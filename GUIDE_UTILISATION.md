# Guide d'Utilisation - IAction

## 🚀 Démarrage Rapide

### 1. Vérification de la Configuration
```bash
# Test complet (plus lent)
python test_config.py


### 2. Démarrage de l'Application
```bash
# Méthode 1: Script automatique
start.bat

# Méthode 2: Commande directe
python app.py
```

### 3. Accès à l'Interface
Ouvrez votre navigateur sur : `http://localhost:5000`

## 📋 Prérequis

### Services Requis
1. **Ollama** avec un modèle vision installé
2. **Broker MQTT** (optionnel pour Home Assistant)

### Installation d'Ollama
```bash
# Téléchargez depuis https://ollama.ai
# Puis installez un modèle vision :
ollama pull llama3.2-vision:latest
# ou
ollama pull gemma2:latest
```

### Installation Mosquitto (MQTT)
```bash
# Windows: Téléchargez depuis https://mosquitto.org/download/
# Ou utilisez Docker:
docker run -it -p 1883:1883 eclipse-mosquitto
```

## ⚙️ Configuration

### Fichier .env
Modifiez le fichier `.env` avec vos paramètres :

```env
# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2-vision:latest

# MQTT (pour Home Assistant)
MQTT_BROKER=192.168.1.100
MQTT_PORT=1883
MQTT_USERNAME=homeassistant
MQTT_PASSWORD=votre_mot_de_passe

# Home Assistant
HA_DEVICE_NAME=IAction Camera AI
HA_DEVICE_ID=iaction_camera_ai
```

## 🎯 Utilisation

### Configuration d'une Caméra

#### Caméra USB
1. Connectez votre caméra USB
2. Dans l'interface, sélectionnez "Caméra USB X"
3. Cliquez "Démarrer la capture"

#### Caméra IP (RTSP)
1. Sélectionnez "Caméra RTSP (URL personnalisée)"
2. Saisissez l'URL : `rtsp://user:pass@192.168.1.100:554/stream1`
3. Cliquez "Démarrer la capture"

### Détections Personnalisées

#### Ajouter une Détection
1. Cliquez sur "Ajouter" dans la section "Détections Personnalisées"
2. Saisissez un nom descriptif
3. Décrivez précisément ce que l'IA doit détecter

#### Exemples de Détections
- **Nom** : Personne avec téléphone
- **Phrase** : une personne qui tient un téléphone portable

- **Nom** : Véhicule en mouvement
- **Phrase** : une voiture ou un camion qui roule

- **Nom** : Animal domestique
- **Phrase** : un chien ou un chat

### Capteurs Automatiques

L'application génère automatiquement :
- **Compteur de personnes** : Nombre de personnes visibles
- **Description de scène** : Description de ce qui se passe

## 🏠 Intégration Home Assistant

### Configuration MQTT
1. Activez MQTT dans Home Assistant
2. Configurez le broker dans `.env`
3. Les capteurs apparaîtront automatiquement

### Capteurs Disponibles
- `sensor.iaction_camera_ai_people_count`
- `sensor.iaction_camera_ai_scene_description`
- `binary_sensor.iaction_camera_ai_detection_[nom]`

### Automatisations Exemple
```yaml
# Notification si plus de 3 personnes
automation:
  - alias: "Trop de monde"
    trigger:
      platform: numeric_state
      entity_id: sensor.iaction_camera_ai_people_count
      above: 3
    action:
      service: notify.mobile_app
      data:
        message: "Plus de 3 personnes détectées !"

# Action sur détection personnalisée
  - alias: "Détection personnalisée"
    trigger:
      platform: state
      entity_id: binary_sensor.iaction_camera_ai_detection_xxxxx
      to: 'on'
    action:
      service: light.turn_on
      entity_id: light.salon
```

## 🔧 Dépannage

### Problèmes Courants

#### "Aucune caméra détectée"
- Vérifiez que la caméra est connectée
- Testez avec une autre application (VLC, etc.)
- Redémarrez l'application


#### "Erreur Ollama"
```bash
# Vérifiez qu'Ollama fonctionne
ollama serve

# Testez la connexion
curl http://localhost:11434/api/tags

# Installez un modèle si nécessaire
ollama pull llama3.2-vision:latest
```

#### "Erreur MQTT"
- Vérifiez que le broker MQTT est démarré
- Testez la connexion :
```bash
mosquitto_pub -h localhost -t test -m "hello"
mosquitto_sub -h localhost -t test
```

#### "Analyse IA lente"
- Utilisez un modèle plus léger (gemma2 au lieu de llama3.2-vision)
- Réduisez la résolution de la caméra
- Vérifiez les ressources système (CPU/RAM)

### Logs et Debug
- Les logs s'affichent dans la console Python
- L'interface web montre l'activité en temps réel
- Utilisez `test_config.py` pour diagnostiquer

## 📊 Performance

### Ressources Recommandées
- **CPU** : 4 cœurs minimum
- **RAM** : 8 GB minimum (16 GB recommandé)
- **GPU** : Optionnel mais améliore les performances

### Optimisation
- Utilisez des modèles Ollama optimisés
- Limitez le nombre de détections simultanées
- Ajustez la résolution vidéo selon vos besoins

## 🔒 Sécurité

### Bonnes Pratiques
- Changez les mots de passe par défaut
- Utilisez HTTPS en production
- Limitez l'accès réseau si nécessaire
- Sauvegardez régulièrement vos configurations

### Données Privées
- Les images sont analysées localement
- Aucune donnée n'est envoyée vers des services externes
- Ollama fonctionne entièrement en local

## 📞 Support

### Fichiers de Log
- Console Python pour les erreurs système
- Interface web pour l'activité utilisateur
- Logs MQTT dans Home Assistant

### Informations Utiles
- Version Python : `python --version`
- Modèles Ollama : `ollama list`
- État des services : `python test_config.py`

---

**IAction** - Analyse Vidéo IA pour Home Assistant
Version 1.0 - Développé avec ❤️
