@echo off
chcp 65001 >nul
title Сборка PC-Agent.exe
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установи его с python.org ^(галочка "Add to PATH"^) и запусти снова.
  pause
  exit /b
)
echo [1/3] Устанавливаю PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail
echo [2/3] Собираю PC-Agent.exe ^(1-3 минуты^)...
python -m PyInstaller --onefile --name PC-Agent --noconfirm --clean --collect-submodules pcagent --add-data "pcagent\web;pcagent\web" agent_chat.py
if errorlevel 1 goto fail
copy /y "dist\PC-Agent.exe" "%~dp0PC-Agent.exe" >nul
echo [3/3] Создаю ярлык на рабочем столе...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\PC-Agent.lnk'); $s.TargetPath='%~dp0PC-Agent.exe'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo.
echo Готово! Запускай ярлык PC-Agent на рабочем столе.
echo Для доступа с телефона запускай: PC-Agent.exe --lan
echo Python теперь не нужен: файл PC-Agent.exe можно копировать на другие компьютеры.
pause
exit /b
:fail
echo.
echo Сборка не удалась. Пришли текст ошибки выше, я помогу.
pause
