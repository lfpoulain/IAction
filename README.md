# IAction - Analyse Vidéo IA avec Home Assistant

Application web pour l'analyse vidéo en temps réel avec intelligence artificielle et intégration Home Assistant via MQTT.

## Fonctionnalités

### Sources Vidéo
- **Caméras USB** : Support des caméras connectées localement
- **Flux RTSP** : Support des caméras IP avec protocole RTSP
- **Capture automatique** : Une image par seconde pour l'analyse IA

### Analyse IA
- **API Vision flexible** : Supporte OpenAI API et LM Studio
- **Modèles supportés** : 
  - OpenAI : gpt-4-vision-preview
  - LM Studio/Ollama : qwen2.5vl:7b
- **Analyse personnalisable** : Système de détection configurable par l'utilisateur

### Capteurs Fixes
- **Compteur de personnes** : Détection automatique du nombre de personnes

### Détections Personnalisées
- **Phrases de correspondance** : L'utilisateur définit des phrases de détection
- **Réponse OUI/NON** : L'IA analyse et répond par oui ou non
- **Binary Sensors MQTT** : Déclenchement automatique des capteurs

### Intégration Home Assistant
- **MQTT Autodiscovery** : Configuration automatique des capteurs
- **Binary Sensors** : Pour les détections personnalisées
- **Sensors** : Pour les valeurs numériques et textuelles

## Installation

### Prérequis
1. **Python 3.8+**
2. **Au choix** :
   - **OpenAI API** : Clé API valide
   - **LM Studio** : Installé avec un modèle vision compatible
   - **Ollama** : Installé avec un modèle vision (utilisé via LM Studio)
3. **Broker MQTT** (ex: Mosquitto)
4. **Home Assistant** (optionnel)

### Installation des dépendances
```bash
pip install -r requirements.txt
```

### Configuration
1. Copiez `.env.example` vers `.env`
2. Modifiez les paramètres selon votre configuration :

```env
# Configuration AI (OpenAI ou LM Studio)
AI_API_MODE=lmstudio  # Options: 'openai' ou 'lmstudio'
AI_TIMEOUT=60

# Configuration OpenAI
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4-vision-preview

# Configuration LM Studio (compatible avec l'API d'Ollama)
LMSTUDIO_URL=http://127.0.0.1:11434/v1
LMSTUDIO_MODEL=qwen/qwen2.5-vl-7b

# Configuration MQTT
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TOPIC_PREFIX=iaction

# Configuration Home Assistant
HA_DEVICE_NAME=IAction Camera AI
HA_DEVICE_ID=iaction_camera_ai
```

## Utilisation

### Configuration de l'API Vision

#### Option 1: LM Studio avec Ollama (Configuration actuelle)

La configuration actuelle utilise LM Studio pour accéder aux modèles d'Ollama via l'API compatible OpenAI :

1. **Installation d'Ollama** :
   ```bash
   # Téléchargez depuis https://ollama.ai
   # Puis installez le modèle vision Qwen
   ollama pull qwen2.5vl:7b
   ```

2. **Démarrage d'Ollama** :
   ```bash
   # Assurez-vous qu'Ollama est en cours d'exécution
   # Il expose une API sur le port 11434
   ```

3. **Configuration dans .env** :
   ```env
   AI_API_MODE=lmstudio
   LMSTUDIO_URL=http://127.0.0.1:11434/v1
   LMSTUDIO_MODEL=qwen/qwen2.5-vl-7b
   ```

#### Option 2: API OpenAI

Pour utiliser l'API OpenAI officielle :

1. **Obtenir une clé API** sur https://platform.openai.com

2. **Modifier le fichier .env** :
   ```env
   AI_API_MODE=openai
   OPENAI_API_KEY=sk-votre-clé-api-ici
   OPENAI_MODEL=gpt-4-vision-preview
   ```

### Démarrage de l'application
```bash
python app.py
```

L'application sera accessible sur `http://localhost:5000`

### Configuration d'une source vidéo

#### Caméra USB
1. Sélectionnez "Caméra USB X" dans la liste
2. Cliquez sur "Démarrer la capture"

#### Caméra RTSP
1. Sélectionnez "Caméra RTSP (URL personnalisée)"
2. Saisissez l'URL RTSP : `rtsp://username:password@ip:port/stream`
3. Cliquez sur "Démarrer la capture"

### Ajout de détections personnalisées
1. Cliquez sur "Ajouter" dans la section "Détections Personnalisées"
2. Saisissez un nom pour la détection
3. Décrivez précisément ce que l'IA doit détecter
4. Sauvegardez

Exemple :
- **Nom** : Personne avec rouleau de scotch
- **Phrase** : un homme qui tient un rouleau de scotch

### Intégration Home Assistant

Les capteurs apparaîtront automatiquement dans Home Assistant via MQTT autodiscovery :

#### Capteurs fixes
- `sensor.iaction_camera_ai_people_count` : Nombre de personnes
- `sensor.iaction_camera_ai_scene_description` : Description de la scène

#### Binary sensors personnalisés
- `binary_sensor.iaction_camera_ai_detection_[ID]` : État de chaque détection

## Architecture

```
app.py                 # Application Flask principale
├── services/
│   ├── camera_service.py      # Gestion des caméras
│   ├── ai_service.py          # Interface avec Ollama
│   ├── mqtt_service.py        # Communication MQTT
│   └── detection_service.py   # Logique de détection
├── templates/
│   └── index.html            # Interface web
├── static/
│   ├── style.css            # Styles CSS
│   └── app.js               # JavaScript frontend
└── requirements.txt         # Dépendances Python
```

## Configuration Ollama

### Installation d'Ollama
```bash
# Téléchargez depuis https://ollama.ai
# Puis installez un modèle vision :
ollama pull qwen2.5vl:7b
```

### Test de la connexion
```bash
curl http://localhost:11434/api/tags
```

## Configuration MQTT

### Mosquitto (exemple)
```bash
# Installation
sudo apt install mosquitto mosquitto-clients

# Démarrage
sudo systemctl start mosquitto
sudo systemctl enable mosquitto
```

### Test MQTT
```bash
# Écouter les messages
mosquitto_sub -h localhost -t "iaction/#"

# Publier un test
mosquitto_pub -h localhost -t "test" -m "hello"
```

## Dépannage

### Problèmes courants

#### Caméra non détectée
- Vérifiez que la caméra est connectée et fonctionnelle
- Testez avec d'autres applications (ex: VLC)
- Vérifiez les permissions d'accès

#### Erreur Ollama
- Vérifiez qu'Ollama est démarré : `ollama serve`
- Vérifiez que le modèle est installé : `ollama list`
- Testez la connexion : `curl http://localhost:11434/api/tags`

#### Problème MQTT
- Vérifiez que le broker MQTT est démarré
- Testez la connexion avec `mosquitto_pub/sub`
- Vérifiez les paramètres de connexion dans `.env`

#### Home Assistant
- Vérifiez que MQTT autodiscovery est activé
- Consultez les logs Home Assistant
- Redémarrez Home Assistant si nécessaire

## Développement

### Structure du code
- **Services** : Logique métier séparée en services
- **API REST** : Endpoints pour l'interface web
- **WebSocket** : Flux vidéo en temps réel
- **Threading** : Analyse IA en arrière-plan

### Ajout de nouvelles fonctionnalités
1. Modifiez les services appropriés
2. Ajoutez les endpoints API nécessaires
3. Mettez à jour l'interface web

## Licence

Ce projet est sous licence MIT.
