from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import cv2
import threading
import time
import base64
import json
import os
from dotenv import load_dotenv
from services.camera_service import CameraService
from services.ai_service import AIService
from services.mqtt_service import get_mqtt_instance, MQTTService
from services.detection_service import DetectionService

# Charger les variables d'environnement
load_dotenv(override=True)  # Forcer le remplacement des variables d'environnement existantes

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/cameras')
def get_cameras():
    """Récupère la liste des caméras disponibles"""
    cameras = camera_service.get_available_cameras()
    return jsonify(cameras)

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
        print(f"INFO: {status_request_count} requêtes /api/status reçues dans les {status_log_interval} dernières secondes")
        status_request_count = 0
        last_status_log_time = current_time
    
    status = {
        'last_analysis_time': last_analysis_time,
        'last_analysis_duration': last_analysis_duration,
        'analysis_in_progress': analysis_in_progress
    }
    
    return jsonify(status)

@app.route('/api/start_capture', methods=['POST'])
def start_capture():
    """Démarre la capture vidéo"""
    global is_capturing, capture_thread
    
    data = request.json
    source = data.get('source')
    source_type = data.get('type')
    
    if is_capturing:
        return jsonify({'error': 'Capture déjà en cours'}), 400
    
    success = camera_service.start_capture(source, source_type)
    if not success:
        return jsonify({'error': 'Impossible de démarrer la capture'}), 400
    
    is_capturing = True
    capture_thread = threading.Thread(target=capture_loop)
    capture_thread.daemon = True
    capture_thread.start()
    
    return jsonify({'status': 'Capture démarrée'})

@app.route('/api/stop_capture', methods=['POST'])
def stop_capture():
    """Arrête la capture vidéo"""
    global is_capturing
    
    is_capturing = False
    camera_service.stop_capture()
    
    return jsonify({'status': 'Capture arrêtée'})

@app.route('/api/detections')
def get_detections():
    """Récupère la liste des détections configurées"""
    return jsonify(detection_service.get_detections())

@app.route('/api/detections', methods=['POST'])
def add_detection():
    """Ajoute une nouvelle détection personnalisée"""
    data = request.json
    name = data.get('name')
    phrase = data.get('phrase')
    
    if not name or not phrase:
        return jsonify({'error': 'Nom et phrase requis'}), 400
    
    detection_id = detection_service.add_detection(name, phrase)
    return jsonify({'id': detection_id, 'status': 'Détection ajoutée'})

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
        global current_frame, video_feed_connections
        error_count = 0
        max_errors = 5
        
        # Incrémenter le compteur de connexions
        video_feed_connections += 1
        connection_id = video_feed_connections
        print(f"Démarrage du flux vidéo (connexion #{connection_id})...")
        
        # Vérifier si c'est une reconnexion rapide (moins de 5 secondes depuis la dernière connexion)
        global last_video_feed_connection_time
        current_time = time.time()
        if hasattr(app, 'last_video_feed_connection_time') and current_time - app.last_video_feed_connection_time < 5:
            print(f"Reconnexion rapide détectée (#{connection_id}) - Intervalle: {current_time - app.last_video_feed_connection_time:.2f}s")
        
        # Mettre à jour le temps de la dernière connexion
        app.last_video_feed_connection_time = current_time
        
        while True:
            try:
                if current_frame is not None:
                    # Convertir l'image en JPEG
                    success, buffer = cv2.imencode('.jpg', current_frame)
                    if success:
                        frame = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                        error_count = 0  # Réinitialiser le compteur d'erreurs
                    else:
                        print("Erreur d'encodage de l'image")
                        error_count += 1
                else:
                    print("Pas d'image disponible")
                    error_count += 1
                    
                # Si trop d'erreurs consécutives, arrêter le flux
                if error_count > max_errors:
                    print(f"Trop d'erreurs dans le flux vidéo, arrêt du flux (connexion #{connection_id})")
                    break
                    
                time.sleep(0.1)
            except Exception as e:
                print(f"Exception dans le flux vidéo: {e}")
                error_count += 1
                if error_count > max_errors:
                    print(f"Trop d'exceptions dans le flux vidéo, arrêt du flux (connexion #{connection_id})")
                    break
                time.sleep(0.5)  # Attendre un peu plus longtemps en cas d'erreur
        
        # Message de fin de connexion
        print(f"Fin du flux vidéo (connexion #{connection_id})")
        return
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

def capture_loop():
    """Boucle principale de capture et analyse"""
    global current_frame, is_capturing, analysis_in_progress, last_analysis_time, last_analysis_duration
    
    min_analysis_interval = 0.5  # Intervalle minimum entre les analyses (secondes)
    
    while is_capturing:
        frame = camera_service.get_frame()
        if frame is not None:
            current_frame = frame
            
            # Analyser l'image seulement si aucune analyse n'est en cours
            # et si l'intervalle minimum est respecté
            current_time = time.time()
            time_since_last_analysis = current_time - last_analysis_time
            
            if not analysis_in_progress and time_since_last_analysis >= min_analysis_interval:
                # Démarrer une nouvelle analyse dans un thread séparé
                analysis_thread = threading.Thread(target=analyze_frame, args=(frame.copy(), current_time))
                analysis_thread.daemon = True
                analysis_thread.start()
                analysis_in_progress = True
                print(f"Démarrage d'une nouvelle analyse, {time_since_last_analysis:.1f}s après la dernière")
        
        time.sleep(0.033)  # ~30 FPS

def analyze_frame(frame, start_time):
    """Analyse une image avec l'IA"""
    global analysis_in_progress, last_analysis_time, last_analysis_duration
    
    try:
        # Encoder l'image en base64
        _, buffer = cv2.imencode('.jpg', frame)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Analyser avec les détections configurées
        result = detection_service.analyze_frame(img_base64)
        
        # Calculer la durée de l'analyse
        end_time = time.time()
        duration = end_time - start_time
        
        # Mettre à jour les variables globales
        last_analysis_time = end_time
        last_analysis_duration = duration
        
        print(f"Analyse terminée en {duration:.2f} secondes")
        
        # Publier les informations d'analyse via MQTT
        mqtt_service.publish_status({
            'last_analysis_time': last_analysis_time,
            'last_analysis_duration': last_analysis_duration,
            'analysis_result': result
        })
        
    except Exception as e:
        print(f"Erreur lors de l'analyse: {e}")
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

# Fonction pour nettoyer les ressources avant l'arrêt de l'application
def cleanup():
    print("Nettoyage des ressources...")
    mqtt_service.disconnect()
    camera_service.stop_capture()

# Enregistrer la fonction de nettoyage pour qu'elle soit appelée à la fermeture
import atexit
atexit.register(cleanup)

if __name__ == '__main__':
    import sys
    
    # Vérifier les arguments de ligne de commande
    debug_mode = '--debug' in sys.argv
    
    # Initialiser MQTT une seule fois
    mqtt_service.connect()
    
    if debug_mode:
        print("Démarrage en mode DEBUG - Attendez-vous à des reconnexions MQTT fréquentes")
        app.run(debug=True, host='0.0.0.0', port=5002, threaded=True, use_reloader=True)
    else:
        print("Démarrage en mode PRODUCTION - Connexion MQTT stable")
        # Mode production sans rechargement automatique
        app.run(debug=False, host='0.0.0.0', port=5002, threaded=True, use_reloader=False)
