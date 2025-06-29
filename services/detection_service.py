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
            self.mqtt_service.buffer_binary_sensor_state(sensor_id, False)
            self.mqtt_service.flush_message_buffer()
            
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
    
    def analyze_frame(self, image_base64: str) -> dict:
        """Analyse une image avec toutes les détections configurées
        
        Returns:
            dict: Résultats de l'analyse avec les clés 'people_count', 'detections'
        """
        results = {
            'people_count': None,
            'detections': [],
            'success': True,
            'timestamp': time.time()
        }
        
        try:
            # Récupérer la liste des détections personnalisées
            with self.lock:
                detections_list = [{
                    'id': detection_id,
                    'phrase': detection['phrase'],
                    'name': detection['name']
                } for detection_id, detection in self.detections.items()]
            
            # Utiliser la méthode d'analyse combinée pour tout analyser en un seul appel
            combined_results = self.ai_service.analyze_combined(image_base64, detections_list)
            
            if combined_results['success']:
                # Mettre à jour le nombre de personnes
                if 'people_count' in combined_results and combined_results['people_count']['success']:
                    results['people_count'] = combined_results['people_count']['count']
                    self.mqtt_service.buffer_sensor_value('people_count', results['people_count'])
                
                # Traiter les résultats des détections personnalisées
                if 'detections' in combined_results:
                    detection_results = []
                    for detection_result in combined_results['detections']:
                        detection_id = detection_result['id']
                        is_match = detection_result['match']
                        
                        # Mettre à jour l'état du binary sensor si nécessaire
                        if detection_id in self.detections:
                            sensor_id = f"detection_{detection_id.replace('-', '_')}"
                            
                            # Ne publier que si l'état a changé
                            if detection_id not in self.binary_sensor_states or self.binary_sensor_states[detection_id] != is_match:
                                self.binary_sensor_states[detection_id] = is_match
                                self.mqtt_service.buffer_binary_sensor_state(sensor_id, is_match)
                            
                            # Mettre à jour les statistiques de la détection
                            if is_match:
                                with self.lock:
                                    if detection_id in self.detections:
                                        self.detections[detection_id]['last_triggered'] = time.time()
                                        self.detections[detection_id]['trigger_count'] += 1
                            
                            # Ajouter aux résultats
                            detection_results.append({
                                'id': detection_id,
                                'name': self.detections[detection_id]['name'],
                                'match': is_match,
                                'success': True
                            })
                    
                    results['detections'] = detection_results
            else:
                # En cas d'erreur dans l'analyse combinée
                results['success'] = False
                results['error'] = combined_results.get('error', 'Erreur inconnue dans l\'analyse combinée')
            
            # Sauvegarder les résultats pour référence
            self.last_analysis_results = results.copy()
            
            # Envoyer tous les messages MQTT en une seule fois
            self.mqtt_service.flush_message_buffer()
            
            return results
            
        except Exception as e:
            print(f"Erreur lors de l'analyse de l'image: {e}")
            results['success'] = False
            results['error'] = str(e)
            return results
    
    # Les méthodes _analyze_fixed_sensors et _analyze_custom_detections ont été supprimées
    # car elles sont remplacées par l'utilisation de la méthode analyze_combined du service AI
    
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
