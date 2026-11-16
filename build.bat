@echo off
rem Compile AssistantPC.exe (un seul fichier) dans le dossier dist\.
rem Prérequis : Python 3.12 64 bits installé (case « Add python.exe to PATH » cochée).
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -3.12 -m venv .venv || python -m venv .venv || goto :erreur
)
call .venv\Scripts\activate.bat || goto :erreur
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-build.txt || goto :erreur

python outils\fabrique_icone.py build\icone.ico || goto :erreur

pyinstaller --noconfirm --clean --onefile --windowed ^
    --name AssistantPC ^
    --icon build\icone.ico ^
    --version-file outils\version.txt ^
    --exclude-module tkinter ^
    run.py || goto :erreur

echo.
echo Termine : dist\AssistantPC.exe
exit /b 0

:erreur
echo.
echo ECHEC de la compilation.
exit /b 1
