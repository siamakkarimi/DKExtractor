from __future__ import annotations
import csv,json,logging,time
from collections import Counter
from datetime import datetime
from pathlib import Path
from selenium.common.exceptions import TimeoutException,WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from core.paths import category_attributes_output_path, ensure_app_dirs, first_step_fields_output_path

logger=logging.getLogger(__name__)
STEP2_HEADERS=["timestamp","product_name","field","items_json"]
STEP3_HEADERS=["timestamp","product_name","field","items_json"]
PLACEHOLDER_TEXT="\u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f"
SEARCH_TEXT_FRAGMENT="\u062c\u0633\u062a"
STEP3_EXPAND_TEXT="\u067e\u0631 \u06a9\u0631\u062f\u0646 \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0628\u06cc\u0634\u062a\u0631"
CONTINUE_TEXT="\u0627\u062f\u0627\u0645\u0647"
COMMISSION_TEXT="\u06a9\u0645\u06cc\u0633\u06cc\u0648\u0646"
SEARCH_PRIMER="\u0627"
DEFAULT_BRAND_TEXT="\u0645\u062a\u0641\u0631\u0642\u0647"
STEP2_SKIP_FIELD_TOKENS=("\u0628\u0631\u0646\u062f","\u0646\u0627\u0645 \u0633\u0627\u0632\u0646\u062f\u0647 \u06a9\u0627\u0644\u0627")
BRAND_WAIT_SECONDS=12
GENERAL_INFO_CONTAINER_XPATH="//div[contains(@class,'FormComponentFrame__input-container')][.//span[normalize-space()='"+PLACEHOLDER_TEXT+"'] or .//input[@name='brand_id']]"
SPEC_FIELD_XPATH="//label[contains(@class,'DropDown__container') or contains(@class,'DropDownMultiple__container')]"
POPPER_XPATH="//div[(@data-popper-placement or @role='list' or contains(@class,'DropDown__popper__') or contains(@class,'DropDownMultiple__popper__')) and not(contains(@style,'display: none'))]"
STEP3_EXPAND_EXACT_NODE_XPATH=f"//*[self::button or self::div or self::span or self::p][normalize-space(text())='{STEP3_EXPAND_TEXT}']"
STEP3_EXPAND_FALLBACK_NODE_XPATH=f"//*[self::button or self::div or self::span or self::p][contains(normalize-space(text()),'{STEP3_EXPAND_TEXT}')]"
STEP3_EXPAND_MAX_TEXT_LENGTH=120
STEP3_EXPAND_MAX_ANCESTOR_DEPTH=3

