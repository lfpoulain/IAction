import cv2
import threading
import time
import os
import subprocess
from PIL import Image
import io
from dotenv import load_dotenv
from urllib.parse import urlparse

class CameraService:
    def __init__(self):
        self.cap = None
        self.is_capturing = False
        self.capture_thread = None
        self.current_frame = None
        self.current_source = None
        self.current_type = None
        self.lock = threading.Lock()
        self.frame_lock = threading.Lock()
        self._v4l2_devices = []
        self.cameras_cache = None
        self.cache_time = 0
        self.cache_duration = 30  # Cache pendant 30 secondes
        
        load_dotenv()
        
        # Détecter les dispositifs V4L2 au démarrage (Linux uniquement)
        self._detect_v4l2_devices()
        
        # Configuration RTSP
        self.default_rtsp_urls = [
            {
                'name': 'RTSP Default',
                'url': os.getenv('DEFAULT_RTSP_URL', ''),
                'username': os.getenv('RTSP_USERNAME', ''),
                'password': os.getenv('RTSP_PASSWORD', ''),
                'enabled': bool(os.getenv('DEFAULT_RTSP_URL', ''))
            }
        ]
        

    
    def get_available_cameras(self):
        """Détecte les caméras USB et RTSP disponibles (Linux uniquement)"""
        if self.cameras_cache is not None and time.time() - self.cache_time < self.cache_duration:
            return self.cameras_cache
        
        print("=== Début de la détection des caméras ===")
        cameras = []
        
        # Détecter les caméras USB Linux (V4L2)
        usb_cameras = self._detect_linux_cameras()
        cameras.extend(usb_cameras)
        
        # Ajouter les caméras RTSP configurées
        rtsp_cameras = self._get_rtsp_cameras()
        cameras.extend(rtsp_cameras)
        
        print(f"Détection terminée: {len(cameras)} caméra(s) trouvée(s)")
        for cam in cameras:
            print(f" - {cam['name']} (type: {cam['type']}, id: {cam['id']})")
        print("=== Fin de la détection des caméras ===")
        
        # Mettre en cache le résultat
        self.cameras_cache = cameras
        self.cache_time = time.time()
        
        return cameras
    
    def _detect_v4l2_devices(self):
        """Détecte les périphériques V4L2 sur Linux"""
        devices = []
        try:
            # Utiliser v4l2-ctl pour lister les périphériques
            result = subprocess.run(['v4l2-ctl', '--list-devices'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                current_device = None
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('\t'):
                        current_device = line
                    elif line.startswith('\t/dev/video'):
                        device_path = line.strip()
                        devices.append({
                            'name': current_device,
                            'path': device_path,
                            'index': int(device_path.split('video')[1])
                        })
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            # Fallback si v4l2-ctl n'est pas disponible
            for i in range(10):
                device_path = f'/dev/video{i}'
                if os.path.exists(device_path):
                    devices.append({
                        'name': f'Video Device {i}',
                        'path': device_path,
                        'index': i
                    })
        
        return devices
    
    def _detect_linux_cameras(self):
        """Détecte les caméras USB sur Linux en utilisant V4L2"""
        cameras = []
        
        for device in self._v4l2_devices:
            try:
                print(f"Test de {device['name']} ({device['path']})...")
                
                # Tester avec OpenCV
                cap = cv2.VideoCapture(device['index'])
                
                if cap.isOpened():
                    # Configuration rapide pour le test
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    
                    # Test rapide avec timeout
                    result = {'ret': False, 'frame': None}
                    
                    def read_frame():
                        try:
                            result['ret'], result['frame'] = cap.read()
                        except Exception as e:
                            print(f"Erreur lecture {device['name']}: {e}")
                            result['ret'] = False
                    
                    # Lancer la lecture dans un thread avec timeout
                    thread = threading.Thread(target=read_frame)
                    thread.daemon = True
                    thread.start()
                    thread.join(timeout=3.0)  # Timeout de 3 secondes
                    
                    if thread.is_alive():
                        print(f"Timeout pour {device['name']}")
                        cap.release()
                        continue
                    
                    ret, frame = result['ret'], result['frame']
                    if ret and frame is not None and frame.size > 0:
                        # Obtenir les capacités de résolution
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        
                        camera_info = {
                            'id': device['index'],
                            'name': device['name'] or f"Caméra USB {device['index']}",
                            'type': 'usb',
                            'path': device['path'],
                            'resolution': f"{width}x{height}" if width > 0 and height > 0 else "auto",
                            'supported_formats': self._get_supported_formats(device['index'])
                        }
                        
                        cameras.append(camera_info)
                        print(f"Caméra ajoutée: {camera_info['name']}")
                
                cap.release()
                
            except Exception as e:
                print(f"Erreur lors du test de {device['name']}: {e}")
        
        return cameras
    
    def _detect_standard_cameras(self):
        """Détecte les caméras avec la méthode standard (non-Linux)"""
        cameras = []
        
        for i in range(10):
            cap = None
            try:
                print(f"Test de la caméra {i}...")
                cap = cv2.VideoCapture(i)
                
                # Configuration rapide
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FPS, 15)
                
                if cap.isOpened():
                    # Test rapide avec timeout
                    result = {'ret': False, 'frame': None}
                    
                    def read_frame():
                        try:
                            result['ret'], result['frame'] = cap.read()
                        except Exception as e:
                            print(f"Erreur lecture caméra {i}: {e}")
                            result['ret'] = False
                    
                    # Lancer la lecture dans un thread avec timeout
                    thread = threading.Thread(target=read_frame)
                    thread.daemon = True
                    thread.start()
                    thread.join(timeout=3.0)  # Timeout de 3 secondes
                    
                    if thread.is_alive():
                        print(f"Timeout pour la caméra {i}")
                        continue
                    
                    ret, frame = result['ret'], result['frame']
                    if ret and frame is not None and frame.size > 0:
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        
                        # Nom plus descriptif
                        camera_name = f"Caméra {i}"
                        if i == 0:
                            camera_name = "Caméra principale"
                        if width > 0 and height > 0:
                            camera_name += f" ({width}x{height})"
                        
                        cameras.append({
                            'id': i,
                            'name': camera_name,
                            'type': 'usb',
                            'resolution': f"{width}x{height}" if width > 0 and height > 0 else "auto"
                        })
                        print(f"Caméra {i} ajoutée à la liste: {camera_name}")
                    else:
                        print(f"Caméra {i} ouverte mais pas d'image valide")
                else:
                    print(f"Caméra {i} n'a pas pu être ouverte")
                        
            except Exception as e:
                print(f"Erreur caméra {i}: {e}")
            finally:
                if cap is not None:
                    try:
                        cap.release()
                        print(f"Caméra {i} libérée")
                    except Exception as e:
                        print(f"Erreur lors de la libération de la caméra {i}: {e}")
        
        return cameras
    
    def _get_supported_formats(self, device_index):
        """Obtient les formats supportés par une caméra (Linux uniquement)"""
        
        formats = []
        try:
            result = subprocess.run(['v4l2-ctl', f'--device=/dev/video{device_index}', '--list-formats-ext'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                current_format = None
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if 'Pixel Format:' in line:
                        current_format = line.split("'")[1] if "'" in line else None
                    elif 'Size: Discrete' in line and current_format:
                        size_info = line.split('Size: Discrete ')[1]
                        if size_info:
                            formats.append({
                                'format': current_format,
                                'size': size_info
                            })
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            pass
        
        return formats
    
    def _get_rtsp_cameras(self):
        """Récupère les caméras RTSP configurées"""
        rtsp_cameras = []
        
        # Ajouter les URLs RTSP par défaut
        for idx, rtsp_config in enumerate(self.default_rtsp_urls):
            if rtsp_config['enabled']:
                camera_name = f"RTSP Camera {idx + 1}"
                if rtsp_config['name']:
                    camera_name = rtsp_config['name']
                
                rtsp_cameras.append({
                    'id': f'rtsp_{idx}',
                    'name': camera_name,
                    'type': 'rtsp',
                    'url': rtsp_config['url'],
                    'username': rtsp_config['username'],
                    'password': rtsp_config['password'],
                    'test_status': self._test_rtsp_connection(rtsp_config['url'])
                })
        
        # Ajouter l'option RTSP personnalisée
        rtsp_cameras.append({
            'id': 'rtsp_custom',
            'name': '📹 Caméra IP - URL personnalisée',
            'type': 'rtsp',
            'description': 'Saisissez votre propre URL RTSP'
        })
        
        return rtsp_cameras
    
    def _test_rtsp_connection(self, url, timeout=5):
        """Test la connexion RTSP"""
        if not url:
            return 'not_configured'
        
        try:
            cap = cv2.VideoCapture(url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                return 'online' if ret and frame is not None else 'error'
            else:
                cap.release()
                return 'offline'
        except Exception:
            return 'error'
    
    def get_camera_info(self, camera_id):
        """Obtient des informations détaillées sur une caméra"""
        cameras = self.get_available_cameras()
        for camera in cameras:
            if str(camera['id']) == str(camera_id):
                return camera
        return None
    
    def validate_rtsp_url(self, url):
        """Valide et normalise une URL RTSP"""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ['rtsp', 'http', 'https']:
                return False, "Protocol non supporté. Utilisez rtsp://, http:// ou https://"
            
            if not parsed.hostname:
                return False, "Hostname manquant dans l'URL"
            
            return True, "URL valide"
        except Exception as e:
            return False, f"URL invalide: {str(e)}"
    
    def build_rtsp_url(self, ip, port=554, username='', password='', path=''):
        """Construit une URL RTSP à partir des composants"""
        if username and password:
            auth = f"{username}:{password}@"
        else:
            auth = ""
        
        if not path.startswith('/'):
            path = '/' + path if path else '/'
        
        return f"rtsp://{auth}{ip}:{port}{path}"
    
    def start_capture(self, source, source_type=None, rtsp_url=None):
        """Démarre la capture depuis une source améliorée"""
        with self.lock:
            if self.is_capturing:
                self.stop_capture()
            
            try:
                # Déterminer le type automatiquement si non spécifié
                if source_type is None:
                    if isinstance(source, str) and ('rtsp://' in source or 'http' in source):
                        source_type = 'rtsp'
                    else:
                        source_type = 'usb'
                
                print(f"Démarrage de la capture - Source: {source}, Type: {source_type}")
                
                if source_type == 'usb':
                    # Caméra USB
                    source_id = int(source) if isinstance(source, str) else source
                    print(f"Ouverture de la caméra USB avec l'index {source_id}")
                    
                    # Configuration Linux avec backend V4L2
                    print(f"Ouverture avec backend V4L2 pour caméra USB {source_id}")
                    self.cap = cv2.VideoCapture(source_id, cv2.CAP_V4L2)
                    if not self.cap.isOpened():
                        print("Tentative avec le backend par défaut...")
                        self.cap = cv2.VideoCapture(source_id)
                    
                elif source_type == 'rtsp':
                    # Caméra RTSP
                    actual_url = rtsp_url if rtsp_url else source
                    
                    # Gestion des caméras RTSP préconfigurées
                    if isinstance(source, str) and source.startswith('rtsp_'):
                        camera_info = self.get_camera_info(source)
                        if camera_info and 'url' in camera_info:
                            actual_url = camera_info['url']
                            if camera_info.get('username') and camera_info.get('password'):
                                # Construire l'URL avec authentification
                                from urllib.parse import urlparse, urlunparse
                                parsed = urlparse(actual_url)
                                auth_netloc = f"{camera_info['username']}:{camera_info['password']}@{parsed.hostname}"
                                if parsed.port:
                                    auth_netloc += f":{parsed.port}"
                                parsed = parsed._replace(netloc=auth_netloc)
                                actual_url = urlunparse(parsed)
                    
                    print(f"Ouverture du flux RTSP: {actual_url[:50]}...")
                    
                    # Configuration optimisée pour RTSP
                    self.cap = cv2.VideoCapture(actual_url)
                    
                    # Configuration RTSP spécifique
                    if self.cap.isOpened():
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Buffer minimal
                        self.cap.set(cv2.CAP_PROP_FPS, 30)
                        # Timeout pour éviter les blocages
                        self.cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
                        
                else:
                    print(f"Type de source non pris en charge: {source_type}")
                    return False
                
                if not self.cap.isOpened():
                    print("Impossible d'ouvrir la source vidéo")
                    return False
                
                # Configuration générale de la caméra
                print("Configuration des propriétés de la caméra")
                
                # Résolution adaptée au type
                if source_type == 'rtsp':
                    # Pour RTSP, respecter la résolution native autant que possible
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                else:
                    # Pour USB, résolution standard
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Réduire la latence
                
                # Test de lecture avec plusieurs tentatives pour RTSP
                max_attempts = 3 if source_type == 'rtsp' else 1
                test_frame = None
                
                for attempt in range(max_attempts):
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        break
                    if attempt < max_attempts - 1:
                        print(f"Tentative {attempt + 1} échouée, nouvelle tentative...")
                        time.sleep(0.5)
                
                if test_frame is None or test_frame.size == 0:
                    print("Impossible de lire une image depuis la caméra")
                    self.cap.release()
                    self.cap = None
                    return False
                    
                print(f"Capture démarrée avec succès - Dimensions: {test_frame.shape}")
                
                self.current_source = rtsp_url if rtsp_url else source
                self.current_type = source_type
                self.is_capturing = True
                
                return True
                
            except Exception as e:
                print(f"Erreur lors du démarrage de la capture: {e}")
                if self.cap:
                    self.cap.release()
                    self.cap = None
                return False
    
    def stop_capture(self):
        """Arrête la capture"""
        with self.lock:
            self.is_capturing = False
            if self.cap:
                self.cap.release()
                self.cap = None
            self.current_source = None
            self.current_type = None
    
    def get_frame(self):
        """Récupère une image de la caméra avec gestion améliorée"""
        with self.lock:
            if not self.is_capturing or not self.cap:
                return None
            
            try:
                # Lecture avec gestion des différents types de caméras
                ret, frame = self.cap.read()
                
                if ret and frame is not None and frame.size > 0:
                    return frame
                else:
                    # Gestion spécifique selon le type de caméra
                    if self.current_type == 'rtsp':
                        # Pour RTSP, plusieurs tentatives avec délai
                        for attempt in range(3):
                            time.sleep(0.1)  # Petit délai
                            ret, frame = self.cap.read()
                            if ret and frame is not None and frame.size > 0:
                                return frame
                        
                        # Si toujours échec, essayer de réinitialiser
                        print("Erreur de lecture RTSP, tentative de reconnexion...")
                        return self._reconnect_camera()
                    
                    else:
                        # Pour USB, réinitialisation directe
                        print("Erreur de lecture USB, tentative de réinitialisation...")
                        return self._reconnect_camera()
                        
            except Exception as e:
                print(f"Exception lors de la lecture de la caméra: {e}")
                if self.current_type == 'rtsp':
                    # Pour RTSP, essayer une reconnexion
                    return self._reconnect_camera()
                return None
    
    def _reconnect_camera(self):
        """Tente de reconnecter la caméra"""
        if self.current_source is None or self.current_type is None:
            return None
        
        try:
            # Fermer la connexion actuelle
            if self.cap:
                self.cap.release()
            
            # Réouvrir selon le type
            if self.current_type == 'usb':
                source_id = int(self.current_source) if isinstance(self.current_source, str) else self.current_source
                # Linux uniquement avec V4L2
                self.cap = cv2.VideoCapture(source_id, cv2.CAP_V4L2)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(source_id)
            
            elif self.current_type == 'rtsp':
                self.cap = cv2.VideoCapture(self.current_source)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if self.cap and self.cap.isOpened():
                print("Caméra reconnectée avec succès")
                # Reconfigurer
                if self.current_type == 'rtsp':
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                else:
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
                # Essayer de lire une image
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    return frame
            
            print("Impossible de reconnecter la caméra")
            return None
            
        except Exception as e:
            print(f"Erreur lors de la reconnexion: {e}")
            return None
    
    def is_active(self):
        """Vérifie si la capture est active"""
        return self.is_capturing
