@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -OpenBrowser -NoWaitTts
if errorlevel 1 (
  echo 启动失败，请查看 startup-runtime.log 和各服务 runtime 日志。
  pause
)
endlocal
