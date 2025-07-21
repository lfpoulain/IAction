#!/usr/bin/env python3
"""
Utilitaire pour tester et configurer les caméras RTSP.
Facilite la sélection de la bonne caméra sur Linux.
"""

import cv2
import sys
import os
import time
import argparse
from pathlib import Path

# Ajouter le répertoire parent au path pour importer les services
sys.path.append(str(Path(__file__).parent.parent))

from services.camera_service import CameraService

def test_rtsp_url(url, username=None, password=None):
    """Teste une URL RTSP"""
    print(f"🔍 Test de l'URL RTSP: {url[:50]}...")
    
    camera_service = CameraService()
    
    # Construire l'URL avec authentification si nécessaire
    test_url = url
    if username and password and '@' not in url:
        # Ajouter les credentials à l'URL
        test_url = camera_service.build_rtsp_url(
            url.replace('rtsp://', '').split('/')[0].split(':')[0],
            port=554,
            username=username,
            password=password,
            path='/' + '/'.join(url.replace('rtsp://', '').split('/')[1:]) if '/' in url else '/'
        )
    
    # Validation de l'URL
    is_valid, message = camera_service.validate_rtsp_url(test_url)
    if not is_valid:
        print(f"❌ URL invalide: {message}")
        return False
    
    # Test de connexion
    status = camera_service._test_rtsp_connection(test_url)
    
    if status == 'online':
        print("✅ Connexion RTSP réussie")
        
        # Test de capture
        if camera_service.start_capture(test_url, 'rtsp'):
            frame = camera_service.get_frame()
            if frame is not None:
                print(f"✅ Test de capture réussi - {frame.shape}")
                return True
            else:
                print("❌ Erreur lors du test de capture")
            camera_service.stop_capture()
        else:
            print("❌ Impossible de démarrer la capture")
    
    elif status == 'offline':
        print("❌ Caméra RTSP hors ligne ou inaccessible")
    elif status == 'error':
        print("❌ Erreur lors de la connexion RTSP")
    else:
        print(f"❌ Statut inconnu: {status}")
    
    return False

def interactive_camera_selection():
    """Interface interactive pour sélectionner une caméra"""
    print("🎥 Sélection interactive de caméra")
    print("=" * 40)
    
    camera_service = CameraService()
    cameras = camera_service.get_available_cameras()
    
    if not cameras:
        print("❌ Aucune caméra trouvée")
        return
    
    print("Caméras disponibles:")
    for i, camera in enumerate(cameras):
        status = ""
        if camera['type'] == 'rtsp' and 'test_status' in camera:
            status_icons = {
                'online': '🟢',
                'offline': '🔴',
                'error': '🟡',
                'not_configured': '⚪'
            }
            status = f" {status_icons.get(camera['test_status'], '❓')}"
        
        print(f"{i + 1}. {camera['name']}{status}")
        if camera['type'] == 'rtsp' and 'description' in camera:
            print(f"   {camera['description']}")
    
    while True:
        try:
            choice = input("\nChoisissez une caméra (numéro) ou 'q' pour quitter: ")
            if choice.lower() == 'q':
                break
            
            choice = int(choice) - 1
            if 0 <= choice < len(cameras):
                selected_camera = cameras[choice]
                print(f"\n📹 Caméra sélectionnée: {selected_camera['name']}")
                
                if selected_camera['type'] == 'rtsp' and selected_camera['id'] == 'rtsp_custom':
                    # Demander l'URL RTSP
                    url = input("Entrez l'URL RTSP: ")
                    username = input("Nom d'utilisateur (optionnel): ")
                    password = input("Mot de passe (optionnel): ")
                    
                    if test_rtsp_url(url, username, password):
                        print("✅ Configuration RTSP valide!")
                    
                else:
                    # Tester la caméra sélectionnée
                    if camera_service.start_capture(selected_camera['id'], 'rtsp'):
                        print("✅ Caméra prête!")

                        show_preview = input("Afficher un aperçu? (o/N): ")
                        if show_preview.lower() == 'o':
                            show_camera_preview(camera_service)

                        camera_service.stop_capture()
                
                break
            else:
                print("❌ Choix invalide")
        
        except (ValueError, KeyboardInterrupt):
            print("\n👋 Au revoir!")
            break

def show_camera_preview(camera_service, duration=10):
    """Affiche un aperçu de la caméra pendant quelques secondes"""
    print(f"📺 Aperçu de {duration} secondes... (Appuyez sur 'q' pour quitter)")
    
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            frame = camera_service.get_frame()
            if frame is not None:
                # Redimensionner pour l'affichage
                height, width = frame.shape[:2]
                if width > 800:
                    scale = 800 / width
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    frame = cv2.resize(frame, (new_width, new_height))
                
                cv2.imshow('Camera Preview', frame)
                
                # Vérifier si l'utilisateur appuie sur 'q'
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print("❌ Impossible de lire l'image")
                break
        
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()

def main():
    parser = argparse.ArgumentParser(description="Testeur de caméras pour IAction")
    parser.add_argument('--rtsp', type=str, help='Tester une URL RTSP')
    parser.add_argument('--username', type=str, help='Nom d\'utilisateur RTSP')
    parser.add_argument('--password', type=str, help='Mot de passe RTSP')
    parser.add_argument('--interactive', action='store_true', help='Mode interactif')
    
    args = parser.parse_args()
    
    if args.rtsp:
        test_rtsp_url(args.rtsp, args.username, args.password)
    elif args.interactive:
        interactive_camera_selection()
    else:
        # Mode interactif par défaut
        interactive_camera_selection()

if __name__ == "__main__":
    main()
