@echo off
chcp 65001 >nul
rem Открывает окно, где работает команда ege.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo Программа ещё не установлена: сначала запусти install.bat
    pause
    exit /b 1
)
start "EGE-TUTOR-2027" cmd /k "call .venv\Scripts\activate.bat && ege info && echo. && echo Команды: ege --help"
