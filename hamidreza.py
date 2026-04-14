from selenium import webdriver
import pandas as pd
import csv,os
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time,random

file_path_first_step = "digikala_all_first_step.csv"
file_path_categories = "digikala_all_categories.csv"


write_first = not os.path.exists(file_path_first_step)  # اگر فایل وجود نداشت، هدر اضافه شود
write_category = not os.path.exists(file_path_categories)

service = Service(executable_path=r"C:\WebDriver\bin\chromedriver.exe")
options = Options()
# اگر میخوای به Chrome باز وصل شی
options.debugger_address = "127.0.0.1:9222"

driver = webdriver.Chrome(service=service, options=options)
wait = WebDriverWait(driver, 20)

def first_step_field():
    fields = wait.until(EC.presence_of_all_elements_located(
        (By.XPATH, "//div[contains(@class, 'FormComponentFrame__input-container-fArle6')]//span[contains(text(), 'انتخاب کنید')]")
    ))
    name_list = ["نوع کالا","دسته بندی کالا","مبدا کالا","شناسه عمومی"]
    all_items = [] 
    for i in range(len(fields)):
        try:
            # دوباره گرفتن field بعد از هر تغییر DOM
            fields = driver.find_elements(
                By.XPATH, "//div[contains(@class, 'FormComponentFrame__input-container-fArle6')]//span[contains(text(), 'انتخاب کنید')]"
            )
            field = fields[i]

            label_text = field.find_element(
                By.XPATH, ".//ancestor::label//p[@data-testid='form-label']"
            ).text.strip()

            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'start'});", field)
            time.sleep(0.5)
            field.click()

            # گرفتن آیتم‌ها
            items = wait.until(
                EC.presence_of_all_elements_located(
                    (By.XPATH, "//div[@data-popper-placement='bottom']//p")
                )
            )
            result = [item.text.strip() for item in items if item.text.strip()]
            all_items.append((label_text,result))
            
            # بستن منوی کشویی
            driver.execute_script("arguments[0].click();", field)
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ خطا در فیلد {i}: {e}")
    with open(file_path_first_step, "a", newline="", encoding="utf-8") as f:  # حالت append
        writer = csv.writer(f)
        if write_first:
            writer.writerow(["label_text", "result"])
        for label_text, result in all_items:
            writer.writerow([label_text, result])
def complet_first_step_field():
    brand_field = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.NAME, "brand_id"))
    )
    driver.execute_script("arguments[0].click();", brand_field)
    time.sleep(1)

    brand_divs = wait.until(
        EC.presence_of_all_elements_located(
            (By.XPATH, "//div[contains(@class,'pointer') and .//p[contains(@class,'text-subtitle-strong')]]")
        )
    )

    selected_brand = None

    for div in brand_divs:
        try:
            name_elem = div.find_element(By.CSS_SELECTOR, "p.text-subtitle-strong.color-n-700")
            brand_name = name_elem.text.strip()
            print(f"تست برند: {brand_name}")

            # scroll + wait
            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", div)
            time.sleep(0.5)

            # force click
            driver.execute_script("arguments[0].click();", div)
            time.sleep(1)

            # بررسی کمیسیون
            try:
                commission_div = driver.find_element(By.CSS_SELECTOR, 
                    "div.overflow-hidden[style*='max-height: 26px']")
                if commission_div.is_displayed():
                    print(f"✅ برند {brand_name} درست است")
                    selected_brand = brand_name
                    break  # برند درست پیدا شد
            except:
                print(f"❌ برند {brand_name} درست نیست، برو به بعدی")
                continue  # برند بعدی را بررسی کن


        except Exception as e:
            print(f"❌ خطا در بررسی برند {brand_name}: {e}")
            continue

    select_boxes = wait.until(EC.element_to_be_clickable((
        By.XPATH, "//span[normalize-space()='انتخاب کنید']"
    )))

    bg_color = select_boxes.value_of_css_property("background-color")

    if bg_color == "rgb(255, 255, 255)":
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", select_boxes)
        driver.execute_script("arguments[0].click();", select_boxes)
        
        option = wait.until(
            EC.element_to_be_clickable((
                By.XPATH, "//div[@role='list']//p[contains(@class,'pointer')][1]"
            ))
        )

        driver.execute_script("arguments[0].click();", option)




        # کلیک روی دکمه تایید
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", select_boxes)

        
    inp = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//input[@name='model']")
    ))

    driver.execute_script("arguments[0].scrollIntoView({block:'start'});", inp)
    time.sleep(1)
    inp.click()
    inp.clear()
    inp.send_keys("12")

    fields = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'FormComponentFrame__input-container')][.//span[text()='انتخاب کنید']]"
    )

    for field in fields:
        try:
            bg_color = field.value_of_css_property("background-color")
            if bg_color == "rgb(240, 240, 241)":
                continue

            # کلیک روی فیلد
            driver.execute_script("arguments[0].scrollIntoView({block:'start'});", field)
            time.sleep(0.5)
            wait.until(EC.element_to_be_clickable(field)).click()
            time.sleep(0.3)
            has_p = field.find_elements(By.XPATH, ".//p")
            # گزینه‌ها
            options = wait.until(
                EC.presence_of_all_elements_located(
                    (By.XPATH, "//div[@role='list']//p[contains(@class,'pointer')]")
                )
            )
            time.sleep(0.3)

            if options:
                option = random.choice(options)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", option)
                driver.execute_script("arguments[0].click();", option)
                time.sleep(0.3)

            # بررسی نوع فیلد
            if not has_p:
                # حالت span → دوباره کلیک برای بستن
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", field)
            # حالت p → رد می‌شه و کاری انجام نمی‌ده

        except Exception:
            continue

        
    inputs = driver.find_elements(By.XPATH, "//input[@type='tel' and contains(@class,'NumberField')]")

    for inp in inputs:
        driver.execute_script("arguments[0].scrollIntoView({behavior:'smooth', block:'start'});", inp)
        inp.clear()
        inp.send_keys("12")
        

    continue_btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[.//div[text()='ادامه']]")
        )
    )
    driver.execute_script("arguments[0].click();", continue_btn)
    print(f"ادامه زده شد برای برند: {selected_brand}")

