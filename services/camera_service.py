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
        
        print("=== Début de la détection des caméras ===")
        cameras = []
        
        # Tester les indices pour trouver toutes les caméras disponibles
        # Commencer par l'index 0 qui est généralement la caméra par défaut (interne ou première USB)
        for i in range(10):
            cap = None
            try:
                print(f"Test de la caméra {i}...")
                # Utiliser la méthode standard pour macOS
                cap = cv2.VideoCapture(i)
                
                # Configuration rapide
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FPS, 15)
                
                # Vérifier si la caméra est ouverte
                if cap.isOpened():
                    print(f"Caméra {i} est ouverte")
                    # Test de lecture avec timeout
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        print(f"Caméra {i} a retourné une image valide")
                        # Obtenir des infos sur la caméra
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
                # S'assurer que la caméra est libérée
                if cap is not None:
                    try:
                        cap.release()
                        print(f"Caméra {i} libérée")
                    except Exception as e:
                        print(f"Erreur lors de la libération de la caméra {i}: {e}")
        
        print(f"Détection terminée: {len(cameras)} caméra(s) trouvée(s)")
        for cam in cameras:
            print(f" - {cam['name']} (id: {cam['id']})")
        print("=== Fin de la détection des caméras ===")
        
        # Ajouter uniquement l'option RTSP personnalisée
        cameras.append({
            'id': 'rtsp_custom',
            'name': '[IP] Caméra IP - URL personnalisée',
            'type': 'rtsp',
            'description': 'Saisissez votre propre URL RTSP'
        })
        
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
                print(f"Démarrage de la capture - Source: {source}, Type: {source_type}")
                
                if source_type == 'usb':
                    source_id = int(source)
                    print(f"Ouverture de la caméra USB avec l'index {source_id}")
                    
                    # Utiliser la méthode standard compatible avec toutes les plateformes
                    self.cap = cv2.VideoCapture(source_id)
                    
                    # Vérifier si la caméra est ouverte
                    if not self.cap.isOpened():
                        print("La méthode standard a échoué, tentative alternative...")
                        # Essayer avec une autre méthode si nécessaire
                        # Cette partie peut être adaptée selon la plateforme si besoin
                        self.cap = cv2.VideoCapture(source_id)
                        
                elif source_type == 'rtsp':
                    print(f"Ouverture du flux RTSP: {source}")
                    self.cap = cv2.VideoCapture(source)
                else:
                    print(f"Type de source non pris en charge: {source_type}")
                    return False
                
                if not self.cap.isOpened():
                    print("Impossible d'ouvrir la source vidéo")
                    return False
                
                # Configuration de la caméra
                print("Configuration des propriétés de la caméra")
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Réduire la latence
                
                # Tester la lecture d'une image
                ret, test_frame = self.cap.read()
                if not ret or test_frame is None:
                    print("Impossible de lire une image depuis la caméra")
                    self.cap.release()
                    self.cap = None
                    return False
                    
                print(f"Capture démarrée avec succès - Dimensions: {test_frame.shape}")
                
                self.current_source = source
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
        """Récupère une image de la caméra"""
        with self.lock:
            if not self.is_capturing or not self.cap:
                return None
            
            try:
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    return frame
                else:
                    # Si la lecture échoue, essayer de réinitialiser la caméra
                    print("Erreur de lecture de la caméra, tentative de réinitialisation...")
                    if self.current_source is not None and self.current_type is not None:
                        # Fermer et réouvrir la caméra
                        self.cap.release()
                        self.cap = cv2.VideoCapture(int(self.current_source) if self.current_type == 'usb' else self.current_source)
                        if self.cap.isOpened():
                            print("Caméra réinitialisée avec succès")
                            # Essayer de lire à nouveau
                            ret, frame = self.cap.read()
                            if ret and frame is not None and frame.size > 0:
                                return frame
                    return None
            except Exception as e:
                print(f"Exception lors de la lecture de la caméra: {e}")
                return None
    
    def is_active(self):
        """Vérifie si la capture est active"""
        return self.is_capturing
