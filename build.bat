@echo off
setlocal

cd /d "%~dp0"

set "APP_VERSION=1.0.0"
set "RELEASE_BUILD_DIR=release_build"
set "RELEASE_DIST_DIR=release_dist"
set "RELEASE_ARTIFACTS_DIR=release_artifacts"
set "INSTALLER_BASENAME=DKExtractor_Setup_%APP_VERSION%"
set "INSTALLER_PATH=%RELEASE_ARTIFACTS_DIR%\%INSTALLER_BASENAME%.exe"
set "CHECKSUM_PATH=%INSTALLER_PATH%.sha256.txt"
set "ZIP_PATH=%RELEASE_ARTIFACTS_DIR%\%INSTALLER_BASENAME%.zip"

if not exist venv (
  python -m venv venv
)

call venv\Scripts\activate
if errorlevel 1 exit /b 1

python -m pip install --upgrade pip
if errorlevel 1 exit /b 1

pip install -r requirements.txt
if errorlevel 1 exit /b 1

pip install pyinstaller
if errorlevel 1 exit /b 1

if exist "%RELEASE_BUILD_DIR%" rmdir /s /q "%RELEASE_BUILD_DIR%"
if exist "%RELEASE_DIST_DIR%" rmdir /s /q "%RELEASE_DIST_DIR%"
if exist "%RELEASE_ARTIFACTS_DIR%" rmdir /s /q "%RELEASE_ARTIFACTS_DIR%"

python -m PyInstaller DKExtractor.spec --noconfirm --clean --distpath "%RELEASE_DIST_DIR%" --workpath "%RELEASE_BUILD_DIR%"
if errorlevel 1 exit /b 1

set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_PATH%" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_PATH%" (
  echo Inno Setup compiler not found. Expected ISCC.exe in a standard Inno Setup 6 install path.
  exit /b 1
)

"%ISCC_PATH%" installer.iss
if errorlevel 1 exit /b 1

certutil -hashfile "%INSTALLER_PATH%" SHA256 > "%CHECKSUM_PATH%"
if errorlevel 1 exit /b 1

powershell -NoProfile -Command "Compress-Archive -LiteralPath '%INSTALLER_PATH%' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 exit /b 1

echo Release build completed.
echo Installer: %INSTALLER_PATH%
echo Checksum: %CHECKSUM_PATH%
echo Zip: %ZIP_PATH%

endlocal
