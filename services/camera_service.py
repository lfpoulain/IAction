import cv2
import threading
import time
import os
from PIL import Image
import io
from dotenv import load_dotenv
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)

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
        self.cameras_cache = None
        self.cache_time = 0
        self.cache_duration = 30  # Cache pendant 30 secondes
        
        load_dotenv()
        
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
        """Récupère les caméras RTSP disponibles"""
        if self.cameras_cache is not None and time.time() - self.cache_time < self.cache_duration:
            return self.cameras_cache
        
        logger.info("=== Chargement des options RTSP ===")
        
        # Seules les caméras RTSP sont supportées
        cameras = self._get_rtsp_cameras()
        
        logger.info(f"Options disponibles: {len(cameras)} source(s) RTSP configurée(s)")
        for cam in cameras:
            logger.info(f" - {cam['name']} (type: {cam['type']}, id: {cam['id']})")
        logger.info("=== Fin du chargement des options ===")
        
        # Mettre en cache le résultat
        self.cameras_cache = cameras
        self.cache_time = time.time()
        
        return cameras
    

    
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
        """Démarre la capture RTSP uniquement"""
        with self.lock:
            if self.is_capturing:
                self.stop_capture()
            
            try:
                # Seul RTSP est supporté
                source_type = 'rtsp'
                logger.info(f"Démarrage de la capture RTSP - Source: {source}")
                
                if source_type == 'rtsp':
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
                    
                    logger.info(f"Ouverture du flux RTSP: {actual_url[:50]}...")
                    
                    # Configuration optimisée pour RTSP
                    self.cap = cv2.VideoCapture(actual_url)
                    
                    # Configuration RTSP spécifique pour latence minimale
                    if self.cap.isOpened():
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Buffer minimal
                        self.cap.set(cv2.CAP_PROP_FPS, 30)
                        # Optimisations RTSP pour latence
                        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
                        # Pas de timeout pour éviter les délais
                        
                if not self.cap.isOpened():
                    logger.error("Impossible d'ouvrir la source vidéo RTSP")
                    return False
                
                # Configuration RTSP
                logger.info("Configuration des propriétés de la caméra RTSP")
                
                # Résolution 720p pour RTSP
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Réduire la latence
                
                # Test de lecture avec plusieurs tentatives pour RTSP
                max_attempts = 3
                test_frame = None
                
                for attempt in range(max_attempts):
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        break
                    if attempt < max_attempts - 1:
                        logger.warning(f"Tentative {attempt + 1} échouée, nouvelle tentative...")
                        time.sleep(0.5)
                
                if test_frame is None or test_frame.size == 0:
                    logger.error("Impossible de lire une image depuis la caméra")
                    self.cap.release()
                    self.cap = None
                    return False
                    
                logger.info(f"Capture démarrée avec succès - Dimensions: {test_frame.shape}")
                
                self.current_source = rtsp_url if rtsp_url else source
                self.current_type = source_type
                self.is_capturing = True
                
                return True
                
            except Exception as e:
                logger.error(f"Erreur lors du démarrage de la capture: {e}")
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
                # Pour RTSP, flush le buffer pour obtenir la frame la plus récente
                # Lire plusieurs frames rapidement pour vider le buffer
                for _ in range(3):
                    ret, frame = self.cap.read()
                    if not ret:
                        break
                
                if ret and frame is not None and frame.size > 0:
                    return frame
                else:
                    # Plusieurs tentatives avec délai
                    for attempt in range(3):
                        time.sleep(0.1)
                        ret, frame = self.cap.read()
                        if ret and frame is not None and frame.size > 0:
                            return frame

                    # Si toujours échec, essayer de réinitialiser
                    logger.warning("Erreur de lecture RTSP, tentative de reconnexion...")
                    return self._reconnect_camera()
                        
            except Exception as e:
                logger.exception(f"Exception lors de la lecture de la caméra: {e}")
                return self._reconnect_camera()
    
    def _reconnect_camera(self):
        """Tente de reconnecter la caméra"""
        if self.current_source is None or self.current_type is None:
            return None
        
        try:
            # Fermer la connexion actuelle
            if self.cap:
                self.cap.release()
            
            # Réouvrir la caméra RTSP
            self.cap = cv2.VideoCapture(self.current_source)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if self.cap and self.cap.isOpened():
                logger.info("Caméra RTSP reconnectée avec succès")
                # Reconfigurer pour RTSP - Maintenir 720p pour performance
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
                # Essayer de lire une image
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    return frame
            
            logger.error("Impossible de reconnecter la caméra")
            return None
            
        except Exception as e:
            logger.exception(f"Erreur lors de la reconnexion: {e}")
            return None
    
    def is_active(self):
        """Vérifie si la capture est active"""
        return self.is_capturing
