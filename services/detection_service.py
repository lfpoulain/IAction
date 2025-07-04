import uuid
import time
import threading
import json
import os
import requests
import asyncio
from typing import Dict, List, Any, Optional

class DetectionService:
    def __init__(self, ai_service, mqtt_service):
        self.ai_service = ai_service
        self.mqtt_service = mqtt_service
        self.detections = {}
        self.lock = threading.Lock()
        self.detections_file = 'detections.json'
        
        # États des binary sensors pour éviter les publications répétées
        self.binary_sensor_states = {}
        self.last_analysis_results = {}
        
        # Gestion de l'intervalle minimum entre analyses
        self.last_analysis_time = 0
        self.min_analysis_interval = float(os.getenv('MIN_ANALYSIS_INTERVAL', '0.1'))
        
        # Charger les détections sauvegardées
        self.load_detections()
    
    def add_detection(self, name: str, phrase: str, webhook_url: Optional[str] = None) -> str:
        """Ajoute une nouvelle détection personnalisée avec webhook optionnel"""
        with self.lock:
            detection_id = str(uuid.uuid4())
            
            self.detections[detection_id] = {
                'id': detection_id,
                'name': name,
                'phrase': phrase,
                'webhook_url': webhook_url,
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
            
            # Sauvegarder les détections
            self.save_detections()
            
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
            
            # Sauvegarder les détections
            self.save_detections()
            
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
        current_time = time.time()
        
        # Vérifier l'intervalle minimum entre analyses
        if current_time - self.last_analysis_time < self.min_analysis_interval:
            # Retourner les derniers résultats si l'intervalle n'est pas respecté
            if self.last_analysis_results:
                return self.last_analysis_results
            else:
                return {
                    'people_count': 0,
                    'detections': [],
                    'success': True,
                    'timestamp': current_time,
                    'skipped': True  # Indicateur que l'analyse a été ignorée
                }
        
        results = {
            'people_count': None,
            'detections': [],
            'success': True,
            'timestamp': current_time
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
                                        current_time = time.time()
                                        self.detections[detection_id]['last_triggered'] = current_time
                                        self.detections[detection_id]['trigger_count'] += 1
                                        
                                        # Appeler le webhook si configuré
                                        webhook_url = self.detections[detection_id].get('webhook_url')
                                        if webhook_url:
                                            self.call_webhook(
                                                detection_id=detection_id,
                                                detection_name=self.detections[detection_id]['name'],
                                                webhook_url=webhook_url,
                                                is_match=is_match,
                                                timestamp=current_time
                                            )
                            
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
            
            # Mettre à jour le timestamp de la dernière analyse
            self.last_analysis_time = current_time
            
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
    
    def save_detections(self):
        """Sauvegarde les détections dans un fichier JSON"""
        try:
            # Préparer les données pour la sérialisation
            detections_data = {}
            for detection_id, detection in self.detections.items():
                detections_data[detection_id] = {
                    'id': detection['id'],
                    'name': detection['name'],
                    'phrase': detection['phrase'],
                    'created_at': detection['created_at'],
                    'last_triggered': detection['last_triggered'],
                    'trigger_count': detection['trigger_count']
                }
            
            with open(self.detections_file, 'w', encoding='utf-8') as f:
                json.dump(detections_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Détections sauvegardées: {len(detections_data)} détections")
            
        except Exception as e:
            print(f"⚠️ Erreur lors de la sauvegarde des détections: {e}")
    
    def load_detections(self):
        """Charge les détections depuis le fichier JSON"""
        try:
            if not os.path.exists(self.detections_file):
                print("📁 Aucun fichier de détections trouvé, démarrage avec une liste vide")
                return
            
            with open(self.detections_file, 'r', encoding='utf-8') as f:
                detections_data = json.load(f)
            
            # Restaurer les détections
            for detection_id, detection in detections_data.items():
                self.detections[detection_id] = detection
                
                # Configurer le binary sensor MQTT
                sensor_id = f"detection_{detection_id.replace('-', '_')}"
                self.mqtt_service.setup_binary_sensor(
                    sensor_id=sensor_id,
                    name=f"Détection: {detection['name']}",
                    device_class="motion"
                )
                
                # Initialiser l'état du binary sensor
                self.binary_sensor_states[detection_id] = False
                self.mqtt_service.buffer_binary_sensor_state(sensor_id, False)
            
            if detections_data:
                self.mqtt_service.flush_message_buffer()
            
            print(f"✅ Détections chargées: {len(detections_data)} détections")
            
        except Exception as e:
            print(f"⚠️ Erreur lors du chargement des détections: {e}")
            print("📁 Démarrage avec une liste vide")
    
    def call_webhook(self, detection_id: str, detection_name: str, webhook_url: str, is_match: bool, timestamp: float):
        """Appelle un webhook de manière asynchrone"""
        try:
            # Préparer les données du webhook
            webhook_data = {
                'detection_id': detection_id,
                'detection_name': detection_name,
                'triggered': is_match,
                'timestamp': timestamp,
                'timestamp_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(timestamp)),
                'source': 'IAction',
                'device_id': 'iaction_camera_ai'
            }
            
            # Appeler le webhook en arrière-plan
            def make_webhook_call():
                try:
                    response = requests.post(
                        webhook_url,
                        json=webhook_data,
                        timeout=5,
                        headers={'Content-Type': 'application/json'}
                    )
                    if response.status_code == 200:
                        print(f"🔗 Webhook appelé avec succès pour '{detection_name}': {webhook_url}")
                    else:
                        print(f"⚠️ Webhook échoué pour '{detection_name}' (HTTP {response.status_code}): {webhook_url}")
                except requests.exceptions.Timeout:
                    print(f"⏱️ Timeout webhook pour '{detection_name}': {webhook_url}")
                except requests.exceptions.RequestException as e:
                    print(f"❌ Erreur webhook pour '{detection_name}': {e}")
            
            # Lancer l'appel en arrière-plan pour ne pas bloquer
            threading.Thread(target=make_webhook_call, daemon=True).start()
            
        except Exception as e:
            print(f"❌ Erreur lors de la préparation du webhook pour '{detection_name}': {e}")
