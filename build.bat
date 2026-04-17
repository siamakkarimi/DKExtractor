@echo off
setlocal

if not exist venv (
  python -m venv venv
)

call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller app\main.py ^
  --name DKExtractor ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --noconsole ^
  --hidden-import "selenium.webdriver.chromium.webdriver" ^
  --hidden-import "selenium.webdriver.chrome.webdriver" ^
  --add-data "runtime\chrome;runtime\chrome" ^
  --add-data "runtime\chromedriver\chromedriver.exe;runtime\chromedriver" ^
  --add-data "data\input.xlsx;data"

echo Build completed. Output: dist\DKExtractor
endlocal
