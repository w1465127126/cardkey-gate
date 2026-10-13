@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   卡密系统打包 (需要先装 Python 3.10+)
echo ============================================
echo.

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" (
  where python >nul 2>nul && set PY=python
)
if "%PY%"=="" (
  echo [X] 找不到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH
  pause & exit /b 1
)

echo [1/4] 安装打包工具 PyInstaller ...
%PY% -m pip install -q --disable-pip-version-check pyinstaller
if errorlevel 1 ( echo [X] PyInstaller 安装失败 & pause & exit /b 1 )

echo.
echo [2/4] 打包 卡密管理端 -^> CardKeyManager.exe
%PY% -m PyInstaller --noconfirm --onefile --windowed ^
  --name CardKeyManager --distpath dist --workpath build --specpath build ^
  keygen_gui.py
if errorlevel 1 ( echo [X] 管理端打包失败 & pause & exit /b 1 )

echo.
echo [3/4] 打包 示例受保护程序 -^> DemoApp.exe
%PY% -m PyInstaller --noconfirm --onefile --windowed ^
  --name DemoApp --distpath dist --workpath build --specpath build ^
  --hidden-import cardkey_store --hidden-import cardkey_sdk ^
  demo_protected_app.py
if errorlevel 1 ( echo [!] 示例程序打包失败（不影响管理端）

echo.
echo [4/4] 打包 控制台校验器 -^> KeyCheck.exe
%PY% -m PyInstaller --noconfirm --onefile --console ^
  --name KeyCheck --distpath dist --workpath build --specpath build ^
  keycheck_cli.py
if errorlevel 1 ( echo [!] 校验器打包失败（不影响管理端）

echo.
echo ============================================
echo   完成！产物在 dist\ 目录：
dir /b dist
echo ============================================
pause
