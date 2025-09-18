# IAction — Analyse Vidéo IA pour Home Assistant (RTSP ou HA Polling)

IAction est un service web qui analyse des images/flux vidéo avec l’IA et publie des capteurs dans Home Assistant via MQTT.

Principales capacités:
- Détection IA sur images en continu (RTSP) ou images fournies par Home Assistant (HA Polling)
- Détections personnalisées (prompt) avec webhook optionnel par détection
- MQTT Auto-Discovery (capteurs de performance, binaire « capture en cours », capteurs par détection)
- Interface web pour démarrer/arrêter, gérer les détections et afficher le flux live
- Page d’administration pour configurer le `.env` (IA, MQTT, RTSP/HA)


## Aperçu rapide
- UI: `templates/index.html` + `static/app.js`
- Admin: `templates/admin.html` + `static/admin.js`
- Backend Flask: `app.py`
- Services: `services/` (caméra RTSP, HA Polling, IA, MQTT, détections)


## Prérequis
- Python 3.10+
- Home Assistant (facultatif mais recommandé, pour MQTT/HA Polling)
- Broker MQTT accessible (ex: Mosquitto)
- OpenCV, Flask, Paho MQTT, Requests, OpenAI SDK (via `requirements.txt`)

Installation des dépendances:
```bash
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```


## Configuration (.env)
Copiez `.env.example` vers `.env` puis renseignez selon votre usage.

- IA générale
  - `AI_API_MODE` = `openai` | `lmstudio` | `ollama`
  - `AI_TIMEOUT` (s), `AI_STRICT_OUTPUT` (true/false)
  - OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL` (ex: gpt-4o)
  - LM Studio: `LMSTUDIO_URL`, `LMSTUDIO_MODEL`
  - Ollama: `OLLAMA_URL`, `OLLAMA_MODEL`
- MQTT / Home Assistant
  - `MQTT_BROKER`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
  - `HA_DEVICE_NAME`, `HA_DEVICE_ID`
- Mode de capture
  - `CAPTURE_MODE` = `rtsp` | `ha_polling`
  - RTSP: `DEFAULT_RTSP_URL`, `RTSP_USERNAME`, `RTSP_PASSWORD`
  - HA Polling: `HA_BASE_URL`, `HA_TOKEN`, `HA_ENTITY_ID`, `HA_IMAGE_ATTR`, `HA_POLL_INTERVAL`
- Analyse
  - `MIN_ANALYSIS_INTERVAL` (s)

Vous pouvez configurer ces paramètres depuis l’interface `/admin` (écrit le fichier `.env`).


## Lancer l’application
```bash
python app.py --debug   # ou simplement: python app.py
```
Par défaut: http://localhost:5002


## Utilisation
1. Configurez votre IA + MQTT + mode de capture dans `/admin`.
2. Sur la page d’accueil, démarrez la capture.
3. Ajoutez des détections (nom + phrase) et, si besoin, un webhook.
4. Affichez/masquez le flux live sans interrompre la capture.


## Modes de capture
- RTSP (recommandé)
  - Implémentation: `services/camera_service.py`
  - Flux MJPEG en direct via `/video_feed`
  - Reconnexion auto, latence réduite (BUFFERSIZE=1, MJPEG)

- HA Polling (images via API Home Assistant)
  - Implémentation: `services/ha_service.py`
  - Récupère l’URL d’image de l’entité (ex: `camera.xxx`), anti-cache, déduplication


## Capteurs Home Assistant (MQTT Auto-Discovery)
Créés par `services/mqtt_service.py`:
- Sensors:
  - `analysis_fps` (FPS d’analyse)
  - `analysis_duration` (s)
  - `analysis_total_interval` (s)
  - `analysis_total_fps` (FPS)
  - `people_count` (nombre de personnes)
- Binary sensors:
  - `capture_active` (ON/OFF)
  - Un binary sensor par détection personnalisée


## Endpoints principaux (REST)
- Config & statut
  - `GET /api/config`
  - `GET /api/status` (global), `GET /api/metrics` (léger)
  - `GET /api/capture_status`
- Caméras & capture
  - `GET /api/cameras`, `POST /api/cameras/refresh`, `GET /api/cameras/<id>`
  - `POST /api/start_capture` (type: `rtsp` ou `ha_polling`)
  - `POST /api/stop_capture`
  - `GET /video_feed`
- Détections
  - `GET /api/detections`, `POST /api/detections`
  - `PUT|PATCH /api/detections/<id>`, `DELETE /api/detections/<id>`
- Administration
  - `GET /api/admin/config`, `POST /api/admin/config`
  - `GET /api/admin/ai_test`, `GET /api/admin/mqtt_test`, `POST /api/admin/rtsp_test`
  - `POST /api/admin/restart`


## Conseils & dépannage
- Vérifiez la connexion MQTT (badge dans `/admin` ou logs CLI). Variables: `MQTT_BROKER`, `MQTT_PORT`.
- Si l’IA timeoute, augmentez `AI_TIMEOUT`. Testez depuis `/admin` → « Tester IA ».
- RTSP: vérifiez l’URL, les identifiants et que la caméra est joignable. Test rapide via `/admin` → « Tester RTSP ».
- Logs CLI configurables via `LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR).


## Développement
- Dépendances: voir `requirements.txt`
- Code principal: `app.py` et `services/`
- UI: `templates/` et `static/`

Contributions bienvenues via issues/PR.
