@echo off
chcp 65001 >nul
setlocal
rem Обновление EGE-TUTOR-2027: свежий код, библиотеки и схема базы. Личные данные не трогаются.

cd /d "%~dp0"
echo === Обновление EGE-TUTOR-2027 ===
echo.

echo [1/3] Скачиваю обновления...
git pull --ff-only
if errorlevel 1 goto :fail

echo.
echo [2/3] Обновляю библиотеки...
uv sync --locked
if errorlevel 1 goto :fail

echo.
echo [3/3] Обновляю базу данных...
uv run ege init
if errorlevel 1 goto :fail

echo.
echo === Готово! ===
goto :end

:fail
echo.
echo Обновление не завершено. Сделай скриншот этого окна и пришли его в чат.
if not defined EGE_NONINTERACTIVE pause
exit /b 1

:end
if not defined EGE_NONINTERACTIVE pause
exit /b 0
