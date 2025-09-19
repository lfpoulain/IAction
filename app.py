from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import cv2
import threading
import time
import base64
import json
import os
import logging
import sys
import re
import socket
import errno
import numpy as np
from dotenv import load_dotenv
from services.camera_service import CameraService
from services.ai_service import AIService
from services.mqtt_service import get_mqtt_instance, MQTTService
from services.detection_service import DetectionService
from services.ha_service import HAService

# Charger les variables d'environnement
load_dotenv(override=True)  # Forcer le remplacement des variables d'environnement existantes
# Format de logs unifié pour le CLI + niveau via env LOG_LEVEL
log_level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_name, logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def _sanitize_env_value(value, key: str) -> str:
    """Normalize values written to .env to avoid spaces breaking Docker env parsing.
    - Trim whitespace
    - Remove surrounding single/double quotes
    - Replace internal whitespace with underscores for most keys
    Some keys are exempt (URLs, tokens, passwords) where spaces are either invalid
    or should not be altered semantically.
    """
    try:
        if value is None:
            return ''
        v = str(value).strip()
        # Remove surrounding quotes if present
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]

        # Keys that should not have their spaces converted
        exempt_keys = {
            'DEFAULT_RTSP_URL', 'LMSTUDIO_URL', 'OLLAMA_URL', 'OPENAI_API_KEY',
            'MQTT_PASSWORD', 'RTSP_PASSWORD', 'HA_TOKEN', 'HA_BASE_URL'
        }

        if key not in exempt_keys:
            # Collapse any whitespace (spaces, tabs) into single underscores
            v = re.sub(r"\s+", "_", v)

        return v
    except Exception:
        return '' if value is None else str(value)

def is_running_in_docker() -> bool:
    """Detect if we're running inside a Docker container.
    Checks /.dockerenv presence or IN_DOCKER env var.
    """
    try:
        if os.path.exists('/.dockerenv'):
            return True
        return str(os.environ.get('IN_DOCKER', '')).lower() in ('1', 'true', 'yes')
    except Exception:
        return False

def _wait_until_bind_possible(host: str, port: int, timeout: float = 10.0) -> bool:
    """Attend jusqu'à ce qu'un bind(host, port) soit possible (port vraiment libéré)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.close()
            return True
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            time.sleep(0.2)
    return False

def _run_web_server_with_retry(host: str = '0.0.0.0', port: int = 5002, debug: bool = False, max_attempts: int = 8):
    """Lance Flask avec une stratégie de retry robuste si le port est encore occupé.
    - Pré-vérifie la disponibilité du port par un bind test.
    - Retrie en cas d'OSError (EADDRINUSE) et de SystemExit issus de werkzeug.
    """
    delay = 0.4
    attempt = 1
    while attempt <= max_attempts:
        mode = 'DEBUG' if debug else 'PRODUCTION'
        if attempt > 1:
            logger.info(f"Nouvelle tentative de démarrage du serveur (essai {attempt}/{max_attempts}) en mode {mode}...")

        # Pré-bind: vérifier que le port est libre
        prebind_ok = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.close()
            prebind_ok = True
        except OSError as e:
            if getattr(e, 'errno', None) in (errno.EADDRINUSE, 10048):
                if attempt < max_attempts:
                    logger.warning(f"Port {port} occupé (pré-vérification), attente {delay:.1f}s avant retry...")
                    time.sleep(delay)
                    delay = min(2.0, delay * 1.6)
                    attempt += 1
                    continue
            # Autre erreur, on tente quand même app.run pour obtenir un message clair
        except Exception:
            # On ne bloque pas sur la pré-vérif
            pass

        try:
            app.run(debug=debug, host=host, port=port, threaded=True, use_reloader=False)
            return
        except OSError as e:
            msg = str(e).lower()
            addr_in_use = (getattr(e, 'errno', None) in (errno.EADDRINUSE, 10048)) or ('address already in use' in msg or ('port' in msg and 'in use' in msg))
            if addr_in_use and attempt < max_attempts:
                logger.warning(f"Port {port} occupé, attente {delay:.1f}s avant retry...")
                time.sleep(delay)
                delay = min(2.0, delay * 1.6)
                attempt += 1
                continue
            raise
        except SystemExit as e:
            # Certains chemins de werkzeug lèvent SystemExit quand le bind échoue
            if attempt < max_attempts:
                logger.warning(f"Échec de démarrage du serveur (SystemExit). Attente {delay:.1f}s avant retry...")
                time.sleep(delay)
                delay = min(2.0, delay * 1.6)
                attempt += 1
                continue
            raise

def _build_restart_args() -> list:
    """Build clean argv for re-exec: keep current flags but force no reloader."""
    try:
        new_args = [a for a in sys.argv[1:] if a != '--no-reloader']
        new_args.append('--no-reloader')
        return [sys.executable, sys.argv[0]] + new_args
    except Exception:
        return [sys.executable, sys.argv[0], '--no-reloader']

def _wait_for_port_to_close(host: str, port: int, timeout: float = 10.0) -> bool:
    """Return True when TCP connect fails (port closed) or timeout reached.
    Polls the given host:port until connection is refused, meaning the previous
    server has released the port.
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.3)
            s.connect((host, port))
            # Connection succeeded -> server still up
            s.close()
            time.sleep(0.2)
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            return True
    return False

