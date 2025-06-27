import cv2
import threading
import time
from PIL import Image
import io

class CameraService:
    def __init__(self):
        self.cap = None
        self.is_capturing = False
        self.current_source = None
        self.current_type = None
        self.lock = threading.Lock()
        self._camera_cache = None
        self._cache_time = 0
        self._cache_duration = 30  # Cache pendant 30 secondes
    
    def get_available_cameras(self):
        """Détecte les caméras USB disponibles de manière sécurisée"""
        if self._camera_cache is not None and time.time() - self._cache_time < self._cache_duration:
            return self._camera_cache
        
        cameras = []
        
        # Tester seulement les indices 0-2 pour être plus rapide
        for i in range(3):
            cap = None
            try:
                # Utiliser DirectShow sur Windows pour une détection plus rapide
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                
                # Configuration rapide
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FPS, 15)
                
                # Vérifier si la caméra est ouverte
                if cap.isOpened():
                    # Test de lecture avec timeout
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        # Obtenir des infos sur la caméra
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        
                        # Nom plus descriptif
                        camera_name = f"Caméra USB {i}"
                        if width > 0 and height > 0:
                            camera_name += f" ({width}x{height})"
                        
                        cameras.append({
                            'id': i,
                            'name': camera_name,
                            'type': 'usb',
                            'resolution': f"{width}x{height}" if width > 0 and height > 0 else "inconnue"
                        })
                        
            except Exception as e:
                print(f"Erreur caméra {i}: {e}")
            finally:
                # S'assurer que la caméra est libérée
                if cap is not None:
                    try:
                        cap.release()
                    except:
                        pass
        
        # Ajouter des options prédéfinies communes
        cameras.extend([
            {
                'id': 'rtsp_custom',
                'name': '[IP] Caméra IP - URL personnalisée',
                'type': 'rtsp',
                'description': 'Saisissez votre propre URL RTSP'
            },
            {
                'id': 'rtsp_hikvision',
                'name': '[HIK] Caméra Hikvision (port 554)',
                'type': 'rtsp_preset',
                'url_template': 'rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/101',
                'description': 'Caméras Hikvision standard'
            },
            {
                'id': 'rtsp_dahua',
                'name': '[DAH] Caméra Dahua (port 554)',
                'type': 'rtsp_preset',
                'url_template': 'rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel=1&subtype=0',
                'description': 'Caméras Dahua standard'
            },
            {
                'id': 'rtsp_generic',
                'name': '[GEN] Caméra IP générique (port 8554)',
                'type': 'rtsp_preset',
                'url_template': 'rtsp://{user}:{pass}@{ip}:8554/stream',
                'description': 'Caméras IP génériques'
            }
        ])
        
        # Mettre en cache le résultat
        self._camera_cache = cameras
        self._cache_time = time.time()
        
        return cameras
    
    def start_capture(self, source, source_type):
        """Démarre la capture depuis une source"""
        with self.lock:
            if self.is_capturing:
                self.stop_capture()
            
            try:
                if source_type == 'usb':
                    self.cap = cv2.VideoCapture(int(source))
                elif source_type == 'rtsp':
                    self.cap = cv2.VideoCapture(source)
                else:
                    return False
                
                if not self.cap.isOpened():
                    return False
                
                # Configuration de la caméra
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
                self.current_source = source
                self.current_type = source_type
                self.is_capturing = True
                
                return True
                
            except Exception as e:
                print(f"Erreur lors du démarrage de la capture: {e}")
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
        """Récupère une image de la caméra"""
        with self.lock:
            if not self.is_capturing or not self.cap:
                return None
            
            ret, frame = self.cap.read()
            if ret:
                return frame
            else:
                return None
    
    def is_active(self):
        """Vérifie si la capture est active"""
        return self.is_capturing