class Extractor:
    def __init__(self,driver):
        self.driver=driver; self.wait=WebDriverWait(driver,30); self.short_wait=WebDriverWait(driver,5); self._brand_handled=False; self._brand_resolved=False
    def extract_product(self,product_name:str)->tuple[list[dict[str,list[str]]],list[dict[str,list[str]]]]:
        self._brand_handled=False; self._brand_resolved=False
        logger.info("extract.start product=%s url=%s page_state=%s",product_name,self.driver.current_url,self._page_state())
        self._wait_for_step2_ready(); step2=self.extract_step2(); self.complete_step2_required_fields(product_name); step3=self.extract_step3()
        logger.info("extract.done product=%s step2_fields=%s step3_fields=%s",product_name,len(step2),len(step3)); return step2,step3
    def extract_step2(self)->list[dict[str,list[str]]]:
        refs=self._list_step2_fields(); logger.info("step2.scan.start page_state=%s field_count=%s",self._page_state(),len(refs))
        results=self._dedupe_stage_rows(self._extract_fields(refs,"step2"),"step2")
        logger.info("step2.aggregate.done count=%s",len(results))
        return results
    def complete_step2_required_fields(self,product_name:str)->None:
        logger.info("step2.fill.start product=%s",product_name); selected=self._select_brand(); logger.info("step2.fill.brand product=%s selected=%s",product_name,selected or "")
        self._fill_model_input(); self._fill_remaining_general_dropdowns(); self._fill_numeric_inputs(); self._advance_to_step3(); logger.info("step2.fill.done product=%s",product_name)
    def extract_step3(self)->list[dict[str,list[str]]]:
        self._ensure_step3_panel_open(); self._wait_for_step3_ready()
        initial_refs=self._list_step3_fields()
        logger.info("step3.scan.start page_state=%s field_count=%s",self._page_state(),len(initial_refs))
        results=self._dedupe_stage_rows(self._extract_fields(initial_refs,"step3"),"step3")
        optional_refs=self._expand_and_list_step3_optional_fields(initial_refs)
        if optional_refs:
            results=self._merge_stage_results(results,self._extract_fields(optional_refs,"step3"),"step3","optional")
        results=self._dedupe_stage_rows(results,"step3")
        logger.info("step3.aggregate.done count=%s",len(results))
        return results
    def save(self,name:str,step2:list[dict[str,list[str]]],step3:list[dict[str,list[str]]])->None:
        ensure_app_dirs(); ts=datetime.now().isoformat(timespec="seconds")
        step2_rows=self._dedupe_stage_rows(step2,"step2")
        step3_rows=self._dedupe_stage_rows(step3,"step3")
        logger.info("save.step2.rows count=%s",len(step2_rows))
        logger.info("save.step3.rows count=%s",len(step3_rows))
        self._append_rows(first_step_fields_output_path(),STEP2_HEADERS,[[ts,name,i["field"],json.dumps(i["items"],ensure_ascii=False)] for i in step2_rows])
        self._append_rows(category_attributes_output_path(),STEP3_HEADERS,[[ts,name,i["field"],json.dumps(i["items"],ensure_ascii=False)] for i in step3_rows])
    def _extract_fields(self,refs:list[dict[str,object]],stage:str)->list[dict[str,list[str]]]:
        results=[]
        for ref in refs:
            field_name=str(ref["label"]); occurrence=int(ref["occurrence"]); container=self._locate_field_container(stage,field_name,occurrence)
            if container is None:
                logger.warning("%s.field.missing field=%s occurrence=%s",stage,field_name,occurrence); results.append({"field":field_name,"items":[]}); logger.warning("%s.field.final_empty field=%s reason=missing-container",stage,field_name); continue
            if stage=="step2" and self._should_skip_step2_container(container,field_name):
                logger.info("step2.skip.preclick field=%s source=extract",self._get_step2_skip_label(container,field_name))
                continue
            field_type=self._detect_dropdown_type(container); logger.info("%s.field.detected field=%s type=%s",stage,field_name,field_type)
            if self._is_disabled(container):
                logger.info("%s.field.skip field=%s type=%s reason=disabled",stage,field_name,field_type); continue
            items=[]; valid=False
            for attempt in range(1,4):
                popper_detected=False
                try:
                    refreshed=self._locate_field_container(stage,field_name,occurrence)
                    if refreshed is None: raise RuntimeError("Container disappeared before attempt")
                    trigger=self._find_dropdown_trigger(refreshed)
                    if trigger is None:
                        logger.info("%s.field.skip field=%s type=%s attempt=%s reason=no-valid-trigger",stage,field_name,field_type,attempt); break
                    popper=self._open_dropdown(trigger); popper_detected=popper is not None
                    if field_type=="searchable": self._prime_searchable_dropdown(popper)
                    items=self._collect_open_dropdown_options(popper); valid=self._validate_options(items)
                    logger.info("%s.field.attempt field=%s type=%s attempt=%s popper_detected=%s option_count=%s valid=%s",stage,field_name,field_type,attempt,popper_detected,len(items),valid)
                    self._close_dropdown(trigger)
                    if valid: break
                except Exception:
                    logger.exception("%s.field.error field=%s type=%s attempt=%s popper_detected=%s",stage,field_name,field_type,attempt,popper_detected)
                    try:
                        refreshed=self._locate_field_container(stage,field_name,occurrence)
                        if refreshed is not None: self._close_dropdown(self._find_dropdown_trigger(refreshed))
                    except Exception: logger.debug("%s.field.cleanup_failed field=%s",stage,field_name,exc_info=True)
                time.sleep(0.2)
            if not valid: logger.warning("%s.field.final_empty field=%s type=%s option_count=%s",stage,field_name,field_type,len(items))
            results.append({"field":field_name,"items":items if valid else []})
        return results
    def _wait_for_step2_ready(self)->None:
        def _ready(_:object)->bool:
            return "/product/create/2" in self.driver.current_url and (bool(self._find_elements(By.XPATH,GENERAL_INFO_CONTAINER_XPATH)) or bool(self._find_elements(By.NAME,"model")))
        self.wait.until(_ready); logger.info("step2.ready url=%s",self.driver.current_url)
    def _wait_for_step3_ready(self)->None:
        self.wait.until(lambda _:"/product/create/3" in self.driver.current_url and self._step3_fields_ready()); logger.info("step3.ready url=%s",self.driver.current_url)
    def _list_step2_fields(self)->list[dict[str,object]]:
        counters=Counter(); fields=[]
        for container in self._find_elements(By.XPATH,GENERAL_INFO_CONTAINER_XPATH):
            if self._candidate_trigger_from_container(container) is None: continue
            label=self._find_label_text(container)
            if not label: continue
            if self._should_skip_step2_container(container,label):
                logger.info("step2.skip.preclick field=%s source=list",self._get_step2_skip_label(container,label))
                continue
            counters[label]+=1; fields.append({"label":label,"occurrence":counters[label]})
        return fields
    def _list_step3_fields(self)->list[dict[str,object]]:
        self._ensure_step3_panel_open(); self._wait_for_step3_ready(); counters=Counter(); fields=[]
        for container in self._find_elements(By.XPATH,SPEC_FIELD_XPATH):
            if not self._is_visible(container): continue
            label=self._find_label_text(container)
            if not label: continue
            counters[label]+=1; fields.append({"label":label,"occurrence":counters[label]})
        return fields
    def _expand_and_list_step3_optional_fields(self,existing_refs:list[dict[str,object]])->list[dict[str,object]]:
        known_keys={self._step3_ref_key(ref) for ref in existing_refs}; before_count=len(known_keys)
        logger.info("step3.optional.expand.start existing_fields=%s",before_count)
        expand_state=self._expand_step3_optional_section(before_count)
        if expand_state=="already_open":
            logger.info("step3.optional.expand.skipped already_open")
        elif expand_state=="clicked":
            logger.info("step3.optional.expand.clicked")
        else:
            logger.info("step3.optional.expand.skipped reason=%s",expand_state)
            return []
        logger.info("step3.optional.scan.start existing_fields=%s",before_count)
        fields=[]; counters=Counter()
        for container in self._find_elements(By.XPATH,SPEC_FIELD_XPATH):
            if not self._is_visible(container): continue
            label=self._find_label_text(container)
            if not label: continue
            counters[label]+=1
            ref={"label":label,"occurrence":counters[label]}
            ref_key=self._step3_ref_key(ref)
            if ref_key in known_keys: continue
            field_type=self._detect_dropdown_type(container)
            logger.info("step3.optional.field.detected field=%s type=%s",label,field_type)
            known_keys.add(ref_key); fields.append(ref)
        logger.info("step3.optional.scan.done count=%s",len(fields))
        return fields
    def _locate_field_container(self,stage:str,label:str,occurrence:int)->WebElement|None:
        xpath=GENERAL_INFO_CONTAINER_XPATH if stage=="step2" else SPEC_FIELD_XPATH
        matches=[c for c in self._find_elements(By.XPATH,xpath) if self._is_visible(c) and self._find_label_text(c)==label]
        return matches[occurrence-1] if occurrence<=len(matches) else None
    def _find_dropdown_trigger(self,container:WebElement)->WebElement|None:
        for candidate in self._dropdown_trigger_candidates(container):
            if not self._is_visible(candidate) or self._is_disabled(candidate) or self._looks_static(candidate): continue
            popper=None
            try:
                popper=self._click_for_new_popper(candidate,self._visible_poppers(),retries=1)
                if popper is not None:
                    logger.info("trigger.valid field=%s candidate=%s",self._find_label_text(container),self._safe_text(candidate)); self._close_dropdown(candidate); return candidate
            except Exception:
                logger.debug("trigger.reject candidate probe failed",exc_info=True)
                try: self._close_dropdown(candidate)
                except Exception: logger.debug("trigger.reject cleanup failed",exc_info=True)
            finally:
                if popper is not None:
                    try: self._close_dropdown(candidate)
                    except Exception: logger.debug("trigger.final cleanup failed",exc_info=True)
        logger.info("trigger.invalid field=%s",self._find_label_text(container)); return None
    def _detect_dropdown_type(self,container:WebElement)->str:
        class_name=(container.get_attribute("class") or "").lower()
        chips=container.find_elements(By.XPATH,".//*[contains(@class,'chip') or contains(@class,'tag')]")
        selected=[e for e in container.find_elements(By.XPATH,".//p[normalize-space()]") if self._safe_text(e) not in {"",PLACEHOLDER_TEXT,self._find_label_text(container)}]
        search_inputs=[e for e in container.find_elements(By.XPATH,".//input[not(@type='hidden')]") if self._is_visible(e)]
        if search_inputs: return "searchable"
        if "dropdownmultiple" in class_name or chips or len(selected)>1: return "multi-select"
        if "dropdown" in class_name or container.find_elements(By.XPATH,f".//span[normalize-space()='{PLACEHOLDER_TEXT}']"): return "single-select"
        return "unknown"
    def _open_dropdown(self,trigger:WebElement)->WebElement:
        popper=self._click_for_new_popper(trigger,self._visible_poppers(),retries=2)
        if popper is None: raise TimeoutException("Dropdown popper did not open")
        return popper
    def _click_for_new_popper(self,trigger:WebElement,previous_poppers:list[WebElement],retries:int)->WebElement|None:
        for _ in range(retries+1):
            self._scroll_into_view(trigger)
            try: self.short_wait.until(EC.element_to_be_clickable(trigger)); trigger.click()
            except Exception: self._js_click(trigger)
            try: return self.short_wait.until(lambda _:self._resolve_popper_for_trigger(trigger,previous_poppers))
            except TimeoutException: time.sleep(0.2)
        return None
    def _resolve_popper_for_trigger(self,trigger:WebElement,previous_poppers:list[WebElement])->WebElement|None:
        previous_ids={e.id for e in previous_poppers}; visible=self._visible_poppers()
        for popper in visible:
            if popper.id not in previous_ids and self._is_visible(popper): return popper
        trigger_controls=(trigger.get_attribute("aria-controls") or "").strip(); trigger_labelled=(trigger.get_attribute("aria-labelledby") or "").strip()
        for popper in visible:
            if trigger_controls and (popper.get_attribute("id") or "").strip()==trigger_controls: return popper
            if trigger_labelled and (popper.get_attribute("aria-labelledby") or "").strip()==trigger_labelled: return popper
        return self._nearest_popper_to_trigger(trigger,visible)
    def _nearest_popper_to_trigger(self,trigger:WebElement,poppers:list[WebElement])->WebElement|None:
        best=None; best_distance=None
        for popper in poppers:
            try:
                distance=float(self.driver.execute_script("const t=arguments[0].getBoundingClientRect();const p=arguments[1].getBoundingClientRect();return Math.hypot((t.left+t.width/2)-(p.left+p.width/2),(t.top+t.height/2)-(p.top+p.height/2));",trigger,popper))
            except Exception: continue
            if best_distance is None or distance<best_distance: best_distance=distance; best=popper
        return best
    def _collect_open_dropdown_options(self,popper:WebElement)->list[str]:
        last_count=-1; stable_rounds=0; collected=[]
        for _ in range(12):
            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;",popper); time.sleep(0.15); current=[]
            for node in popper.find_elements(By.XPATH,".//p[normalize-space()]"):
                text=self._safe_text(node)
                if not text or text==PLACEHOLDER_TEXT or SEARCH_TEXT_FRAGMENT in text: continue
                if text not in current: current.append(text)
            stable_rounds=stable_rounds+1 if len(current)==last_count else 0; collected=current; last_count=len(current)
            if stable_rounds>=2: break
        return collected
    def _validate_options(self,items:list[str])->bool:
        cleaned=[i.strip() for i in items if i and i.strip()]
        return bool(cleaned) and set(cleaned)!={PLACEHOLDER_TEXT}
    def _close_dropdown(self,trigger:WebElement|None)->None:
        if trigger is None: return
        try: self._js_click(trigger); time.sleep(0.2)
        except Exception:
            logger.debug("dropdown.close click failed",exc_info=True); self.driver.execute_script("document.body.click();"); time.sleep(0.2)
    def _prime_searchable_dropdown(self,popper:WebElement)->None:
        inputs=[e for e in popper.find_elements(By.XPATH,".//input[not(@type='hidden')]") if self._is_visible(e)]
        if not inputs: return
        try:
            search_input=inputs[0]
            if not (search_input.get_attribute("value") or "").strip():
                search_input.click(); search_input.send_keys(SEARCH_PRIMER); time.sleep(0.3); search_input.clear(); time.sleep(0.2)
        except Exception: logger.debug("dropdown.search.prime_failed",exc_info=True)
    def _select_brand(self)->str|None:
        brand_inputs=self._find_elements(By.NAME,"brand_id")
        if not brand_inputs: logger.info("step2.brand.skip reason=missing"); return None
        brand_input=brand_inputs[0]; current_value=self._confirm_brand_value(brand_input,log=False)
        if current_value:
            self._brand_handled=True; self._brand_resolved=True
            logger.info("step2.brand.already_resolved value=%s",current_value)
            return current_value
        if self._brand_handled:
            logger.warning("step2.brand.reopen.blocked")
            raise RuntimeError("Brand field is still empty after the previous selection attempt.")
        logger.info("step2.brand.required")
        trigger=self._resolve_brand_trigger(brand_input)
        if trigger is None:
            logger.warning("step2.brand.timeout reason=no-trigger")
            raise RuntimeError("Brand field is required but no clickable brand trigger was found.")
        self._brand_handled=True
        logger.info("step2.brand.opened.once")
        logger.info("step2.brand.waiting_for_user")
        try:
            self._open_brand_once(trigger)
            selected_value=self.wait.until(lambda _ : self._wait_for_brand_selection(brand_input))
            self._brand_resolved=True
            logger.info("step2.brand.selected.confirmed value=%s",selected_value)
            return selected_value
        except Exception:
            logger.warning("step2.brand.selected.unconfirmed")
            logger.warning("step2.brand.timeout")
            raise RuntimeError("Brand selection timed out before the field received a value.")
        finally:
            self._dismiss_open_poppers()
    def _read_brand_value(self,brand_input:WebElement)->str:
        value=(brand_input.get_attribute("value") or "").strip()
        if value:
            return value
        container=self._find_parent_label_or_self(brand_input)
        values=[self._safe_text(node) for node in container.find_elements(By.XPATH,".//p[normalize-space()]")]
        values=[v for v in values if v not in {"",self._find_label_text(container),PLACEHOLDER_TEXT}]
        return values[0] if values else ""
    def _resolve_brand_trigger(self,brand_input:WebElement)->WebElement|None:
        container=self._find_parent_label_or_self(brand_input)
        candidates=[brand_input]
        candidates.extend(container.find_elements(By.XPATH,f".//*[self::span or self::p][normalize-space()='{PLACEHOLDER_TEXT}']"))
        candidates.extend(container.find_elements(By.XPATH,".//*[@role='button' or @role='combobox' or @aria-haspopup='listbox']"))
        if container not in candidates: candidates.append(container)
        for candidate in candidates:
            if self._is_visible(candidate) and not self._is_disabled(candidate):
                return candidate
        return None
    def _open_brand_once(self,trigger:WebElement)->None:
        self._scroll_into_view(trigger)
        try: trigger.click()
        except Exception: self._js_click(trigger)
        time.sleep(0.5)
    def _wait_for_brand_selection(self,brand_input:WebElement)->str|bool:
        deadline=time.time()+BRAND_WAIT_SECONDS
        while time.time()<deadline:
            logger.info("step2.brand.settle.check")
            value=self._confirm_brand_value(brand_input,log=True)
            if value:
                return value
            time.sleep(0.3)
        return False
    def _confirm_brand_value(self,brand_input:WebElement,log:bool)->str:
        value=self._read_brand_value(brand_input)
        if not value:
            return ""
        deadline=time.time()+2
        settled=value
        while time.time()<deadline:
            latest=self._read_brand_value(brand_input)
            if latest:
                settled=latest
            time.sleep(0.15)
        if log and self._brand_validation_cleared(brand_input):
            logger.info("step2.brand.validation.clear")
        return settled
    def _brand_validation_cleared(self,brand_input:WebElement)->bool:
        container=self._find_parent_label_or_self(brand_input)
        errors=[self._normalize_label(self._safe_text(node)) for node in container.find_elements(By.XPATH,".//p[normalize-space()]")]
        return not any("\u062e\u0627\u0644\u06cc" in text and "\u0628\u0631\u0646\u062f" in text for text in errors)
    def _dismiss_open_poppers(self)->None:
        if not self._visible_poppers():
            return
        try: self.driver.execute_script("document.body.click();")
        except Exception: logger.debug("brand.dismiss.failed",exc_info=True)
        time.sleep(0.2)
    def _brand_selection_confirmed(self)->bool:
        for by,value in [(By.CSS_SELECTOR,"div.overflow-hidden[style*='max-height: 26px']"),(By.XPATH,f"//*[contains(text(),'{COMMISSION_TEXT}')]")]:
            if any(e.is_displayed() for e in self._find_elements(by,value)): return True
        return any((e.get_attribute("value") or "").strip() for e in self._find_elements(By.NAME,"brand_id"))
    def _fill_model_input(self)->None:
        model_inputs=self._find_elements(By.NAME,"model")
        if not model_inputs: logger.info("step2.model.skip reason=missing"); return
        model_input=model_inputs[0]
        if (model_input.get_attribute("value") or "").strip(): logger.info("step2.model.skip reason=already-populated"); return
        self._scroll_into_view(model_input); model_input.click(); model_input.clear(); model_input.send_keys("12"); logger.info("step2.model.filled")
    def _fill_remaining_general_dropdowns(self)->None:
        for ref in self._list_step2_fields():
            field_name=str(ref["label"]); occurrence=int(ref["occurrence"]); container=self._locate_field_container("step2",field_name,occurrence)
            if container is None or self._is_disabled(container): 
                if container is not None: logger.info("step2.fill.skip field=%s reason=disabled",field_name)
                continue
            if self._should_skip_step2_container(container,field_name):
                logger.info("step2.skip.preclick field=%s source=fill",self._get_step2_skip_label(container,field_name))
                continue
            if self._is_already_populated(container): logger.info("step2.fill.skip field=%s reason=already-populated",field_name); continue
            trigger=self._find_dropdown_trigger(container)
            if trigger is None: logger.info("step2.fill.skip field=%s reason=no-trigger",field_name); continue
            try:
                popper=self._open_dropdown(trigger); option=self._first_selectable_option(popper)
                if option is None: logger.warning("step2.fill.skip field=%s reason=no-option",field_name); self._close_dropdown(trigger); continue
                self._js_click(option); time.sleep(0.2); logger.info("step2.fill.done field=%s",field_name)
            except Exception: logger.exception("step2.fill.error field=%s",field_name)
            finally: self._close_dropdown(trigger)
    def _fill_numeric_inputs(self)->None:
        for index,input_element in enumerate(self._find_elements(By.XPATH,"//input[@type='tel' and contains(@class,'NumberField')]"),start=1):
            try:
                if (input_element.get_attribute("value") or "").strip(): continue
                self._scroll_into_view(input_element); input_element.clear(); input_element.send_keys("12"); logger.info("step2.number.filled index=%s",index)
            except Exception: logger.exception("step2.number.error index=%s",index)
    def _advance_to_step3(self)->None:
        continue_button=self.wait.until(EC.element_to_be_clickable((By.XPATH,f"//button[.//div[normalize-space()='{CONTINUE_TEXT}']]")))
        self._scroll_into_view(continue_button); self._js_click(continue_button); logger.info("step2.continue.clicked")
        self.wait.until(lambda _:"/product/create/3" in self.driver.current_url); self._ensure_step3_panel_open(); self._wait_for_step3_ready()
    def _first_selectable_option(self,popper:WebElement)->WebElement|None:
        for option in popper.find_elements(By.XPATH,".//p[contains(@class,'pointer') and normalize-space()]"):
            text=self._safe_text(option)
            if text and SEARCH_TEXT_FRAGMENT not in text and text!=PLACEHOLDER_TEXT: return option
        return None
    def _dropdown_trigger_candidates(self,container:WebElement)->list[WebElement]:
        candidates=[]
        for xpath in [".//input[@name='brand_id']",".//input[not(@type='hidden')]",f".//*[self::span or self::p][normalize-space()='{PLACEHOLDER_TEXT}']",".//*[@role='button' or @role='combobox']",".//*[@aria-haspopup='listbox' or @aria-haspopup='menu']",".//*[@tabindex='0']",".//div[contains(@class,'cursor-pointer')]",".//div[contains(@class,'DropDown')]",".//label[contains(@class,'DropDown__container') or contains(@class,'DropDownMultiple__container')]"]:
            for candidate in container.find_elements(By.XPATH,xpath):
                if candidate not in candidates: candidates.append(candidate)
        if container not in candidates: candidates.append(container)
        return candidates
    def _candidate_trigger_from_container(self,container:WebElement)->WebElement|None:
        for candidate in self._dropdown_trigger_candidates(container):
            if self._is_visible(candidate) and not self._looks_static(candidate): return candidate
        return None
    def _visible_poppers(self)->list[WebElement]: return [p for p in self._find_elements(By.XPATH,POPPER_XPATH) if self._is_visible(p)]
    def _find_parent_label_or_self(self,element:WebElement)->WebElement:
        parents=element.find_elements(By.XPATH,"./ancestor::label[1]"); return parents[0] if parents else element
    def _find_label_text(self,element:WebElement)->str:
        for xpath in [".//ancestor::label[1]//p[@data-testid='form-label']",".//p[@data-testid='form-label']",".//ancestor::label[1]//p",".//p"]:
            for candidate in element.find_elements(By.XPATH,xpath):
                text=self._safe_text(candidate)
                if text and text!=PLACEHOLDER_TEXT: return text
        return "Unknown field"
    def _normalize_label(self,label:str)->str:
        return " ".join((label or "").replace("\u200c"," ").split())
    def _should_skip_step2_field(self,label:str)->bool:
        normalized=self._normalize_label(label)
        return any(token in normalized for token in STEP2_SKIP_FIELD_TOKENS)
    def _should_skip_step2_container(self,container:WebElement,label:str="")->bool:
        if container.find_elements(By.NAME,"brand_id"): return True
        return self._should_skip_step2_field(label) or self._should_skip_step2_field(self._find_label_text(container))
    def _get_step2_skip_label(self,container:WebElement,label:str="")->str:
        visible=label or self._find_label_text(container)
        normalized=self._normalize_label(visible)
        return normalized or "\u0628\u0631\u0646\u062f"
    def _is_already_populated(self,container:WebElement)->bool:
        if container.find_elements(By.XPATH,f".//span[normalize-space()='{PLACEHOLDER_TEXT}']"): return False
        chips=container.find_elements(By.XPATH,".//*[contains(@class,'chip') or contains(@class,'tag')]")
        if any(self._safe_text(chip) for chip in chips): return True
        values=[self._safe_text(n) for n in container.find_elements(By.XPATH,".//p[normalize-space()]") if self._safe_text(n) not in {"",self._find_label_text(container),PLACEHOLDER_TEXT}]
        return bool(values)
    def _looks_static(self,element:WebElement)->bool:
        text=self._safe_text(element); class_name=(element.get_attribute("class") or "").lower()
        if "chip" in class_name or "tag" in class_name: return True
        if element.tag_name.lower() in {"input","label","button"}: return False
        if element.get_attribute("role") in {"button","combobox","listbox"}: return False
        if (element.get_attribute("tabindex") or "").strip()=="0": return False
        if element.get_attribute("aria-haspopup"): return False
        return bool(text and text!=PLACEHOLDER_TEXT and element.tag_name.lower() in {"p","span"})
    def _step3_fields_ready(self)->bool:
        visible=[c for c in self._find_elements(By.XPATH,SPEC_FIELD_XPATH) if self._is_visible(c)]
        return any(self._candidate_trigger_from_container(c) is not None for c in visible)
    def _ensure_step3_panel_open(self)->None:
        if self._step3_fields_ready(): return
        expand_button=self._find_step3_expand_click_target()
        if expand_button is None: logger.info("step3.expand.skip reason=missing-button"); return
        self._scroll_into_view(expand_button); self._js_click(expand_button); logger.info("step3.expand.clicked"); self.wait.until(lambda _:self._step3_fields_ready())
    def _expand_step3_optional_section(self,baseline_count:int)->str:
        before_keys={self._step3_ref_key(ref) for ref in self._list_visible_step3_field_refs()}
        expand_button=self._find_step3_expand_click_target()
        if expand_button is None:
            return "already_open" if self._step3_optional_expanded(before_keys,baseline_count) else "missing-button"
        logger.info("step3.optional.button.found tag=%s text=%s",expand_button.tag_name,self._safe_text(expand_button))
        self._scroll_into_view(expand_button); logger.info("step3.optional.button.click")
        try: expand_button.click()
        except Exception: self._js_click(expand_button)
        try:
            self.wait.until(lambda _ : self._step3_optional_expanded(before_keys,baseline_count))
            logger.info("step3.optional.expand.confirmed")
            return "clicked"
        except TimeoutException:
            if self._step3_optional_expanded(before_keys,baseline_count):
                logger.info("step3.optional.expand.confirmed")
                return "clicked"
            logger.info("step3.optional.expand.failed")
            return "no-new-fields"
    def _step3_ref_key(self,ref:dict[str,object])->tuple[str,int]:
        return self._normalize_label(str(ref["label"])),int(ref["occurrence"])
    def _field_result_key(self,field_name:str)->str:
        return self._normalize_label(field_name)
    def _dedupe_stage_rows(self,rows:list[dict[str,list[str]]],stage:str)->list[dict[str,list[str]]]:
        return self._merge_stage_results([],rows,stage,"dedupe")
    def _merge_stage_results(self,existing:list[dict[str,list[str]]],new_rows:list[dict[str,list[str]]],stage:str,source:str)->list[dict[str,list[str]]]:
        merged=[{"field":str(row["field"]),"items":list(row.get("items",[]))} for row in existing]
        index_by_key={self._field_result_key(str(row["field"])):idx for idx,row in enumerate(merged)}
        for row in new_rows:
            field_name=str(row["field"]); key=self._field_result_key(field_name); items=self._merge_items([],list(row.get("items",[])))
            if key not in index_by_key:
                index_by_key[key]=len(merged); merged.append({"field":field_name,"items":items}); continue
            idx=index_by_key[key]; current=merged[idx]
            merged_items=self._merge_items(list(current.get("items",[])),items)
            if merged_items!=current.get("items",[]):
                logger.info("%s.aggregate.merge field=%s source=%s",stage,current["field"],source)
            current["items"]=merged_items
            if (not self._normalize_label(str(current["field"])) or str(current["field"]).startswith("Unknown")) and field_name:
                current["field"]=field_name
        return merged
    def _merge_items(self,existing:list[str],new_items:list[str])->list[str]:
        merged=[]; seen=set()
        for item in [*(existing or []),*(new_items or [])]:
            text=self._normalize_label(str(item))
            if not text or text in seen: continue
            seen.add(text); merged.append(str(item).strip())
        return merged
    def _list_visible_step3_field_refs(self)->list[dict[str,object]]:
        counters=Counter(); fields=[]
        for container in self._find_elements(By.XPATH,SPEC_FIELD_XPATH):
            if not self._is_visible(container): continue
            label=self._find_label_text(container)
            if not label: continue
            counters[label]+=1; fields.append({"label":label,"occurrence":counters[label]})
        return fields
    def _step3_optional_expanded(self,before_keys:set[tuple[str,int]],baseline_count:int)->bool:
        current_refs=self._list_visible_step3_field_refs()
        current_keys={self._step3_ref_key(ref) for ref in current_refs}
        if len(current_keys)>baseline_count and current_keys!=before_keys:
            return True
        return self._find_step3_expand_click_target() is None and len(current_keys)>=baseline_count
    def _find_step3_expand_click_target(self)->WebElement|None:
        for xpath in [STEP3_EXPAND_EXACT_NODE_XPATH,STEP3_EXPAND_FALLBACK_NODE_XPATH]:
            for node in self._find_elements(By.XPATH,xpath):
                if not self._is_visible(node): continue
                target=self._resolve_clickable_ancestor(node)
                if target is None or not self._is_visible(target) or self._is_disabled(target): continue
                return target
        return None
    def _resolve_clickable_ancestor(self,node:WebElement)->WebElement|None:
        for candidate in self._nearby_clickable_candidates(node,STEP3_EXPAND_MAX_ANCESTOR_DEPTH):
            text=self._normalize_label(self._safe_text(candidate))
            if len(text)>STEP3_EXPAND_MAX_TEXT_LENGTH or text.count(" ")>12:
                logger.info("step3.optional.button.rejected reason=oversized-text tag=%s text=%s",candidate.tag_name,text[:200])
                continue
            return candidate
        return None
    def _nearby_clickable_candidates(self,node:WebElement,max_depth:int)->list[WebElement]:
        candidates=[]; current=node; depth=0
        while current is not None and depth<=max_depth:
            if self._is_reasonable_step3_expand_candidate(current) and current not in candidates:
                candidates.append(current)
            parents=current.find_elements(By.XPATH,"./parent::*")
            current=parents[0] if parents else None
            depth+=1
        return candidates
    def _is_reasonable_step3_expand_candidate(self,element:WebElement)->bool:
        if not self._is_visible(element) or self._is_disabled(element): return False
        text=self._normalize_label(self._safe_text(element))
        if not text or STEP3_EXPAND_TEXT not in text: return False
        if len(text)>STEP3_EXPAND_MAX_TEXT_LENGTH: return False
        tag=element.tag_name.lower()
        role=(element.get_attribute("role") or "").strip().lower()
        tabindex=(element.get_attribute("tabindex") or "").strip()
        class_name=(element.get_attribute("class") or "").lower()
        if text==STEP3_EXPAND_TEXT and tag in {"button","a","div","span","p"}:
            return True
        return role in {"button","link"} or tabindex=="0" or "cursor-pointer" in class_name or "pointer" in class_name
    def _is_disabled(self,element:WebElement)->bool:
        try: bg_color=(element.value_of_css_property("background-color") or "").strip().lower()
        except Exception: bg_color=""
        return bg_color in {"rgb(240, 240, 241)","rgba(240, 240, 241, 1)"} or (element.get_attribute("aria-disabled") or "").strip().lower()=="true"
    def _find_elements(self,by:str,value:str)->list[WebElement]:
        try: return self.driver.find_elements(by,value)
        except WebDriverException: logger.debug("find_elements.failed by=%s value=%s",by,value,exc_info=True); return []
    def _scroll_into_view(self,element:WebElement)->None:
        self.driver.execute_script("arguments[0].scrollIntoView({behavior:'instant', block:'center', inline:'center'});",element); time.sleep(0.15)
    def _js_click(self,element:WebElement)->None: self.driver.execute_script("arguments[0].click();",element)
    def _is_visible(self,element:WebElement)->bool:
        try: return element.is_displayed()
        except Exception: return False
    def _safe_text(self,element:WebElement)->str:
        try: return (element.text or "").strip()
        except Exception: return ""
    def _page_state(self)->str:
        url=self.driver.current_url
        if "/product/create/3" in url: return "step3"
        if "/product/create/2" in url: return "step2"
        return "unknown"
    @staticmethod
    def _append_rows(path:Path,headers:list[str],rows:list[list[str]])->None:
        file_exists=path.exists()
        with open(path,"a",newline="",encoding="utf-8-sig") as file_obj:
            writer=csv.writer(file_obj)
            if not file_exists: writer.writerow(headers)
            for row in rows: writer.writerow(row)
