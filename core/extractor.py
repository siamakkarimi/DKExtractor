from __future__ import annotations

import csv
import json
import logging
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.paths import ensure_app_dirs, output_dir

logger = logging.getLogger(__name__)

STEP2_HEADERS = ["timestamp", "product_name", "field", "items_json"]
STEP3_HEADERS = ["timestamp", "product_name", "field", "items_json"]

GENERAL_INFO_CONTAINER_XPATH = (
    "//div[contains(@class,'FormComponentFrame__input-container')]"
    "[.//span[normalize-space()='انتخاب کنید'] or .//input[@name='brand_id']]"
)
SPEC_FIELD_XPATH = (
    "//label[contains(@class,'DropDown__container') or "
    "contains(@class,'DropDownMultiple__container')]"
)
POPPER_XPATH = (
    "//div[("
    "@data-popper-placement or "
    "@role='list' or "
    "contains(@class,'DropDown__popper__') or "
    "contains(@class,'DropDownMultiple__popper__')"
    ") and not(contains(@style,'display: none'))]"
)


class Extractor:
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 30)
        self.short_wait = WebDriverWait(driver, 5)

    def extract_product(self, product_name: str) -> tuple[list[dict[str, list[str]]], list[dict[str, list[str]]]]:
        logger.info(
            "extract.start product=%s url=%s page_state=%s",
            product_name,
            self.driver.current_url,
            self._page_state(),
        )
        self._wait_for_step2_ready()
        step2_results = self.extract_step2()
        self.complete_step2_required_fields(product_name)
        step3_results = self.extract_step3()
        logger.info(
            "extract.done product=%s step2_fields=%s step3_fields=%s",
            product_name,
            len(step2_results),
            len(step3_results),
        )
        return step2_results, step3_results

    def extract_step2(self) -> list[dict[str, list[str]]]:
        field_refs = self._list_step2_fields()
        logger.info(
            "step2.scan.start page_state=%s field_count=%s",
            self._page_state(),
            len(field_refs),
        )
        return self._extract_fields(field_refs, stage="step2")

    def complete_step2_required_fields(self, product_name: str) -> None:
        logger.info("step2.fill.start product=%s", product_name)
        selected_brand = self._select_brand()
        logger.info("step2.fill.brand product=%s selected=%s", product_name, selected_brand or "")
        self._fill_model_input()
        self._fill_remaining_general_dropdowns()
        self._fill_numeric_inputs()
        self._advance_to_step3()
        logger.info("step2.fill.done product=%s", product_name)

    def extract_step3(self) -> list[dict[str, list[str]]]:
        field_refs = self._list_step3_fields()
        logger.info(
            "step3.scan.start page_state=%s field_count=%s",
            self._page_state(),
            len(field_refs),
        )
        return self._extract_fields(field_refs, stage="step3")

    def save(self, name: str, step2: list[dict[str, list[str]]], step3: list[dict[str, list[str]]]) -> None:
        ensure_app_dirs()
        out = output_dir()
        step2_path = out / "step2.csv"
        step3_path = out / "step3.csv"

        timestamp = datetime.now().isoformat(timespec="seconds")
        step2_rows = [
            [timestamp, name, item["field"], json.dumps(item["items"], ensure_ascii=False)]
            for item in step2
        ]
        step3_rows = [
            [timestamp, name, item["field"], json.dumps(item["items"], ensure_ascii=False)]
            for item in step3
        ]

        self._append_rows(step2_path, STEP2_HEADERS, step2_rows)
        self._append_rows(step3_path, STEP3_HEADERS, step3_rows)

    def _extract_fields(self, field_refs: list[dict[str, object]], stage: str) -> list[dict[str, list[str]]]:
        results: list[dict[str, list[str]]] = []

        for field_ref in field_refs:
            field_name = str(field_ref["label"])
            occurrence = int(field_ref["occurrence"])
            container = self._locate_field_container(stage, field_name, occurrence)

            if container is None:
                logger.warning("%s.field.missing field=%s occurrence=%s", stage, field_name, occurrence)
                results.append({"field": field_name, "items": []})
                logger.warning("%s.field.final_empty field=%s reason=missing-container", stage, field_name)
                continue

            field_type = self._detect_dropdown_type(container)
            logger.info("%s.field.detected field=%s type=%s", stage, field_name, field_type)

            if self._is_disabled(container):
                logger.info("%s.field.skip field=%s type=%s reason=disabled", stage, field_name, field_type)
                continue

            items: list[str] = []
            valid = False

            for attempt in range(1, 4):
                popper_detected = False
                try:
                    refreshed_container = self._locate_field_container(stage, field_name, occurrence)
                    if refreshed_container is None:
                        raise RuntimeError("Container disappeared before attempt")

                    trigger = self._find_dropdown_trigger(refreshed_container)
                    if trigger is None:
                        logger.info(
                            "%s.field.skip field=%s type=%s attempt=%s reason=no-valid-trigger",
                            stage,
                            field_name,
                            field_type,
                            attempt,
                        )
                        break

                    popper = self._open_dropdown(trigger)
                    popper_detected = popper is not None
                    items = self._collect_open_dropdown_options(popper)
                    valid = self._validate_options(items)
                    logger.info(
                        "%s.field.attempt field=%s type=%s attempt=%s popper_detected=%s option_count=%s valid=%s",
                        stage,
                        field_name,
                        field_type,
                        attempt,
                        popper_detected,
                        len(items),
                        valid,
                    )
                    self._close_dropdown(trigger)

                    if valid:
                        break
                except Exception:
                    logger.exception(
                        "%s.field.error field=%s type=%s attempt=%s popper_detected=%s",
                        stage,
                        field_name,
                        field_type,
                        attempt,
                        popper_detected,
                    )
                    try:
                        refreshed_container = self._locate_field_container(stage, field_name, occurrence)
                        if refreshed_container is not None:
                            trigger = self._find_dropdown_trigger(refreshed_container)
                            self._close_dropdown(trigger)
                    except Exception:
                        logger.debug("%s.field.cleanup_failed field=%s", stage, field_name, exc_info=True)

                time.sleep(0.2)

            if not valid:
                logger.warning(
                    "%s.field.final_empty field=%s type=%s option_count=%s",
                    stage,
                    field_name,
                    field_type,
                    len(items),
                )

            results.append({"field": field_name, "items": items if valid else []})

        return results

    def _wait_for_step2_ready(self) -> None:
        def _ready(_: object) -> bool:
            if "/product/create/2" not in self.driver.current_url:
                return False
            return bool(self._find_elements(By.XPATH, GENERAL_INFO_CONTAINER_XPATH)) or bool(
                self._find_elements(By.NAME, "model")
            )

        self.wait.until(_ready)
        logger.info("step2.ready url=%s", self.driver.current_url)

    def _wait_for_step3_ready(self) -> None:
        def _ready(_: object) -> bool:
            return "/product/create/3" in self.driver.current_url or bool(
                self._find_elements(By.XPATH, SPEC_FIELD_XPATH)
            )

        self.wait.until(_ready)
        logger.info("step3.ready url=%s", self.driver.current_url)

    def _list_step2_fields(self) -> list[dict[str, object]]:
        counters: Counter[str] = Counter()
        fields: list[dict[str, object]] = []

        for container in self._find_elements(By.XPATH, GENERAL_INFO_CONTAINER_XPATH):
            trigger = self._candidate_trigger_from_container(container)
            if trigger is None:
                continue

            label = self._find_label_text(container)
            if not label:
                continue

            counters[label] += 1
            fields.append({"label": label, "occurrence": counters[label]})

        return fields

    def _list_step3_fields(self) -> list[dict[str, object]]:
        self._wait_for_step3_ready()
        counters: Counter[str] = Counter()
        fields: list[dict[str, object]] = []

        for container in self._find_elements(By.XPATH, SPEC_FIELD_XPATH):
            label = self._find_label_text(container)
            if not label:
                continue

            counters[label] += 1
            fields.append({"label": label, "occurrence": counters[label]})

        return fields

    def _locate_field_container(self, stage: str, label: str, occurrence: int) -> WebElement | None:
        xpath = GENERAL_INFO_CONTAINER_XPATH if stage == "step2" else SPEC_FIELD_XPATH
        matches: list[WebElement] = []

        for container in self._find_elements(By.XPATH, xpath):
            if self._find_label_text(container) == label:
                matches.append(container)

        if occurrence <= len(matches):
            return matches[occurrence - 1]
        return None

    def _find_dropdown_trigger(self, container: WebElement) -> WebElement | None:
        for candidate in self._dropdown_trigger_candidates(container):
            if not self._is_visible(candidate):
                continue
            if self._is_disabled(candidate) or self._looks_static(candidate):
                continue

            popper = None
            try:
                previous_poppers = self._visible_poppers()
                popper = self._click_for_new_popper(candidate, previous_poppers, retries=1)
                if popper is not None:
                    logger.info(
                        "trigger.valid field=%s candidate=%s",
                        self._find_label_text(container),
                        self._safe_text(candidate),
                    )
                    self._close_dropdown(candidate)
                    return candidate
            except Exception:
                logger.debug("trigger.reject candidate probe failed", exc_info=True)
                try:
                    self._close_dropdown(candidate)
                except Exception:
                    logger.debug("trigger.reject cleanup failed", exc_info=True)
            finally:
                if popper is not None:
                    try:
                        self._close_dropdown(candidate)
                    except Exception:
                        logger.debug("trigger.final cleanup failed", exc_info=True)

        logger.info("trigger.invalid field=%s", self._find_label_text(container))
        return None

    def _detect_dropdown_type(self, container: WebElement) -> str:
        class_name = (container.get_attribute("class") or "").lower()
        chips = container.find_elements(By.XPATH, ".//*[contains(@class,'chip') or contains(@class,'tag')]")
        selected_items = [
            element
            for element in container.find_elements(By.XPATH, ".//p[normalize-space()]")
            if self._safe_text(element) not in {"", "انتخاب کنید", self._find_label_text(container)}
        ]
        search_inputs = container.find_elements(By.XPATH, ".//input[not(@type='hidden')]")

        if search_inputs:
            return "searchable"
        if "dropdownmultiple" in class_name or len(chips) > 0 or len(selected_items) > 1:
            return "multi-select"
        if "dropdown" in class_name or container.find_elements(By.XPATH, ".//span[normalize-space()='انتخاب کنید']"):
            return "single-select"
        return "unknown"

    def _open_dropdown(self, trigger: WebElement) -> WebElement:
        previous_poppers = self._visible_poppers()
        popper = self._click_for_new_popper(trigger, previous_poppers, retries=2)
        if popper is None:
            raise TimeoutException("Dropdown popper did not open")
        return popper

    def _click_for_new_popper(
        self,
        trigger: WebElement,
        previous_poppers: list[WebElement],
        retries: int,
    ) -> WebElement | None:
        for _ in range(retries + 1):
            self._scroll_into_view(trigger)
            try:
                self.short_wait.until(EC.element_to_be_clickable(trigger))
                trigger.click()
            except Exception:
                self._js_click(trigger)

            try:
                return self.short_wait.until(lambda _: self._get_new_popper(previous_poppers))
            except TimeoutException:
                time.sleep(0.2)

        return None

    def _get_new_popper(self, previous_poppers: list[WebElement]) -> WebElement | None:
        previous_ids = {element.id for element in previous_poppers}
        for popper in self._visible_poppers():
            if popper.id not in previous_ids and self._is_visible(popper):
                return popper
        return None

    def _collect_open_dropdown_options(self, popper: WebElement) -> list[str]:
        last_count = -1
        stable_rounds = 0
        collected: list[str] = []

        for _ in range(12):
            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", popper)
            time.sleep(0.15)

            current_items: list[str] = []
            option_nodes = popper.find_elements(By.XPATH, ".//p[normalize-space()]")
            for node in option_nodes:
                text = self._safe_text(node)
                if not text or text == "انتخاب کنید" or "جست" in text:
                    continue
                if text not in current_items:
                    current_items.append(text)

            if len(current_items) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0

            collected = current_items
            last_count = len(current_items)

            if stable_rounds >= 2:
                break

        return collected

    def _validate_options(self, items: list[str]) -> bool:
        cleaned = [item.strip() for item in items if item and item.strip()]
        if len(cleaned) < 2:
            return False
        if all(item == cleaned[0] for item in cleaned):
            return False
        if set(cleaned) == {"انتخاب کنید"}:
            return False
        return True

    def _close_dropdown(self, trigger: WebElement | None) -> None:
        if trigger is None:
            return

        try:
            self._js_click(trigger)
            time.sleep(0.2)
        except Exception:
            logger.debug("dropdown.close click failed", exc_info=True)
            self.driver.execute_script("document.body.click();")
            time.sleep(0.2)

    def _select_brand(self) -> str | None:
        brand_inputs = self._find_elements(By.NAME, "brand_id")
        if not brand_inputs:
            logger.info("step2.brand.skip reason=missing")
            return None

        brand_input = brand_inputs[0]
        current_value = (brand_input.get_attribute("value") or "").strip()
        if current_value:
            logger.info("step2.brand.skip reason=already-selected")
            return current_value

        brand_container = self._find_parent_label_or_self(brand_input)
        trigger = self._find_dropdown_trigger(brand_container)
        if trigger is None:
            logger.warning("step2.brand.skip reason=no-trigger")
            return None

        popper = self._open_dropdown(trigger)
        cards = self.wait.until(
            lambda _: popper.find_elements(
                By.XPATH,
                ".//div[contains(@class,'pointer') and .//p[contains(@class,'text-subtitle-strong')]]",
            )
        )

        for card in cards:
            try:
                name = self._safe_text(card.find_element(By.CSS_SELECTOR, "p.text-subtitle-strong"))
                self._scroll_into_view(card)
                self._js_click(card)
                time.sleep(0.8)
                if self._brand_selection_confirmed():
                    return name
            except Exception:
                logger.exception("step2.brand.probe_failed")

        return None

    def _brand_selection_confirmed(self) -> bool:
        for by, value in [
            (By.CSS_SELECTOR, "div.overflow-hidden[style*='max-height: 26px']"),
            (By.XPATH, "//*[contains(text(),'کمیسیون')]"),
        ]:
            if any(element.is_displayed() for element in self._find_elements(by, value)):
                return True

        return any((element.get_attribute("value") or "").strip() for element in self._find_elements(By.NAME, "brand_id"))

    def _fill_model_input(self) -> None:
        model_inputs = self._find_elements(By.NAME, "model")
        if not model_inputs:
            logger.info("step2.model.skip reason=missing")
            return

        model_input = model_inputs[0]
        if (model_input.get_attribute("value") or "").strip():
            logger.info("step2.model.skip reason=already-populated")
            return

        self._scroll_into_view(model_input)
        model_input.click()
        model_input.clear()
        model_input.send_keys("12")
        logger.info("step2.model.filled")

    def _fill_remaining_general_dropdowns(self) -> None:
        for field_ref in self._list_step2_fields():
            field_name = str(field_ref["label"])
            occurrence = int(field_ref["occurrence"])
            container = self._locate_field_container("step2", field_name, occurrence)
            if container is None:
                continue

            if self._is_disabled(container):
                logger.info("step2.fill.skip field=%s reason=disabled", field_name)
                continue

            if self._is_already_populated(container):
                logger.info("step2.fill.skip field=%s reason=already-populated", field_name)
                continue

            trigger = self._find_dropdown_trigger(container)
            if trigger is None:
                logger.info("step2.fill.skip field=%s reason=no-trigger", field_name)
                continue

            try:
                popper = self._open_dropdown(trigger)
                option = self._first_selectable_option(popper)
                if option is None:
                    logger.warning("step2.fill.skip field=%s reason=no-option", field_name)
                    self._close_dropdown(trigger)
                    continue
                self._js_click(option)
                time.sleep(0.2)
                logger.info("step2.fill.done field=%s", field_name)
            except Exception:
                logger.exception("step2.fill.error field=%s", field_name)
            finally:
                self._close_dropdown(trigger)

    def _fill_numeric_inputs(self) -> None:
        numeric_inputs = self._find_elements(By.XPATH, "//input[@type='tel' and contains(@class,'NumberField')]")
        for index, input_element in enumerate(numeric_inputs, start=1):
            try:
                if (input_element.get_attribute("value") or "").strip():
                    continue
                self._scroll_into_view(input_element)
                input_element.clear()
                input_element.send_keys("12")
                logger.info("step2.number.filled index=%s", index)
            except Exception:
                logger.exception("step2.number.error index=%s", index)

    def _advance_to_step3(self) -> None:
        continue_button = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[.//div[normalize-space()='ادامه']]"))
        )
        self._scroll_into_view(continue_button)
        self._js_click(continue_button)
        logger.info("step2.continue.clicked")
        self._wait_for_step3_ready()

    def _first_selectable_option(self, popper: WebElement) -> WebElement | None:
        for option in popper.find_elements(By.XPATH, ".//p[contains(@class,'pointer') and normalize-space()]"):
            text = self._safe_text(option)
            if text and "جست" not in text and text != "انتخاب کنید":
                return option
        return None

    def _dropdown_trigger_candidates(self, container: WebElement) -> list[WebElement]:
        candidates: list[WebElement] = []
        for xpath in [
            ".//input[@name='brand_id']",
            ".//*[self::span or self::p][normalize-space()='انتخاب کنید']",
            ".//*[@role='button']",
            ".//div[contains(@class,'cursor-pointer')]",
            ".//div[contains(@class,'DropDown')]",
        ]:
            for candidate in container.find_elements(By.XPATH, xpath):
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _candidate_trigger_from_container(self, container: WebElement) -> WebElement | None:
        for candidate in self._dropdown_trigger_candidates(container):
            if self._is_visible(candidate) and not self._looks_static(candidate):
                return candidate
        return None

    def _visible_poppers(self) -> list[WebElement]:
        return [popper for popper in self._find_elements(By.XPATH, POPPER_XPATH) if self._is_visible(popper)]

    def _find_parent_label_or_self(self, element: WebElement) -> WebElement:
        parents = element.find_elements(By.XPATH, "./ancestor::label[1]")
        return parents[0] if parents else element

    def _find_label_text(self, element: WebElement) -> str:
        for xpath in [
            ".//ancestor::label[1]//p[@data-testid='form-label']",
            ".//p[@data-testid='form-label']",
            ".//ancestor::label[1]//p",
            ".//p",
        ]:
            for candidate in element.find_elements(By.XPATH, xpath):
                text = self._safe_text(candidate)
                if text and text != "انتخاب کنید":
                    return text
        return "Unknown field"

    def _is_already_populated(self, container: WebElement) -> bool:
        placeholder = container.find_elements(By.XPATH, ".//span[normalize-space()='انتخاب کنید']")
        if placeholder:
            return False

        chips = container.find_elements(By.XPATH, ".//*[contains(@class,'chip') or contains(@class,'tag')]")
        if any(self._safe_text(chip) for chip in chips):
            return True

        values = [
            self._safe_text(node)
            for node in container.find_elements(By.XPATH, ".//p[normalize-space()]")
            if self._safe_text(node) not in {"", self._find_label_text(container), "انتخاب کنید"}
        ]
        return bool(values)

    def _looks_static(self, element: WebElement) -> bool:
        text = self._safe_text(element)
        class_name = (element.get_attribute("class") or "").lower()
        if "chip" in class_name or "tag" in class_name:
            return True
        if text and text != "انتخاب کنید" and element.tag_name.lower() in {"p", "span"}:
            return True
        return False

    def _is_disabled(self, element: WebElement) -> bool:
        try:
            bg_color = (element.value_of_css_property("background-color") or "").strip().lower()
        except Exception:
            bg_color = ""

        if bg_color in {"rgb(240, 240, 241)", "rgba(240, 240, 241, 1)"}:
            return True

        aria_disabled = (element.get_attribute("aria-disabled") or "").strip().lower()
        return aria_disabled == "true"

    def _find_elements(self, by: str, value: str) -> list[WebElement]:
        try:
            return self.driver.find_elements(by, value)
        except WebDriverException:
            logger.debug("find_elements.failed by=%s value=%s", by, value, exc_info=True)
            return []

    def _scroll_into_view(self, element: WebElement) -> None:
        self.driver.execute_script(
            "arguments[0].scrollIntoView({behavior:'instant', block:'center', inline:'center'});",
            element,
        )
        time.sleep(0.15)

    def _js_click(self, element: WebElement) -> None:
        self.driver.execute_script("arguments[0].click();", element)

    def _is_visible(self, element: WebElement) -> bool:
        try:
            return element.is_displayed()
        except Exception:
            return False

    def _safe_text(self, element: WebElement) -> str:
        try:
            return (element.text or "").strip()
        except Exception:
            return ""

    def _page_state(self) -> str:
        url = self.driver.current_url
        if "/product/create/3" in url:
            return "step3"
        if "/product/create/2" in url:
            return "step2"
        return "unknown"

    @staticmethod
    def _append_rows(path: Path, headers: list[str], rows: list[list[str]]) -> None:
        file_exists = path.exists()

        with open(path, "a", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.writer(file_obj)
            if not file_exists:
                writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
