@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\switch_xiandie_trial.ps1" -Mode rollback
pause