def _delayed_self_restart(delay_sec: float = 0.3, shutdown_fn=None):
    """Redémarrage robuste par sous-processus (tous environnements).
    - Crée un sous-processus Python (avec IACTION_WAIT_FOR_PID)
    - Arrête proprement le serveur actuel, cleanup, puis quitte le parent
    - Le sous-processus attend que le port soit libéré avant de démarrer
    """
    try:
        time.sleep(delay_sec)
        args = _build_restart_args()
        # Créer un sous-processus, arrêter proprement, puis quitter
        try:
            env = os.environ.copy()
            env['IACTION_WAIT_FOR_PID'] = str(os.getpid())
            logger.info(f"🔁 Redémarrage via nouveau subprocess: {args}")
            import subprocess
            subprocess.Popen(args, close_fds=True, env=env)
        except Exception as e:
            logger.error(f"Échec du lancement du processus enfant: {e}")
        finally:
            if shutdown_fn:
                try:
                    logger.info("🛑 Arrêt du serveur en cours (shutdown werkzeug)...")
                    shutdown_fn()
                except Exception as e:
                    logger.debug(f"shutdown werkzeug ignoré: {e}")
            try:
                cleanup()
            except Exception:
                pass
            os._exit(0)
    except Exception as e:
        logger.error(f"Erreur inattendue pendant le redémarrage différé: {e}")
        try:
            cleanup()
        except Exception:
            pass
        os._exit(0)

def resize_frame_for_analysis(frame):
    """Redimensionne une frame en 720p pour l'analyse IA de manière centralisée"""
    try:
        if frame is None:
            return None
        # Vérifier si déjà en 720p pour éviter un redimensionnement inutile
        height, width = frame.shape[:2]
        if height == 720 and width == 1280:
            return frame
        return cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    except Exception as e:
        logger.warning(f"Erreur lors du redimensionnement: {e}")
        return frame

app = Flask(__name__)
CORS(app)

# Services globaux
camera_service = CameraService()
ai_service = AIService()
mqtt_service = get_mqtt_instance()  # Utiliser le singleton MQTT
detection_service = DetectionService(ai_service, mqtt_service)

# Variables globales
current_frame = None
is_capturing = False
capture_thread = None
analysis_in_progress = False  # Indique si une analyse est en cours
last_analysis_time = 0  # Timestamp de la dernière analyse terminée
last_analysis_duration = 0  # Durée de la dernière analyse en secondes
last_analysis_total_interval = 0  # Intervalle total entre deux réponses (fin -> fin)
shutting_down = False  # Indicateur d'arrêt global
# Compteur d'échecs IA consécutifs pour arrêt automatique
ai_consecutive_failures = 0

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config')
def get_config():
    """Expose la configuration nécessaire au frontend"""
    config = {
        'rtsp_url': os.getenv('DEFAULT_RTSP_URL', ''),
        'capture_mode': os.getenv('CAPTURE_MODE', 'rtsp'),
        'ha_base_url': os.getenv('HA_BASE_URL', ''),
        'ha_entity_id': os.getenv('HA_ENTITY_ID', ''),
        'ha_image_attr': os.getenv('HA_IMAGE_ATTR', 'entity_picture'),
        'ha_poll_interval': float(os.getenv('HA_POLL_INTERVAL', '1.0')),
    }
    return jsonify(config)

@app.route('/api/cameras')
def get_cameras():
    """Récupère la liste des caméras RTSP disponibles"""
    try:
        cameras = camera_service.get_available_cameras()
        return jsonify({
            'success': True,
            'cameras': cameras,
            'count': len(cameras),
            'rtsp_count': len(cameras)  # Toutes les caméras sont RTSP maintenant
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des caméras: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'cameras': []
        }), 500