def Category_Attributes():
    result = []

    btn = wait.until(EC.element_to_be_clickable((
        By.XPATH,
        "//div[contains(normalize-space(text()),'پر کردن اطلاعات بیشتر')]"
    )))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    driver.execute_script("arguments[0].click();", btn)

    labels = wait.until(EC.presence_of_all_elements_located((
        By.XPATH,
        "//label[contains(@class,'DropDown__container') or contains(@class,'DropDownMultiple__container')]"
    )))

    for label in labels:
        try:
            result.clear()

            title = label.find_element(
                By.XPATH,
                ".//p[@data-testid='form-label']"
            ).text

            select_btn = label.find_element(
                By.XPATH,
                ".//*[self::span or self::p][normalize-space()='انتخاب کنید']"
            )

            bg = label.value_of_css_property("background-color")
            if bg == "rgb(240, 240, 241)":
                continue

            popper = wait.until(EC.presence_of_element_located((
                By.XPATH, "//div[contains(@class,'DropDown__popper__') and contains(@style,'translate3d')]"
            )))

            wait.until(lambda d: len(
                popper.find_elements(By.XPATH, ".//p[contains(@class,'pointer')]")
            ) > 0)



            # 🔥 اصلاح مهم: صبر برای لود شدن آیتم‌ها داخل popper
            wait.until(lambda d: len(
                popper.find_elements(By.XPATH, ".//p[contains(@class,'pointer')]")
            ) > 0)

            options = popper.find_elements(
                By.XPATH, ".//p[contains(@class,'pointer')]"
            )


            for opt in options:
                text = opt.text.strip()
                if text and "جست و جو" not in text:
                    result.append(text)
            time.sleep(0.5)  # صبر برای اطمینان از ثبت نتیجه
            with open(file_path_categories, "a", newline="", encoding="utf-8") as f:  # حالت append
                writer = csv.writer(f)
                writer.writerow([title, result])

            # 🔥 بستن popper بعد از استخراج
            driver.execute_script("arguments[0].click();", select_btn)

        except Exception as e:
            print(f"{title}: []  (احتمالاً وابسته به فیلد قبلی)")

df = pd.read_excel("url.xlsx", header=0)
driver = webdriver.Chrome(service=service, options=options)
# گرفتن نام‌ها از ستون اول و URL ها از ستون دوم (ردیف دوم به بعد)
data = list(zip(df.iloc[1:, 0], df.iloc[1:, 1]))  # [(name1, url1), (name2, url2), ...]

# تست: نمایش داده‌ها
for name, url in data:
    
    driver.get(url)
    time.sleep(1)  # صبر برای لود شدن صفحه
    with open(file_path_first_step, "a", newline="", encoding="utf-8") as f:  # حالت append
        writer = csv.writer(f)
        writer.writerow([name])
    first_step_field()
    time.sleep(0.5)
    complet_first_step_field()
    time.sleep(0.5)
    with open(file_path_categories, "a", newline="", encoding="utf-8") as f:  # حالت append
        writer = csv.writer(f)
        writer.writerow([name])
    Category_Attributes()