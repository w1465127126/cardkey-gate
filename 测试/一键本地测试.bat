@echo off
chcp 936 >nul
cd /d "%~dp0"
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost

echo ============================================
echo   本地全流程测试（不需要 GitHub）
echo ============================================
echo.

set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo [!] 没装 Python，跳过自测，只测 exe
  goto EXTEST
)

echo [1/3] 卡密库核心逻辑自测 ...
%PY% test_store.py
echo.
echo [2/3] 端到端 HTTP 自测 ...
%PY% test_e2e_http.py
echo.

:EXTEST
echo [3/3] 起本地卡密库 + 用 ② 卡密校验器.exe 真跑
start "本地卡密库" /min %PY% local_keys_server.py
ping -n 4 127.0.0.1 >nul

echo.
echo 上面那个小黑窗会打印三张卡密（GOOD / EXPIRED / REVOKED）。
echo 复制 GOOD= 后面那串，粘到下面回车：
set /p KEY=卡密：
echo.
if not "%KEY%"=="" (
  "..\② 卡密校验器.exe" --check %KEY% --app-id MY_APP --raw-url http://127.0.0.1:8899/keys.json
  echo exit=%errorlevel%   ^(0=通过  1=拒绝^)
)
echo.
echo 测完直接关掉那个本地卡密库小黑窗即可。
pause
