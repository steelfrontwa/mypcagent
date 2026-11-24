@echo off
chcp 65001 >nul
title PC Agent (не закрывай это окно)
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установи его с python.org ^(галочка "Add to PATH"^) и запусти снова.
  pause
  exit /b
)
python "%~dp0agent_chat.py" %*
pause
