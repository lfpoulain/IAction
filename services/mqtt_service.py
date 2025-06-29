import os
import json
import paho.mqtt.client as mqtt
import time
import sys
import os
import time
import atexit
from typing import Dict, Any

# Variable globale pour stocker l'instance unique du service MQTT
_mqtt_instance = None

# Méthode pour obtenir l'instance unique du service MQTT
def get_mqtt_instance():
    global _mqtt_instance
    if _mqtt_instance is None:
        _mqtt_instance = MQTTService()
    return _mqtt_instance

class MQTTService:
    def __init__(self):
        # Vérifier si c'est la première instance
        global _mqtt_instance
        if _mqtt_instance is not None:
            print("ATTENTION: Une nouvelle instance de MQTTService a été créée alors qu'une existe déjà!")
            # Fermer l'ancienne instance proprement
            _mqtt_instance.disconnect()
        
        # Enregistrer cette instance comme l'instance globale
        _mqtt_instance = self
        
        # S'assurer que la déconnexion est appelée à la fermeture du programme
        atexit.register(self.disconnect)
        
        # Recharger explicitement les variables d'environnement
        from dotenv import load_dotenv
        load_dotenv(override=True)
        
        self.broker = os.getenv('MQTT_BROKER', 'localhost')
        self.port = int(os.getenv('MQTT_PORT', '1883'))
        self.username = os.getenv('MQTT_USERNAME', '')
        self.password = os.getenv('MQTT_PASSWORD', '')
        self.topic_prefix = os.getenv('MQTT_TOPIC_PREFIX', 'iaction')
        
        self.device_name = os.getenv('HA_DEVICE_NAME', 'IAction Camera AI')
        self.device_id = os.getenv('HA_DEVICE_ID', 'iaction_camera_ai')
        
        # Afficher les valeurs exactes lues du fichier .env
        print("=== Configuration MQTT chargée ===")
        print(f"Broker: '{self.broker}'")
        print(f"Port: {self.port}")
        print(f"Username: '{self.username}'")
        print(f"Password: '{'*' * len(self.password) if self.password else 'Non défini'}'")
        print(f"Topic prefix: '{self.topic_prefix}'")
        print("=================================")
        
        # Utiliser un ID client fixe pour éviter les connexions multiples
        self.client_id = f"iaction_client_{self.device_id}"
        self.client = None
        self.is_connected = False
        self.published_sensors = set()
        self.message_buffer = {}
        self.last_publish_time = 0
        self.publish_interval = 1.0  # Intervalle minimum entre les publications en secondes
    
    def connect(self):
        """Se connecte au broker MQTT avec reconnexion automatique"""
        # Si déjà connecté, ne rien faire
        if self.client and self.is_connected:
            print("Déjà connecté au broker MQTT")
            return True
            
        try:
            # Utiliser l'ID client fixe pour éviter les connexions multiples
            print(f"Utilisation de l'ID client MQTT fixe: {self.client_id}")
            self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311, clean_session=False)
            
            # Configuration des callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_publish = self._on_publish
            
            # Activer la reconnexion automatique
            self.client.reconnect_delay_set(min_delay=1, max_delay=120)
            
            # Authentification si nécessaire
            if self.username and self.password:
                print(f"Configuration de l'authentification MQTT avec l'utilisateur: '{self.username}'")
                try:
                    self.client.username_pw_set(self.username, self.password)
                    print("Authentification configurée")
                except Exception as e:
                    print(f"Erreur lors de la configuration de l'authentification: {e}")
            
            # Connexion avec plus de détails en cas d'erreur
            print(f"Tentative de connexion à {self.broker}:{self.port}...")
            try:
                self.client.connect_async(self.broker, self.port, keepalive=60)
                print("Connexion asynchrone initialisée, démarrage de la boucle...")
                self.client.loop_start()
            except Exception as e:
                print(f"Exception lors de la connexion MQTT: {str(e)}")
                return False
            
            return True
            
        except Exception as e:
            print(f"Erreur de connexion MQTT: {e}")
            return False
    
    def disconnect(self):
        """Se déconnecte du broker MQTT"""
        if self.client:
            try:
                # Arrêter la boucle d'abord
                self.client.loop_stop()
                # Puis se déconnecter proprement
                if self.is_connected:
                    self.client.disconnect()
                    print("Déconnexion propre du broker MQTT")
            except Exception as e:
                print(f"Erreur lors de la déconnexion MQTT: {e}")
            finally:
                self.is_connected = False
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback de connexion"""
        if rc == 0:
            self.is_connected = True
            print("Connecté au broker MQTT")
            
            # Vérifier si c'est une reconnexion ou une première connexion
            if not hasattr(self, '_initial_setup_done') or not self._initial_setup_done:
                print("Configuration initiale des capteurs fixes...")
                self._setup_fixed_sensors()
                self._initial_setup_done = True
            else:
                print("Reconnexion MQTT - capteurs déjà configurés")
        else:
            error_messages = {
                1: "Protocole incorrect",
                2: "ID client rejeté",
                3: "Serveur indisponible",
                4: "Identifiants incorrects",
                5: "Non autorisé - Vérifiez vos identifiants MQTT"
            }
            error_msg = error_messages.get(rc, f"Erreur inconnue: {rc}")
            print(f"Échec de connexion MQTT, code: {rc} - {error_msg}")
            print(f"Tentative de connexion à {self.broker}:{self.port} avec utilisateur '{self.username}'")
            print(f"Flags de connexion: {flags}")
            # Essayer de se reconnecter avec un délai
            if not self.is_connected:
                print("Nouvelle tentative de connexion dans 5 secondes...")
                time.sleep(5)
                try:
                    self.connect()
                except Exception as e:
                    print(f"Erreur lors de la tentative de reconnexion: {e}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback de déconnexion"""
        self.is_connected = False
        print("Déconnecté du broker MQTT")
    
    def _on_publish(self, client, userdata, mid):
        """Callback de publication"""
        pass
    
    def _setup_fixed_sensors(self):
        """Configure les capteurs fixes obligatoires"""
        # Capteur nombre de personnes
        self.setup_sensor(
            sensor_id="people_count",
            name="Nombre de personnes",
            device_class="",
            unit_of_measurement="personnes",
            icon="mdi:account-group"
        )
        
    def setup_sensor(self, sensor_id: str, name: str, device_class: str = "", 
                    unit_of_measurement: str = "", icon: str = "mdi:camera"):
        """Configure un capteur avec autodiscovery Home Assistant"""
        if not self.is_connected:
            return False
        
        config_topic = f"homeassistant/sensor/{self.device_id}_{sensor_id}/config"
        state_topic = f"{self.topic_prefix}/sensor/{sensor_id}/state"
        
        config_payload = {
            "name": name,
            "unique_id": f"{self.device_id}_{sensor_id}",
            "state_topic": state_topic,
            "icon": icon,
            "device": {
                "identifiers": [self.device_id],
                "name": self.device_name,
                "manufacturer": "IAction",
                "model": "Camera AI Analyzer",
                "sw_version": "1.0.0"
            }
        }
        
        if device_class:
            config_payload["device_class"] = device_class
        
        if unit_of_measurement:
            config_payload["unit_of_measurement"] = unit_of_measurement
        
        try:
            self.client.publish(config_topic, json.dumps(config_payload), retain=True)
            self.published_sensors.add(sensor_id)
            print(f"Capteur configuré: {name}")
            return True
        except Exception as e:
            print(f"Erreur lors de la configuration du capteur {sensor_id}: {e}")
            return False
    
    def setup_binary_sensor(self, sensor_id: str, name: str, device_class: str = "motion"):
        """Configure un binary sensor avec autodiscovery Home Assistant"""
        if not self.is_connected:
            return False
        
        config_topic = f"homeassistant/binary_sensor/{self.device_id}_{sensor_id}/config"
        state_topic = f"{self.topic_prefix}/binary_sensor/{sensor_id}/state"
        
        config_payload = {
            "name": name,
            "unique_id": f"{self.device_id}_{sensor_id}",
            "state_topic": state_topic,
            "device_class": device_class,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": {
                "identifiers": [self.device_id],
                "name": self.device_name,
                "manufacturer": "IAction",
                "model": "Camera AI Analyzer",
                "sw_version": "1.0.0"
            }
        }
        
        try:
            self.client.publish(config_topic, json.dumps(config_payload), retain=True)
            self.published_sensors.add(sensor_id)
            print(f"Binary sensor configuré: {name}")
            return True
        except Exception as e:
            print(f"Erreur lors de la configuration du binary sensor {sensor_id}: {e}")
            return False
    
    def buffer_sensor_value(self, sensor_id: str, value: Any):
        """Ajoute une valeur de capteur au buffer pour publication groupée"""
        state_topic = f"{self.topic_prefix}/sensor/{sensor_id}/state"
        self.message_buffer[state_topic] = str(value)
        return True
    
    def buffer_binary_sensor_state(self, sensor_id: str, state: bool):
        """Ajoute l'état d'un binary sensor au buffer pour publication groupée"""
        state_topic = f"{self.topic_prefix}/binary_sensor/{sensor_id}/state"
        payload = "ON" if state else "OFF"
        self.message_buffer[state_topic] = payload
        return True
        
    def flush_message_buffer(self):
        """Publie tous les messages en attente dans le buffer"""
        if not self.is_connected or not self.message_buffer:
            return False
            
        # Vérifier si assez de temps s'est écoulé depuis la dernière publication
        current_time = time.time()
        if current_time - self.last_publish_time < self.publish_interval:
            return False
            
        success = True
        try:
            # Publier tous les messages en une seule connexion
            for topic, payload in self.message_buffer.items():
                self.client.publish(topic, payload)
            self.last_publish_time = current_time
            self.message_buffer.clear()
        except Exception as e:
            print(f"Erreur lors de la publication groupée: {e}")
            success = False
            
        return success
    
    def publish_sensor_value(self, sensor_id: str, value: Any):
        """Publie une valeur de capteur (méthode de compatibilité)"""
        if not self.is_connected:
            return False
        
        state_topic = f"{self.topic_prefix}/sensor/{sensor_id}/state"
        
        try:
            self.client.publish(state_topic, str(value))
            return True
        except Exception as e:
            print(f"Erreur lors de la publication du capteur {sensor_id}: {e}")
            return False
    
    def publish_binary_sensor_state(self, sensor_id: str, state: bool):
        """Publie l'état d'un binary sensor (méthode de compatibilité)"""
        if not self.is_connected:
            return False
        
        state_topic = f"{self.topic_prefix}/binary_sensor/{sensor_id}/state"
        payload = "ON" if state else "OFF"
        
        try:
            self.client.publish(state_topic, payload)
            return True
        except Exception as e:
            print(f"Erreur lors de la publication du binary sensor {sensor_id}: {e}")
            return False
            
    def publish_status(self, status_data: Dict[str, Any]):
        """Publie les informations de statut de l'analyse
        
        Args:
            status_data: Dictionnaire contenant les informations de statut
                - last_analysis_time: Timestamp de la dernière analyse
                - last_analysis_duration: Durée de la dernière analyse en secondes
                - analysis_result: Résultats de l'analyse
        """
        if not self.is_connected:
            return False
            
        # Publier le timestamp de la dernière analyse
        if 'last_analysis_time' in status_data:
            self.publish_sensor_value('last_analysis_time', status_data['last_analysis_time'])
            
        # Publier la durée de la dernière analyse
        if 'last_analysis_duration' in status_data:
            duration = status_data['last_analysis_duration']
            self.publish_sensor_value('last_analysis_duration', f"{duration:.2f}")
            
        # Publier un JSON avec toutes les informations de statut
        try:
            status_topic = f"{self.topic_prefix}/status"
            status_json = json.dumps(status_data)
            self.client.publish(status_topic, status_json)
            return True
        except Exception as e:
            print(f"Erreur lors de la publication du statut: {e}")
            return False
    
    def remove_sensor(self, sensor_id: str, sensor_type: str = "sensor"):
        """Supprime un capteur de Home Assistant"""
        if not self.is_connected:
            return False
        
        config_topic = f"homeassistant/{sensor_type}/{self.device_id}_{sensor_id}/config"
        
        try:
            # Publier un payload vide pour supprimer le capteur
            self.client.publish(config_topic, "", retain=True)
            if sensor_id in self.published_sensors:
                self.published_sensors.remove(sensor_id)
            return True
        except Exception as e:
            print(f"Erreur lors de la suppression du capteur {sensor_id}: {e}")
            return False
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Retourne le statut de la connexion MQTT"""
        return {
            'connected': self.is_connected,
            'broker': self.broker,
            'port': self.port,
            'topic_prefix': self.topic_prefix,
            'published_sensors': list(self.published_sensors)
        }
