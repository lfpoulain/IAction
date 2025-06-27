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
from services.mqtt_service import MQTTService
from services.detection_service import DetectionService

# Charger les variables d'environnement
load_dotenv()

app = Flask(__name__)
CORS(app)

# Services globaux
camera_service = CameraService()
ai_service = AIService()
mqtt_service = MQTTService()
detection_service = DetectionService(ai_service, mqtt_service)

# Variables globales
current_frame = None
is_capturing = False
capture_thread = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/cameras')
def get_cameras():
    """Récupère la liste des caméras disponibles"""
    cameras = camera_service.get_available_cameras()
    return jsonify(cameras)

@app.route('/api/cameras/quick')
def get_cameras_quick():
    """Récupère une liste rapide des caméras (sans détection USB)"""
    cameras = [
        {'id': 0, 'name': '[USB] Caméra USB 0 (par défaut)', 'type': 'usb'},
        {'id': 1, 'name': '[USB] Caméra USB 1', 'type': 'usb'},
        {'id': 'rtsp_custom', 'name': '[IP] Caméra IP - URL personnalisée', 'type': 'rtsp'},
        {'id': 'rtsp_hikvision', 'name': '[HIK] Caméra Hikvision (port 554)', 'type': 'rtsp_preset'},
        {'id': 'rtsp_dahua', 'name': '[DAH] Caméra Dahua (port 554)', 'type': 'rtsp_preset'}
    ]
    return jsonify(cameras)

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

@app.route('/video_feed')
def video_feed():
    """Stream vidéo en temps réel"""
    def generate():
        global current_frame
        while True:
            if current_frame is not None:
                _, buffer = cv2.imencode('.jpg', current_frame)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.1)
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

def capture_loop():
    """Boucle principale de capture et analyse"""
    global current_frame, is_capturing
    
    last_analysis_time = 0
    analysis_interval = 1.0  # 1 seconde
    
    while is_capturing:
        frame = camera_service.get_frame()
        if frame is not None:
            current_frame = frame
            
            # Analyser l'image toutes les secondes
            current_time = time.time()
            if current_time - last_analysis_time >= analysis_interval:
                threading.Thread(target=analyze_frame, args=(frame.copy(),)).start()
                last_analysis_time = current_time
        
        time.sleep(0.033)  # ~30 FPS

def analyze_frame(frame):
    """Analyse une image avec l'IA"""
    try:
        # Encoder l'image en base64
        _, buffer = cv2.imencode('.jpg', frame)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Analyser avec les détections configurées
        detection_service.analyze_frame(img_base64)
        
    except Exception as e:
        print(f"Erreur lors de l'analyse: {e}")

if __name__ == '__main__':
    # Initialiser MQTT
    mqtt_service.connect()
    
    # Démarrer l'application
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
