import uuid
import time
import threading
from typing import Dict, List, Any

class DetectionService:
    def __init__(self, ai_service, mqtt_service):
        self.ai_service = ai_service
        self.mqtt_service = mqtt_service
        self.detections = {}
        self.lock = threading.Lock()
        
        # États des binary sensors pour éviter les publications répétées
        self.binary_sensor_states = {}
        self.last_analysis_results = {}
    
    def add_detection(self, name: str, phrase: str) -> str:
        """Ajoute une nouvelle détection personnalisée"""
        with self.lock:
            detection_id = str(uuid.uuid4())
            
            self.detections[detection_id] = {
                'id': detection_id,
                'name': name,
                'phrase': phrase,
                'created_at': time.time(),
                'last_triggered': None,
                'trigger_count': 0
            }
            
            # Configurer le binary sensor MQTT
            sensor_id = f"detection_{detection_id.replace('-', '_')}"
            self.mqtt_service.setup_binary_sensor(
                sensor_id=sensor_id,
                name=f"Détection: {name}",
                device_class="motion"
            )
            
            # Initialiser l'état du binary sensor
            self.binary_sensor_states[detection_id] = False
            self.mqtt_service.publish_binary_sensor_state(sensor_id, False)
            
            return detection_id
    
    def remove_detection(self, detection_id: str) -> bool:
        """Supprime une détection"""
        with self.lock:
            if detection_id not in self.detections:
                return False
            
            # Supprimer le binary sensor MQTT
            sensor_id = f"detection_{detection_id.replace('-', '_')}"
            self.mqtt_service.remove_sensor(sensor_id, "binary_sensor")
            
            # Supprimer de nos structures
            del self.detections[detection_id]
            if detection_id in self.binary_sensor_states:
                del self.binary_sensor_states[detection_id]
            if detection_id in self.last_analysis_results:
                del self.last_analysis_results[detection_id]
            
            return True
    
    def get_detections(self) -> List[Dict[str, Any]]:
        """Récupère la liste des détections"""
        with self.lock:
            return list(self.detections.values())
    
    def analyze_frame(self, image_base64: str):
        """Analyse une image avec toutes les détections configurées"""
        try:
            # Analyser les capteurs fixes
            self._analyze_fixed_sensors(image_base64)
            
            # Analyser les détections personnalisées
            self._analyze_custom_detections(image_base64)
            
        except Exception as e:
            print(f"Erreur lors de l'analyse de l'image: {e}")
    
    def _analyze_fixed_sensors(self, image_base64: str):
        """Analyse les capteurs fixes (nombre de personnes, description)"""
        try:
            # Compter les personnes
            people_result = self.ai_service.count_people(image_base64)
            if people_result['success']:
                count = people_result['count']
                self.mqtt_service.publish_sensor_value('people_count', count)
                print(f"Nombre de personnes détectées: {count}")
            else:
                print(f"Erreur comptage personnes: {people_result['error']}")
            
            # Décrire la scène
            scene_result = self.ai_service.describe_scene(image_base64)
            if scene_result['success']:
                description = scene_result['response']
                self.mqtt_service.publish_sensor_value('scene_description', description)
                print(f"Description de la scène: {description}")
            else:
                print(f"Erreur description scène: {scene_result['error']}")
                
        except Exception as e:
            print(f"Erreur lors de l'analyse des capteurs fixes: {e}")
    
    def _analyze_custom_detections(self, image_base64: str):
        """Analyse les détections personnalisées"""
        with self.lock:
            detections_copy = dict(self.detections)
        
        for detection_id, detection in detections_copy.items():
            try:
                # Analyser avec l'IA
                result = self.ai_service.check_custom_detection(
                    image_base64, 
                    detection['phrase']
                )
                
                if result['success']:
                    is_match = result['match']
                    sensor_id = f"detection_{detection_id.replace('-', '_')}"
                    
                    # Mettre à jour l'état du binary sensor si nécessaire
                    current_state = self.binary_sensor_states.get(detection_id, False)
                    
                    if is_match != current_state:
                        self.binary_sensor_states[detection_id] = is_match
                        self.mqtt_service.publish_binary_sensor_state(sensor_id, is_match)
                        
                        if is_match:
                            # Mettre à jour les statistiques
                            with self.lock:
                                if detection_id in self.detections:
                                    self.detections[detection_id]['last_triggered'] = time.time()
                                    self.detections[detection_id]['trigger_count'] += 1
                            
                            print(f"Détection déclenchée: {detection['name']}")
                        else:
                            print(f"Détection arrêtée: {detection['name']}")
                    
                    # Sauvegarder le résultat pour le debug
                    self.last_analysis_results[detection_id] = {
                        'timestamp': time.time(),
                        'match': is_match,
                        'raw_response': result['raw_response']
                    }
                    
                else:
                    print(f"Erreur détection {detection['name']}: {result['error']}")
                    
            except Exception as e:
                print(f"Erreur lors de l'analyse de la détection {detection['name']}: {e}")
    
    def get_detection_status(self, detection_id: str) -> Dict[str, Any]:
        """Récupère le statut d'une détection"""
        with self.lock:
            if detection_id not in self.detections:
                return None
            
            detection = self.detections[detection_id].copy()
            detection['current_state'] = self.binary_sensor_states.get(detection_id, False)
            detection['last_analysis'] = self.last_analysis_results.get(detection_id)
            
            return detection
    
    def get_all_status(self) -> Dict[str, Any]:
        """Récupère le statut de toutes les détections"""
        with self.lock:
            status = {
                'total_detections': len(self.detections),
                'active_detections': sum(1 for state in self.binary_sensor_states.values() if state),
                'detections': []
            }
            
            for detection_id in self.detections:
                detection_status = self.get_detection_status(detection_id)
                if detection_status:
                    status['detections'].append(detection_status)
            
            return status