@app.route('/api/cameras/refresh', methods=['POST'])
def refresh_cameras():
    """Force la mise à jour de la liste des caméras"""
    try:
        # Effacer le cache
        camera_service.cameras_cache = None
        camera_service.cache_time = 0
        
        # Recharger les caméras
        cameras = camera_service.get_available_cameras()
        
        return jsonify({
            'success': True,
            'message': 'Liste des caméras mise à jour',
            'cameras': cameras,
            'count': len(cameras),
            'rtsp_count': len([c for c in cameras if c['type'] == 'rtsp'])
        })
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour des caméras: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/cameras/<camera_id>')
def get_camera_info(camera_id):
    """Récupère les informations détaillées d'une caméra"""
    try:
        camera_info = camera_service.get_camera_info(camera_id)
        if camera_info:
            return jsonify({
                'success': True,
                'camera': camera_info
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Caméra non trouvée'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Variable pour suivre les requêtes /api/status
status_request_count = 0
last_status_log_time = 0
status_log_interval = 60  # Intervalle en secondes entre les logs de status

@app.route('/api/status')
def get_status():
    """Récupère les informations de statut de l'analyse"""
    global last_analysis_time, last_analysis_duration, analysis_in_progress
    global status_request_count, last_status_log_time
    
    # Incrémenter le compteur de requêtes
    status_request_count += 1
    current_time = time.time()
    
    # Ne logger que périodiquement pour éviter de surcharger les logs
    if current_time - last_status_log_time > status_log_interval:
        logger.info(f"{status_request_count} requêtes /api/status reçues dans les {status_log_interval} dernières secondes")
        status_request_count = 0
        last_status_log_time = current_time
    
    status = {
        'last_analysis_time': last_analysis_time,
        'last_analysis_duration': last_analysis_duration,
        'analysis_in_progress': analysis_in_progress
    }
    
    return jsonify(status)

@app.route('/api/metrics')
def get_metrics():
    """Endpoint léger pour les métriques de performance uniquement"""
    global last_analysis_time, last_analysis_duration, last_analysis_total_interval
    
    # Calculer FPS dérivés
    analysis_fps = (1.0 / last_analysis_duration) if last_analysis_duration and last_analysis_duration > 0 else 0
    total_fps = (1.0 / last_analysis_total_interval) if last_analysis_total_interval and last_analysis_total_interval > 0 else 0

    return jsonify({
        'last_analysis_time': last_analysis_time,
        'last_analysis_duration': last_analysis_duration,
        'analysis_fps': analysis_fps,
        'analysis_total_interval': last_analysis_total_interval,
        'analysis_total_fps': total_fps,
        'timestamp': time.time()
    })

@app.route('/api/capture_status')
def get_capture_status():
    """Retourne l'état actuel de la capture"""
    global is_capturing
    return jsonify({
        'is_capturing': is_capturing,
        'camera_active': camera_service.is_capturing if hasattr(camera_service, 'is_capturing') else False
    })

@app.route('/api/start_capture', methods=['POST'])
def start_capture():
    """Démarre la capture vidéo avec support amélioré"""
    global is_capturing, capture_thread, ai_consecutive_failures
    
    try:
        data = request.json
        source = data.get('source')
        source_type = data.get('type')  # 'rtsp' ou 'ha_polling'
        rtsp_url = data.get('rtsp_url')  # URL RTSP personnalisée (si RTSP)
        
        # Si non fourni, utiliser la config serveur
        if not source_type:
            source_type = os.getenv('CAPTURE_MODE', 'rtsp')
        
        logger.info(f"Tentative de démarrage - Type: {source_type}, Source: {source}, RTSP URL: {rtsp_url}")
        
        if is_capturing:
            return jsonify({
                'success': False,
                'error': 'Capture déjà en cours'
            }), 400
        
        if source_type == 'rtsp':
            # Valider si nécessaire
            if rtsp_url:
                is_valid, message = camera_service.validate_rtsp_url(rtsp_url)
                if not is_valid:
                    return jsonify({'success': False, 'error': f'URL RTSP invalide: {message}'}), 400
            
            # Démarrer RTSP
            # Réinitialiser le compteur d'échecs IA au démarrage d'une nouvelle session
            ai_consecutive_failures = 0
            success = camera_service.start_capture(source, 'rtsp', rtsp_url)
            if not success:
                return jsonify({'success': False, 'error': 'Impossible de démarrer la capture RTSP'}), 400
            
            is_capturing = True
            capture_thread = threading.Thread(target=capture_loop, daemon=True)
            capture_thread.start()
            # Publier l'état de capture (ON)
            try:
                mqtt_service.publish_binary_sensor_state('capture_active', True)
            except Exception:
                pass
            
            camera_info = camera_service.get_camera_info(source)
            camera_name = camera_info['name'] if camera_info else f'Source {source}'
            return jsonify({'success': True, 'message': f'Capture RTSP démarrée: {camera_name}', 'camera': camera_info})
        
        elif source_type == 'ha_polling':
            # S'assurer que la caméra RTSP est arrêtée
            camera_service.stop_capture()
            
            # Vérifier config HA minimale
            if not os.getenv('HA_BASE_URL') or not os.getenv('HA_TOKEN') or not os.getenv('HA_ENTITY_ID'):
                return jsonify({'success': False, 'error': 'Configuration HA incomplète (HA_BASE_URL, HA_TOKEN, HA_ENTITY_ID)'}), 400
            
            # Réinitialiser le compteur d'échecs IA au démarrage d'une nouvelle session
            ai_consecutive_failures = 0
            is_capturing = True
            capture_thread = threading.Thread(target=ha_polling_loop, daemon=True)
            capture_thread.start()
            # Publier l'état de capture (ON)
            try:
                mqtt_service.publish_binary_sensor_state('capture_active', True)
            except Exception:
                pass
            return jsonify({'success': True, 'message': 'Capture HA Polling démarrée', 'camera': None})
        
        else:
            return jsonify({'success': False, 'error': f"Type de capture inconnu: {source_type}"}), 400
        
    except Exception as e:
        logger.error(f"Erreur lors du démarrage de la capture: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stop_capture', methods=['POST'])
def stop_capture():
    """Arrête la capture vidéo"""
    global is_capturing
    
    is_capturing = False
    camera_service.stop_capture()
    # Publier l'état de capture (OFF)
    try:
        mqtt_service.publish_binary_sensor_state('capture_active', False)
    except Exception:
        pass
    
    return jsonify({'status': 'Capture arrêtée'})

@app.route('/api/detections')
def get_detections():
    """Récupère la liste des détections configurées"""
    return jsonify(detection_service.get_detections())

@app.route('/api/detections', methods=['POST'])
def add_detection():
    """Ajoute une nouvelle détection personnalisée avec webhook optionnel"""
    data = request.json
    name = data.get('name')
    phrase = data.get('phrase')
    webhook_url = data.get('webhook_url')  # Optionnel
    
    if not name or not phrase:
        return jsonify({'error': 'Nom et phrase requis'}), 400
    
    # Valider l'URL du webhook si fournie
    if webhook_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(webhook_url)
            if not parsed.scheme in ['http', 'https']:
                return jsonify({'error': 'URL webhook invalide (doit utiliser http:// ou https://)'}), 400
            if not parsed.netloc:
                return jsonify({'error': 'URL webhook invalide (hostname manquant)'}), 400
            # Vérifier que ce n'est pas une URL locale dangereuse
            if parsed.hostname in ['localhost', '127.0.0.1', '::1'] or (parsed.hostname and parsed.hostname.startswith('192.168.')):
                logger.warning(f"URL webhook vers réseau local détectée: {webhook_url}")
        except Exception:
            return jsonify({'error': 'URL webhook malformée'}), 400
    
    detection_id = detection_service.add_detection(name, phrase, webhook_url)
    
    response_data = {'id': detection_id, 'status': 'Détection ajoutée'}
    if webhook_url:
        response_data['webhook_configured'] = True
        response_data['webhook_url'] = webhook_url
    
    return jsonify(response_data)

@app.route('/api/detections/<detection_id>', methods=['PUT', 'PATCH'])
def update_detection(detection_id):
    """Met à jour une détection personnalisée (nom, phrase, webhook)"""
    try:
        data = request.get_json() or {}
        name = data.get('name')
        phrase = data.get('phrase')
        webhook_url = data.get('webhook_url') if 'webhook_url' in data else None

        if not any([name, phrase]) and 'webhook_url' not in data:
            return jsonify({'error': 'Aucun champ à mettre à jour'}), 400

        updated = detection_service.update_detection(detection_id, name=name, phrase=phrase, webhook_url=webhook_url)
        if not updated:
            return jsonify({'error': 'Détection non trouvée'}), 404

        return jsonify({'success': True, 'detection': updated})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/detections/<detection_id>', methods=['DELETE'])
def delete_detection(detection_id):
    """Supprime une détection"""
    success = detection_service.remove_detection(detection_id)
    if success:
        return jsonify({'status': 'Détection supprimée'})
    else:
        return jsonify({'error': 'Détection non trouvée'}), 404

@app.route('/api/current_frame')
def get_current_frame():
    """Récupère l'image actuelle"""
    global current_frame
    
    if current_frame is None:
        return jsonify({'error': 'Aucune image disponible'}), 404
    
    # Encoder l'image en base64
    _, buffer = cv2.imencode('.jpg', current_frame)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
    
    return jsonify({'image': f'data:image/jpeg;base64,{img_base64}'})

# Variable pour suivre les connexions au flux vidéo
video_feed_connections = 0

@app.route('/video_feed')
def video_feed():
    """Stream vidéo en temps réel"""
    def generate():
        global current_frame, video_feed_connections, shutting_down
        error_count = 0
        max_errors = 5
        
        # Incrémenter le compteur de connexions
        video_feed_connections += 1
        connection_id = video_feed_connections
        logger.info(f"Démarrage du flux vidéo (connexion #{connection_id})...")
        
        # Vérifier si c'est une reconnexion rapide (moins de 5 secondes depuis la dernière connexion)
        current_time = time.time()
        if hasattr(app, 'last_video_feed_connection_time') and current_time - app.last_video_feed_connection_time < 5:
            logger.info(f"Reconnexion rapide détectée (#{connection_id}) - Intervalle: {current_time - app.last_video_feed_connection_time:.2f}s")
        
        # Mettre à jour le temps de la dernière connexion
        app.last_video_feed_connection_time = current_time
        
        try:
            while True:
                # Arrêt propre si shutdown demandé
                if shutting_down:
                    logger.info(f"Arrêt du flux vidéo (connexion #{connection_id}) - arrêt application en cours")
                    break
                try:
                    if current_frame is not None:
                        # Convertir l'image en JPEG avec compression optimisée
                        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]  # Qualité optimisée
                        success, buffer = cv2.imencode('.jpg', current_frame, encode_params)
                        if success:
                            frame = buffer.tobytes()
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                            error_count = 0  # Réinitialiser le compteur d'erreurs
                        else:
                            logger.error("Erreur d'encodage de l'image")
                            error_count += 1
                    else:
                        logger.debug("Pas d'image disponible")
                        error_count += 1
                        
                    # Si trop d'erreurs consécutives, arrêter le flux
                    if error_count > max_errors:
                        logger.error(f"Trop d'erreurs dans le flux vidéo, arrêt du flux (connexion #{connection_id})")
                        break
                        
                    # Cadence du flux alignée sur la source si possible
                    try:
                        fps = camera_service.get_source_fps() if hasattr(camera_service, 'get_source_fps') else None
                        if fps and fps > 0:
                            interval = 1.0 / fps
                        else:
                            # Fallback: si mode HA polling actif, se caler sur l'intervalle de polling
                            if os.getenv('CAPTURE_MODE', 'rtsp') == 'ha_polling':
                                interval = max(float(os.getenv('HA_POLL_INTERVAL', '1.0')), 0.2)
                            else:
                                interval = 0.033
                    except Exception:
                        interval = 0.033
                    time.sleep(interval)
                except Exception as e:
                    logger.exception(f"Exception dans le flux vidéo: {e}")
                    error_count += 1
                    if error_count > max_errors:
                        logger.error(f"Trop d'exceptions dans le flux vidéo, arrêt du flux (connexion #{connection_id})")
                        break
                    time.sleep(0.5)  # Attendre un peu plus longtemps en cas d'erreur
        finally:
            # Décrémenter le compteur de connexions à la fermeture
            video_feed_connections -= 1
            logger.info(f"Flux vidéo fermé (connexion #{connection_id}) - Connexions actives: {video_feed_connections}")
    # Retourner une réponse streaming MJPEG
    logger.info("Préparation de la réponse streaming MJPEG /video_feed")
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

def ha_polling_loop():
    """Boucle de capture via Home Assistant en utilisant HAService."""
    global current_frame, is_capturing, analysis_in_progress, last_analysis_time

    base_url = os.getenv('HA_BASE_URL', '').rstrip('/')
    token = os.getenv('HA_TOKEN', '')
    entity_id = os.getenv('HA_ENTITY_ID', '')
    image_attr = os.getenv('HA_IMAGE_ATTR', 'entity_picture')
    poll_interval = float(os.getenv('HA_POLL_INTERVAL', '1.0'))
    min_analysis_interval = float(os.getenv('MIN_ANALYSIS_INTERVAL', '0.1'))

    # Aligner les timeouts HA sur le timeout IA existant par simplicité
    try:
        ai_timeout = float(os.getenv('AI_TIMEOUT', '10'))
    except Exception:
        ai_timeout = 10.0

    service = HAService(
        base_url=base_url,
        token=token,
        entity_id=entity_id,
        image_attr=image_attr,
        poll_interval=poll_interval,
        state_timeout=ai_timeout,
        image_timeout=ai_timeout,
        logger=logging.getLogger(__name__)
    )

    def on_frame(frame):
        global current_frame, analysis_in_progress, last_analysis_time
        # Publier la frame courante
        current_frame = frame
        # Déclencher analyse si intervalle OK
        current_time = time.time()
        if not analysis_in_progress and (current_time - last_analysis_time) >= min_analysis_interval:
            analysis_thread = threading.Thread(target=analyze_frame, args=(frame.copy(), current_time), daemon=True)
            analysis_thread.start()
            analysis_in_progress = True

    def is_running():
        return is_capturing

    service.run_loop(on_frame, is_running)


def capture_loop():
    """Boucle principale de capture RTSP"""
    global current_frame, is_capturing, analysis_in_progress, last_analysis_time, last_analysis_duration
    
    min_analysis_interval = float(os.getenv('MIN_ANALYSIS_INTERVAL', '0.1'))
    
    while is_capturing:
        try:
            frame = camera_service.get_frame()
            if frame is not None:
                current_frame = frame
                # Déclencher l'analyse si l'intervalle minimum est respecté
                current_time = time.time()
                if not analysis_in_progress and (current_time - last_analysis_time) >= min_analysis_interval:
                    analysis_thread = threading.Thread(target=analyze_frame, args=(frame.copy(), current_time), daemon=True)
                    analysis_thread.start()
                    analysis_in_progress = True

            # Cadence alignée sur la source si possible
            try:
                fps = camera_service.get_source_fps() if hasattr(camera_service, 'get_source_fps') else None
                interval = 1.0 / fps if fps and fps > 0 else 0.02
            except Exception:
                interval = 0.02
            time.sleep(interval)

        except Exception as e:
            logger.exception(f"Exception capture_loop: {e}")
            time.sleep(0.1)


def analyze_frame(frame, start_time):
    """Analyse une image avec l'IA"""
    global analysis_in_progress, last_analysis_time, last_analysis_duration, last_analysis_total_interval, is_capturing, ai_consecutive_failures
    
    try:
        # Redimensionner l'image en 720p (1280x720) pour l'analyse
        resized_frame = resize_frame_for_analysis(frame)

        # Encoder l'image redimensionnée en base64
        _, buffer = cv2.imencode('.jpg', resized_frame)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Analyser avec les détections configurées
        result = detection_service.analyze_frame(img_base64)

        # Détecter erreurs IA (timeouts et erreurs de connexion) et arrêter si nécessaire
        try:
            if isinstance(result, dict):
                err_text = (str(result.get('error', '')) + ' ' + str(result.get('details', ''))).lower()
                success_flag = bool(result.get('success', True))

                # Détection de timeout
                is_timeout = (not success_flag) and any(
                    kw in err_text for kw in ['timeout', 'timed out', 'read timed out', 'deadline exceeded']
                )
                # Détection d'erreurs de connexion/réseau
                is_connection_error = (not success_flag) and any(
                    kw in err_text for kw in [
                        'connection error', 'connection refused', 'failed to establish a new connection',
                        'connection reset', 'bad gateway', 'service unavailable', 'host unreachable',
                        'network is unreachable', 'cannot connect', 'name or service not known', 'dns']
                )

                if success_flag:
                    # Reset sur succès
                    if ai_consecutive_failures:
                        logger.debug(f"Réinitialisation du compteur d'échecs IA ({ai_consecutive_failures} → 0)")
                    ai_consecutive_failures = 0
                else:
                    ai_consecutive_failures += 1
                    logger.warning(f"Échec IA #{ai_consecutive_failures}: {err_text[:200]}")

                # Arrêt immédiat sur timeout ou erreur de connexion
                should_stop_now = is_timeout or is_connection_error
                # Arrêt après N échecs consécutifs (N=3)
                failure_threshold_reached = ai_consecutive_failures >= 3

                if is_capturing and (should_stop_now or failure_threshold_reached):
                    reason = 'timeout IA' if is_timeout else ('erreur de connexion IA' if is_connection_error else 'échecs IA répétés')
                    logger.error(f"🛑 {reason} - arrêt de la capture")
                    is_capturing = False
                    try:
                        camera_service.stop_capture()
                    except Exception as e_stop:
                        logger.warning(f"Erreur lors de l'arrêt de la capture après erreur IA: {e_stop}")
                    try:
                        mqtt_service.publish_binary_sensor_state('capture_active', False)
                    except Exception:
                        pass
        except Exception:
            # Ne pas bloquer l'analyse si la détection d'erreur échoue
            pass
        
        # Calculer la durée de l'analyse
        end_time = time.time()
        duration = end_time - start_time
        # Calculer l'intervalle total (fin -> fin) par rapport à l'analyse précédente
        prev_end_time = last_analysis_time
        total_interval = (end_time - prev_end_time) if prev_end_time and prev_end_time > 0 else 0
        
        # Mettre à jour les variables globales
        last_analysis_time = end_time
        last_analysis_duration = duration
        last_analysis_total_interval = total_interval
        
        if total_interval and total_interval > 0:
            logger.info(f"Analyse terminée en {duration:.2f}s | Intervalle total: {total_interval:.2f}s | FPS total: {1.0/total_interval:.2f}")
        else:
            logger.info(f"Analyse terminée en {duration:.2f}s")
        
        # Publier les informations d'analyse via MQTT
        mqtt_service.publish_status({
            'last_analysis_time': last_analysis_time,
            'last_analysis_duration': last_analysis_duration,
            'analysis_total_interval': last_analysis_total_interval,
            'analysis_result': result
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse: {e}")
        # Publier l'erreur via MQTT
        mqtt_service.publish_status({
            'last_analysis_time': time.time(),
            'last_analysis_duration': time.time() - start_time,
            'analysis_error': str(e),
            'analysis_result': None
        })
    finally:
        # Marquer l'analyse comme terminée, qu'elle ait réussi ou échoué
        analysis_in_progress = False

@app.route('/admin')
def admin():
    """Page d'administration"""
    return render_template('admin.html')

@app.route('/api/admin/config', methods=['GET'])
def get_admin_config():
    """Récupère la configuration actuelle"""
    try:
        config = {}
        
        # Lire le fichier .env
        env_path = '.env'
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key] = value
        
        # Ajouter les paramètres par défaut s'ils n'existent pas
        defaults = {
            'AI_API_MODE': 'lmstudio',
            'AI_TIMEOUT': '10',
            'LOG_LEVEL': 'INFO',
            'OPENAI_MODEL': 'gpt-4-vision-preview',
            'LMSTUDIO_URL': 'http://127.0.0.1:11434/v1',
            'LMSTUDIO_MODEL': '',
            'OLLAMA_URL': 'http://127.0.0.1:11434/v1',
            'OLLAMA_MODEL': '',
            'MQTT_BROKER': '127.0.0.1',
            'MQTT_PORT': '1883',
            'MQTT_USERNAME': '',
            'MQTT_PASSWORD': '',
            'HA_DEVICE_NAME': 'IAction',
            'HA_DEVICE_ID': 'iaction_camera',
            'DEFAULT_RTSP_URL': 'rtsp://localhost:554/live',
            'RTSP_USERNAME': '',
            'RTSP_PASSWORD': '',
            'MIN_ANALYSIS_INTERVAL': '0.1',
            # Nouveau: capture mode & HA Polling
            'CAPTURE_MODE': 'rtsp',
            'HA_BASE_URL': '',
            'HA_TOKEN': '',
            'HA_ENTITY_ID': '',
            'HA_IMAGE_ATTR': 'entity_picture',
            'HA_POLL_INTERVAL': '1.0'
        }
        
        for key, default_value in defaults.items():
            if key not in config:
                config[key] = default_value
        
        return jsonify(config)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur lors de la lecture de la configuration: {str(e)}'
        }), 500

@app.route('/api/admin/ai_test', methods=['GET'])
def admin_ai_test():
    """Teste la connexion au backend IA avec le modèle courant.
    Ne bloque pas le démarrage et retourne un JSON simple.
    """
    try:
        result = ai_service.test_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur lors du test de connexion IA: {str(e)}'
        }), 200

