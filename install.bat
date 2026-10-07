@echo off
chcp 65001 >nul
setlocal
rem Установка EGE-TUTOR-2027 на Windows.
rem Можно запустить из папки проекта или отдельно: тогда проект скачается в %USERPROFILE%\EGE-TUTOR-2027.
rem EGE_NONINTERACTIVE=1 — не ждать нажатия клавиши и не создавать ярлык (для CI).

set "REPO_URL=https://github.com/rostislavkarasev5-a11y/EGE-TUTOR-2027.git"
set "TARGET=%USERPROFILE%\EGE-TUTOR-2027"

echo === Установка EGE-TUTOR-2027 ===
echo.

where uv >nul 2>nul
if errorlevel 1 goto :no_uv

if exist "%~dp0pyproject.toml" (
    set "PROJECT=%~dp0"
    goto :have_project
)

where git >nul 2>nul
if errorlevel 1 goto :no_git
if exist "%TARGET%\pyproject.toml" (
    echo Проект уже скачан: %TARGET%
) else (
    echo Скачиваю проект в %TARGET% ...
    git clone "%REPO_URL%" "%TARGET%"
    if errorlevel 1 goto :fail
)
set "PROJECT=%TARGET%"

:have_project
cd /d "%PROJECT%"
if errorlevel 1 goto :fail
echo Папка проекта: %CD%
echo.

echo [1/3] Устанавливаю Python и библиотеки, это может занять пару минут...
uv sync --locked
if errorlevel 1 goto :fail

echo.
echo [2/3] Создаю локальную базу данных...
uv run ege init
if errorlevel 1 goto :fail

echo.
echo [3/3] Проверяю, что всё работает...
uv run ege info
if errorlevel 1 goto :fail

if defined EGE_NONINTERACTIVE goto :done
set "DESKTOP="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
if not defined DESKTOP goto :done
> "%DESKTOP%\EGE-TUTOR.bat" (
    echo @echo off
    echo call "%CD%\ege-console.bat"
)
echo.
echo На рабочем столе появился файл EGE-TUTOR.bat — двойной щелчок открывает программу.

:done
echo.
echo === Готово! ===
echo Открой программу: двойной щелчок по ege-console.bat в папке проекта.
echo Попробуй команды: ege topics   ege exam math   ege --help
goto :end

:no_uv
echo [ОШИБКА] Не найден uv. Установи его по инструкции и запусти этот файл ещё раз.
goto :fail

:no_git
echo [ОШИБКА] Не найден Git. Установи его по инструкции и запусти этот файл ещё раз.
goto :fail

:fail
echo.
echo Установка не завершена. Сделай скриншот этого окна и пришли его в чат.
if not defined EGE_NONINTERACTIVE pause
exit /b 1

:end
if not defined EGE_NONINTERACTIVE pause
exit /b 0
