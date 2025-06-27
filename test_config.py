#!/usr/bin/env python3
"""
Script de test de configuration pour IAction
Vérifie que tous les services requis sont disponibles
"""

import os
import sys
import requests
import cv2
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

def test_python_version():
    """Teste la version de Python"""
    print("[PYTHON] Test de la version Python...")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"   [OK] Python {version.major}.{version.minor}.{version.micro} - OK")
        return True
    else:
        print(f"   [ERREUR] Python {version.major}.{version.minor}.{version.micro} - Version trop ancienne (requis: 3.8+)")
        return False

def test_dependencies():
    """Teste les dépendances Python"""
    print("\n[DEPS] Test des dépendances Python...")
    dependencies = [
        ('flask', 'Flask'),
        ('cv2', 'OpenCV'),
        ('requests', 'Requests'),
        ('paho.mqtt.client', 'Paho MQTT'),
        ('dotenv', 'Python-dotenv'),
        ('PIL', 'Pillow'),
        ('numpy', 'NumPy')
    ]
    
    all_ok = True
    for module, name in dependencies:
        try:
            __import__(module)
            print(f"   [OK] {name} - OK")
        except ImportError:
            print(f"   [ERREUR] {name} - Non installé")
            all_ok = False
    
    return all_ok

def test_cameras():
    """Teste les caméras disponibles de manière optimisée"""
    print("\n[CAMERA] Test des caméras...")
    cameras_found = 0
    
    # Test rapide seulement sur les indices 0-2
    for i in range(3):
        try:
            # Utiliser DirectShow sur Windows pour une détection plus rapide
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if cap.isOpened():
                # Test rapide de lecture avec timeout
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"   [OK] Caméra USB {i} - Disponible")
                    cameras_found += 1
                cap.release()
        except Exception as e:
            # Ignorer les erreurs silencieusement pour accélérer
            continue
    
    if cameras_found > 0:
        print(f"   [INFO] {cameras_found} caméra(s) USB détectée(s)")
        return True
    else:
        print("   [WARN] Aucune caméra USB détectée (test rapide)")
        print("   [INFO] Vous pouvez toujours utiliser des flux RTSP")
        return False

def test_ollama():
    """Teste la connexion à Ollama"""
    print("\n[OLLAMA] Test de la connexion Ollama...")
    
    load_dotenv()
    ollama_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    model = os.getenv('OLLAMA_MODEL', 'llama3.2-vision:latest')
    
    try:
        # Test de connexion
        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if response.status_code == 200:
            print(f"   [OK] Ollama accessible sur {ollama_url}")
            
            # Vérifier les modèles
            data = response.json()
            models = [m['name'] for m in data.get('models', [])]
            
            if model in models:
                print(f"   [OK] Modèle {model} disponible")
                return True
            else:
                print(f"   [WARN] Modèle {model} non trouvé")
                print(f"   [INFO] Modèles disponibles: {', '.join(models) if models else 'Aucun'}")
                return False
        else:
            print(f"   [ERREUR] Erreur HTTP {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"   [ERREUR] Impossible de se connecter à {ollama_url}")
        print("   [INFO] Vérifiez qu'Ollama est démarré: ollama serve")
        return False
    except Exception as e:
        print(f"   [ERREUR] Erreur: {e}")
        return False

def test_mqtt():
    """Teste la connexion MQTT"""
    print("\n[MQTT] Test de la connexion MQTT...")
    
    load_dotenv()
    broker = os.getenv('MQTT_BROKER', 'localhost')
    port = int(os.getenv('MQTT_PORT', '1883'))
    username = os.getenv('MQTT_USERNAME', '')
    password = os.getenv('MQTT_PASSWORD', '')
    
    try:
        client = mqtt.Client()
        
        if username and password:
            client.username_pw_set(username, password)
        
        client.connect(broker, port, 10)
        client.disconnect()
        
        print(f"   [OK] MQTT accessible sur {broker}:{port}")
        return True
        
    except Exception as e:
        print(f"   [ERREUR] Impossible de se connecter à {broker}:{port}")
        print(f"   [INFO] Erreur: {e}")
        print("   [INFO] Vérifiez qu'un broker MQTT est démarré (ex: Mosquitto)")
        return False

def test_env_file():
    """Teste la présence du fichier .env"""
    print("\n[CONFIG] Test du fichier de configuration...")
    
    if os.path.exists('.env'):
        print("   [OK] Fichier .env trouvé")
        
        load_dotenv()
        required_vars = [
            'OLLAMA_BASE_URL',
            'OLLAMA_MODEL',
            'MQTT_BROKER',
            'MQTT_PORT'
        ]
        
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            print(f"   [WARN] Variables manquantes: {', '.join(missing_vars)}")
            return False
        else:
            print("   [OK] Configuration complète")
            return True
    else:
        print("   [ERREUR] Fichier .env non trouvé")
        print("   [INFO] Copiez .env.example vers .env et configurez-le")
        return False

def main():
    """Fonction principale"""
    print("[TEST] Configuration IAction")
    print("=" * 50)
    
    tests = [
        ("Version Python", test_python_version),
        ("Dépendances", test_dependencies),
        ("Configuration", test_env_file),
        ("Caméras", test_cameras),
        ("Ollama", test_ollama),
        ("MQTT", test_mqtt)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"   [ERREUR] Erreur lors du test {name}: {e}")
            results.append((name, False))
    
    # Résumé
    print("\n" + "=" * 50)
    print("[RESUME] RÉSUMÉ DES TESTS")
    print("=" * 50)
    
    passed = 0
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")
        if result:
            passed += 1
    
    print(f"\n[SCORE] {passed}/{len(results)} tests réussis")
    
    if passed == len(results):
        print("\n[SUCCESS] Configuration parfaite ! Vous pouvez démarrer IAction.")
    elif passed >= len(results) - 2:
        print("\n[WARN] Configuration presque prête. Vérifiez les services optionnels.")
    else:
        print("\n[ERROR] Configuration incomplète. Veuillez corriger les erreurs.")
    
    return passed == len(results)

if __name__ == "__main__":
    success = main()
    input("\nAppuyez sur Entrée pour continuer...")
    sys.exit(0 if success else 1)