@app.route('/api/admin/mqtt_test', methods=['GET'])
def admin_mqtt_test():
    """Retourne l'état de la connexion MQTT et tente une connexion rapide si déconnecté."""
    try:
        status = mqtt_service.get_connection_status() if hasattr(mqtt_service, 'get_connection_status') else {
            'connected': getattr(mqtt_service, 'is_connected', False),
            'broker': getattr(mqtt_service, 'broker', ''),
            'port': getattr(mqtt_service, 'port', 1883)
        }
        if not status.get('connected'):
            # Tentative de connexion rapide (non bloquante)
            try:
                mqtt_service.connect()
                t0 = time.time()
                while time.time() - t0 < 3:
                    if getattr(mqtt_service, 'is_connected', False):
                        break
                    time.sleep(0.2)
                status = mqtt_service.get_connection_status()
            except Exception:
                pass
        return jsonify({ 'success': True, 'status': status })
    except Exception as e:
        return jsonify({ 'success': False, 'error': str(e) }), 200

@app.route('/api/admin/rtsp_test', methods=['POST'])
def admin_rtsp_test():
    """Teste une URL RTSP (dans le body JSON: { url }) ou la valeur DEFAULT_RTSP_URL si absente."""
    try:
        test_url = None
        try:
            data = request.get_json(silent=True) or {}
            test_url = data.get('url')
        except Exception:
            test_url = None
        if not test_url:
            test_url = os.getenv('DEFAULT_RTSP_URL', '')
        status = camera_service._test_rtsp_connection(test_url) if hasattr(camera_service, '_test_rtsp_connection') else 'unsupported'
        return jsonify({
            'success': True,
            'url': test_url,
            'status': status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 200

@app.route('/api/admin/reload', methods=['POST'])
def admin_hot_reload():
    """Recharge la configuration (.env) et reconfigure les services sans redémarrer."""
    try:
        # Recharger .env
        try:
            load_dotenv(override=True)
        except Exception:
            pass

        status = {}

        # Mettre à jour le niveau de logs dynamiquement
        try:
            lvl_name = os.getenv('LOG_LEVEL', 'INFO').upper()
            new_level = getattr(logging, lvl_name, logging.INFO)
            logging.getLogger().setLevel(new_level)  # root
            logger.setLevel(new_level)
            status['log_level'] = lvl_name
        except Exception as e:
            status['log_level_error'] = str(e)

        # Recharger AI
        try:
            if hasattr(ai_service, 'reload_from_env'):
                status['ai_reloaded'] = bool(ai_service.reload_from_env())
            else:
                status['ai_reloaded'] = False
        except Exception as e:
            status['ai_error'] = str(e)

        # Recharger MQTT et reconfigurer les capteurs
        try:
            if hasattr(mqtt_service, 'reload_from_env'):
                status['mqtt_reloaded'] = bool(mqtt_service.reload_from_env())
            else:
                status['mqtt_reloaded'] = False
        except Exception as e:
            status['mqtt_error'] = str(e)

        try:
            if getattr(mqtt_service, 'is_connected', False):
                if hasattr(detection_service, 'reconfigure_mqtt_sensors'):
                    detection_service.reconfigure_mqtt_sensors()
                    status['mqtt_sensors_reconfigured'] = True
        except Exception as e:
            status['mqtt_sensors_error'] = str(e)

        # Recharger caméra (cache/cfg)
        try:
            if hasattr(camera_service, 'refresh_from_env'):
                camera_service.refresh_from_env()
                status['camera_refreshed'] = True
        except Exception as e:
            status['camera_error'] = str(e)

        # Mettre à jour l'intervalle d'analyse
        try:
            detection_service.min_analysis_interval = float(os.getenv('MIN_ANALYSIS_INTERVAL', '0.1'))
            status['min_analysis_interval'] = detection_service.min_analysis_interval
        except Exception as e:
            status['min_analysis_interval_error'] = str(e)

        return jsonify({'success': True, 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/config', methods=['POST'])
def save_admin_config():
    """Sauvegarde la configuration"""
    try:
        config = request.get_json()
        
        if not config:
            return jsonify({
                'success': False,
                'error': 'Aucune configuration fournie'
            }), 400
        
        # Construire le contenu du fichier .env
        env_content = []
        
        # Configuration IA
        env_content.append("# Configuration IA")
        env_content.append(f"AI_API_MODE={_sanitize_env_value(config.get('AI_API_MODE', 'lmstudio'), 'AI_API_MODE')}")
        env_content.append(f"AI_TIMEOUT={_sanitize_env_value(config.get('AI_TIMEOUT', '10'), 'AI_TIMEOUT')}")
        env_content.append("")

        # Configuration Logs
        env_content.append("# Configuration Logs")
        env_content.append(f"LOG_LEVEL={_sanitize_env_value(config.get('LOG_LEVEL', 'INFO'), 'LOG_LEVEL')}")
        env_content.append("")
        
        # Configuration OpenAI
        env_content.append("# Configuration OpenAI")
        env_content.append(f"OPENAI_API_KEY={_sanitize_env_value(config.get('OPENAI_API_KEY', ''), 'OPENAI_API_KEY')}")
        env_content.append(f"OPENAI_MODEL={_sanitize_env_value(config.get('OPENAI_MODEL', 'gpt-4-vision-preview'), 'OPENAI_MODEL')}")
        env_content.append("")
        
        # Configuration LM Studio
        env_content.append("# Configuration LM Studio")
        env_content.append(f"LMSTUDIO_URL={_sanitize_env_value(config.get('LMSTUDIO_URL', 'http://127.0.0.1:11434/v1'), 'LMSTUDIO_URL')}")
        env_content.append(f"LMSTUDIO_MODEL={_sanitize_env_value(config.get('LMSTUDIO_MODEL', ''), 'LMSTUDIO_MODEL')}")
        env_content.append("")
        
        # Configuration Ollama
        env_content.append("# Configuration Ollama")
        env_content.append(f"OLLAMA_URL={_sanitize_env_value(config.get('OLLAMA_URL', 'http://127.0.0.1:11434/v1'), 'OLLAMA_URL')}")
        env_content.append(f"OLLAMA_MODEL={_sanitize_env_value(config.get('OLLAMA_MODEL', ''), 'OLLAMA_MODEL')}")
        env_content.append("")
        
        # Configuration MQTT
        env_content.append("# Configuration MQTT")
        env_content.append(f"MQTT_BROKER={_sanitize_env_value(config.get('MQTT_BROKER', '127.0.0.1'), 'MQTT_BROKER')}")
        env_content.append(f"MQTT_PORT={_sanitize_env_value(config.get('MQTT_PORT', '1883'), 'MQTT_PORT')}")
        env_content.append(f"MQTT_USERNAME={_sanitize_env_value(config.get('MQTT_USERNAME', ''), 'MQTT_USERNAME')}")
        env_content.append(f"MQTT_PASSWORD={_sanitize_env_value(config.get('MQTT_PASSWORD', ''), 'MQTT_PASSWORD')}")
        env_content.append("")
        
        # Configuration Home Assistant
        env_content.append("\n# Configuration Home Assistant")
        env_content.append(f"HA_DEVICE_NAME={_sanitize_env_value(config.get('HA_DEVICE_NAME', 'IAction'), 'HA_DEVICE_NAME')}")
        env_content.append(f"HA_DEVICE_ID={_sanitize_env_value(config.get('HA_DEVICE_ID', 'iaction_camera'), 'HA_DEVICE_ID')}")
        env_content.append("")
        
        # Configuration Caméra
        env_content.append("\n# Configuration Caméra")
        env_content.append(f"CAPTURE_MODE={_sanitize_env_value(config.get('CAPTURE_MODE', 'rtsp'), 'CAPTURE_MODE')}")
        env_content.append(f"DEFAULT_RTSP_URL={_sanitize_env_value(config.get('DEFAULT_RTSP_URL', ''), 'DEFAULT_RTSP_URL')}")
        env_content.append(f"RTSP_USERNAME={_sanitize_env_value(config.get('RTSP_USERNAME', ''), 'RTSP_USERNAME')}")
        env_content.append(f"RTSP_PASSWORD={_sanitize_env_value(config.get('RTSP_PASSWORD', ''), 'RTSP_PASSWORD')}")

        # Configuration HA Polling
        env_content.append("\n# Configuration HA Polling")
        env_content.append(f"HA_BASE_URL={_sanitize_env_value(config.get('HA_BASE_URL', ''), 'HA_BASE_URL')}")
        env_content.append(f"HA_TOKEN={_sanitize_env_value(config.get('HA_TOKEN', ''), 'HA_TOKEN')}")
        env_content.append(f"HA_ENTITY_ID={_sanitize_env_value(config.get('HA_ENTITY_ID', ''), 'HA_ENTITY_ID')}")
        env_content.append(f"HA_IMAGE_ATTR={_sanitize_env_value(config.get('HA_IMAGE_ATTR', 'entity_picture'), 'HA_IMAGE_ATTR')}")
        env_content.append(f"HA_POLL_INTERVAL={_sanitize_env_value(config.get('HA_POLL_INTERVAL', '1.0'), 'HA_POLL_INTERVAL')}")

        # Configuration Analyse
        env_content.append("\n# Configuration Analyse")
        env_content.append(f"MIN_ANALYSIS_INTERVAL={_sanitize_env_value(config.get('MIN_ANALYSIS_INTERVAL', '0.1'), 'MIN_ANALYSIS_INTERVAL')}")

        # Écrire le fichier .env
        with open('.env', 'w', encoding='utf-8') as f:
            f.write('\n'.join(env_content))
        
        return jsonify({
            'success': True,
            'message': 'Configuration sauvegardée avec succès'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur lors de la sauvegarde: {str(e)}'
        }), 500



@app.route('/api/admin/restart', methods=['POST'])
def restart_app():
    """Redémarre l'application"""
    try:
        # Récupérer la fonction shutdown du serveur pour libérer le port proprement
        shutdown_fn = None
        try:
            shutdown_fn = request.environ.get('werkzeug.server.shutdown')
        except Exception:
            shutdown_fn = None
        # Démarrer un redémarrage différé pour que la réponse HTTP parte correctement
        threading.Thread(target=_delayed_self_restart, kwargs={'delay_sec': 1.0, 'shutdown_fn': shutdown_fn}, daemon=True).start()
        return jsonify({'success': True, 'message': 'Redémarrage en cours (nouveau processus).'} )
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur lors du redémarrage: {str(e)}'
        }), 500

@app.route('/api/admin/shutdown', methods=['POST'])
def shutdown_app():
    """Arrête proprement l'application (fallback si Ctrl+C ne fonctionne pas).
    Limité à l'accès local (127.0.0.1 / ::1).
    """
    try:
        ra = request.remote_addr
        if ra not in ('127.0.0.1', '::1'):
            return jsonify({'success': False, 'error': 'Accès refusé'}), 403
        logger.info("Demande d'arrêt via /api/admin/shutdown")
        cleanup()
        # Sortie différée pour laisser la réponse HTTP partir
        def _exit():
            time.sleep(0.2)
            os._exit(0)
        threading.Thread(target=_exit, daemon=True).start()
        return jsonify({'success': True, 'message': 'Arrêt en cours...'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Fonction pour nettoyer les ressources avant l'arrêt de l'application
def cleanup():
    global shutting_down, is_capturing
    if shutting_down:
        return
    logger.info("Nettoyage des ressources...")
    # Poser les flags d'arrêt
    shutting_down = True
    is_capturing = False
    try:
        camera_service.stop_capture()
    except Exception as e:
        logger.warning(f"Erreur lors de l'arrêt de la caméra: {e}")
    try:
        # Publier l'état de capture (OFF) avant de se déconnecter
        mqtt_service.publish_binary_sensor_state('capture_active', False)
    except Exception:
        pass
    try:
        mqtt_service.disconnect()
    except Exception as e:
        logger.warning(f"Erreur lors de la déconnexion MQTT: {e}")

# Enregistrer la fonction de nettoyage pour qu'elle soit appelée à la fermeture
import atexit
atexit.register(cleanup)

if __name__ == '__main__':
    # Gestion des signaux (Ctrl+C / arrêt système)
    try:
        import signal
        def _handle_signal(signum, frame):
            logger.info(f"Signal reçu ({signum}), arrêt en cours...")
            try:
                cleanup()
            finally:
                # Petite attente pour laisser finir les réponses HTTP
                time.sleep(0.2)
                os._exit(0)
        signal.signal(signal.SIGINT, _handle_signal)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, _handle_signal)
        # Sous Windows, gérer aussi Ctrl+Pause (SIGBREAK)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, _handle_signal)
    except Exception:
        # En cas d'échec, on poursuivra sans handler explicite
        pass
    logger.info("=== DÉMARRAGE IACTION ===")
    # Si ce processus est lancé par un redémarrage, attendre la libération du port HTTP
    try:
        if os.environ.get('IACTION_WAIT_FOR_PID'):
            logger.info("⏳ Attente de la libération du port 5002 par l'ancien processus (bind test)...")
            _wait_until_bind_possible('0.0.0.0', 5002, timeout=10.0)
        os.environ.pop('IACTION_WAIT_FOR_PID', None)
    except Exception:
        pass
    logger.info("Tentative de connexion au broker MQTT...")
    
    # Initier la connexion MQTT
    mqtt_service.connect()
    
    # Attendre que la connexion soit établie (ou échoue)
    logger.info("Vérification de la connexion MQTT...")
    max_wait = 10  # Attendre maximum 10 secondes
    wait_time = 0
    
    while wait_time < max_wait:
        if mqtt_service.is_connected:
            logger.info("✅ MQTT: Connexion réussie au broker")
            logger.info("✅ MQTT: Capteurs configurés pour Home Assistant")
            # Reconfigurer les capteurs des détections après connexion MQTT
            try:
                if hasattr(detection_service, 'reconfigure_mqtt_sensors'):
                    detection_service.reconfigure_mqtt_sensors()
            except Exception as e:
                logger.error(f"Erreur reconfiguration MQTT des détections: {e}")
            break
        time.sleep(1)
        wait_time += 1
        if wait_time % 3 == 0:
            logger.info(f"⏳ MQTT: Tentative de connexion... ({wait_time}/{max_wait}s)")
    
    if not mqtt_service.is_connected:
        logger.error("❌ MQTT: Connexion échouée - Les capteurs ne seront pas disponibles")
        logger.error("   Vérifiez votre broker MQTT et votre configuration .env")
    
    logger.info("\n=== DÉMARRAGE DU SERVEUR WEB ===")
    debug_mode = '--debug' in sys.argv
    no_reloader = '--no-reloader' in sys.argv or os.getenv('NO_RELOADER', '').lower() in ('1', 'true', 'yes')
    is_windows = os.name == 'nt'

    # Désactiver systématiquement le reloader pour éviter WinError 10038 (Windows)
    os.environ.pop('WERKZEUG_RUN_MAIN', None)
    os.environ.pop('WERKZEUG_SERVER_FD', None)

    try:
        if debug_mode:
            logger.info("Mode: DEBUG")
            _run_web_server_with_retry(host='0.0.0.0', port=5002, debug=True)
        else:
            logger.info("Mode: PRODUCTION")
            _run_web_server_with_retry(host='0.0.0.0', port=5002, debug=False)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt reçu, arrêt en cours...")
        cleanup()
        os._exit(0)
