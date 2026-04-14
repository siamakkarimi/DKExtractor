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
  --add-data "runtime;runtime" ^
  --add-data "data;data"

echo Build completed. Output: dist\DKExtractor
endlocal
