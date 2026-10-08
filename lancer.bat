@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Premier lancement : preparation de l'environnement, patientez...
    where py >nul 2>&1 && (py -3 -m venv .venv) || (python -m venv .venv)
    if errorlevel 1 (
        echo.
        echo Python 3.11 ou plus recent est introuvable. Installez-le depuis python.org, puis relancez.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo L'installation a echoue. Verifiez votre connexion Internet, puis relancez.
    pause
    exit /b 1
)

REM Ouvre le navigateur apres quelques secondes (le serveur demarre en arriere-plan)
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8501"

echo Contratheque demarre. Fermez cette fenetre pour l'arreter.
python -m streamlit run app.py
if errorlevel 1 pause
