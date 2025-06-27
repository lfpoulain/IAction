import paho.mqtt.client as mqtt
import json
import os
import time
from typing import Dict, Any

class MQTTService:
    def __init__(self):
        self.broker = os.getenv('MQTT_BROKER', 'localhost')
        self.port = int(os.getenv('MQTT_PORT', '1883'))
        self.username = os.getenv('MQTT_USERNAME', '')
        self.password = os.getenv('MQTT_PASSWORD', '')
        self.topic_prefix = os.getenv('MQTT_TOPIC_PREFIX', 'iaction')
        
        self.device_name = os.getenv('HA_DEVICE_NAME', 'IAction Camera AI')
        self.device_id = os.getenv('HA_DEVICE_ID', 'iaction_camera_ai')
        
        self.client = None
        self.is_connected = False
        self.published_sensors = set()
    
    def connect(self):
        """Se connecte au broker MQTT"""
        try:
            self.client = mqtt.Client()
            
            # Configuration des callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_publish = self._on_publish
            
            # Authentification si nécessaire
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            
            # Connexion
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            
            return True
            
        except Exception as e:
            print(f"Erreur de connexion MQTT: {e}")
            return False
    
    def disconnect(self):
        """Se déconnecte du broker MQTT"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.is_connected = False
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback de connexion"""
        if rc == 0:
            self.is_connected = True
            print("Connecté au broker MQTT")
            self._setup_fixed_sensors()
        else:
            print(f"Échec de connexion MQTT, code: {rc}")
    
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
        
        # Capteur description de scène
        self.setup_sensor(
            sensor_id="scene_description",
            name="Description de la scène",
            device_class="",
            unit_of_measurement="",
            icon="mdi:eye"
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
    
    def publish_sensor_value(self, sensor_id: str, value: Any):
        """Publie une valeur de capteur"""
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
        """Publie l'état d'un binary sensor"""
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
