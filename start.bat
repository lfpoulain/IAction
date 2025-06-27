@echo off
echo ========================================
echo    IAction - Analyse Video IA
echo ========================================
echo.

REM Vérifier si Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python n'est pas installé ou pas dans le PATH
    echo Veuillez installer Python 3.8+ depuis https://python.org
    pause
    exit /b 1
)

REM Vérifier si les dépendances sont installées
echo Vérification des dépendances...
python -c "import flask, cv2, requests, paho.mqtt.client, dotenv" >nul 2>&1
if errorlevel 1 (
    echo Installation des dépendances...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERREUR: Impossible d'installer les dépendances
        pause
        exit /b 1
    )
)

REM Vérifier si le fichier .env existe
if not exist .env (
    echo Création du fichier de configuration...
    copy .env.example .env
    echo.
    echo IMPORTANT: Veuillez configurer le fichier .env avec vos paramètres
    echo - URL Ollama
    echo - Paramètres MQTT
    echo.
)

echo Démarrage de l'application...
echo.
echo L'application sera accessible sur:
echo http://localhost:5000
echo.
echo Appuyez sur Ctrl+C pour arrêter l'application
echo.

python app.py
