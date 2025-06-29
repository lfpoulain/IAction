import json
import os
import re
import base64
from typing import Dict, Any, List
from openai import OpenAI

class AIService:
    def __init__(self):
        # Déterminer le mode API (OpenAI ou LM Studio)
        self.api_mode = os.environ.get('AI_API_MODE', 'openai').lower()
        
        # Configuration commune
        self.timeout = int(os.environ.get('AI_TIMEOUT', '60'))
        
        # Configuration spécifique à OpenAI
        self.openai_api_key = os.environ.get('OPENAI_API_KEY', '')
        self.openai_model = os.environ.get('OPENAI_MODEL', 'gpt-4-vision-preview')
        
        # Configuration spécifique à LM Studio
        self.lmstudio_url = os.environ.get('LMSTUDIO_URL', 'http://localhost:1234/v1')
        self.lmstudio_model = os.environ.get('LMSTUDIO_MODEL', 'local-model')
        
        # Initialiser le client OpenAI approprié
        if self.api_mode == 'lmstudio':
            self.client = OpenAI(
                base_url=self.lmstudio_url,
                api_key="lm-studio",  # Valeur fictive mais requise
                timeout=self.timeout
            )
            self.model = self.lmstudio_model
            print(f"Configuration AI Service (LM Studio):\n - URL: {self.lmstudio_url}\n - Modèle: {self.model}\n - Timeout: {self.timeout}s")
        else:  # mode 'openai' par défaut
            self.client = OpenAI(
                api_key=self.openai_api_key,
                timeout=self.timeout
            )
            self.model = self.openai_model
            print(f"Configuration AI Service (OpenAI):\n - Modèle: {self.model}\n - Timeout: {self.timeout}s")
    
    def analyze_image(self, image_base64: str, prompt: str) -> Dict[str, Any]:
        """Analyse une image avec OpenAI ou LM Studio en utilisant l'API compatible OpenAI"""
        try:
            # Préparer l'image pour l'API vision
            image_content = f"data:image/jpeg;base64,{image_base64}"
            
            api_name = "LM Studio" if self.api_mode == "lmstudio" else "OpenAI"
            print(f"Envoi de la requête à {api_name} avec timeout de {self.timeout}s...")
            
            # Utiliser l'API OpenAI (ou compatible) pour générer la réponse
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", 
                     "content": [
                         {"type": "text", "text": prompt},
                         {"type": "image_url", "image_url": {"url": image_content}}
                     ]
                    }
                ],
                max_tokens=500
            )
            
            print(f"Réponse reçue avec succès de {api_name}")
            message_content = response.choices[0].message.content
            return {
                'success': True,
                'response': message_content,
                'model': self.model
            }
        except Exception as e:
            api_name = "LM Studio" if self.api_mode == "lmstudio" else "OpenAI"
            error_msg = f'Erreur lors de la connexion à {api_name}: {str(e)}'
            print(f"Exception: {error_msg}")
            
            if self.api_mode == "lmstudio":
                print("Assurez-vous que LM Studio est bien installé et en cours d'exécution sur votre machine.")
                print("Vous pouvez l'installer depuis https://lmstudio.ai/")
            else:
                print("Vérifiez votre clé API OpenAI et votre connexion internet.")
                
            print(f"Essayez d'augmenter le délai dans le fichier .env avec AI_TIMEOUT={self.timeout*2}")
            return {
                'success': False,
                'error': error_msg
            }
    
    # Les méthodes count_people et describe_scene ont été supprimées
    # car elles sont remplacées par la méthode analyze_combined qui regroupe tous les prompts en un seul
    
    def check_custom_detection(self, image_base64: str, detection_phrase: str) -> Dict[str, Any]:
        """Vérifie si une phrase de détection correspond à l'image"""
        prompt = f"""Analyze this image and determine if it matches this description: "{detection_phrase}"
        
        Reply only with "YES" or "NO" depending on whether the image matches the description or not.
        Be precise in your analysis."""
        
        result = self.analyze_image(image_base64, prompt)
        
        if result['success']:
            response_text = result['response'].strip().upper()
            is_match = 'YES' in response_text
            
            return {
                'success': True,
                'match': is_match,
                'raw_response': result['response']
            }
        else:
            return result
            
    def analyze_combined(self, image_base64: str, detections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyse une image avec un prompt combiné pour tous les besoins d'analyse
        
        Args:
            image_base64: Image en base64
            detections: Liste des détections personnalisées à vérifier
            
        Returns:
            Dict avec les résultats structurés
        """
        # Construire un prompt combiné qui demande une réponse structurée
        detection_prompts = ""
        for i, detection in enumerate(detections):
            detection_prompts += f"\nDetection {i+1}: {detection['phrase']} (Answer with YES or NO)"
        
        prompt = f"""Analyze this image and answer the following questions in a structured JSON format:

1. How many people are visible in the image? (answer with an integer number)

{detection_prompts}

Format your response as valid JSON like this:
{{
  "people_count": number_of_people,
  "detections": [
    {{ "id": 1, "result": "YES/NO" }},
    {{ "id": 2, "result": "YES/NO" }},
    ...
  ]
}}

Make sure your response is valid JSON without any additional text before or after."""
        
        result = self.analyze_image(image_base64, prompt)
        
        if result['success']:
            try:
                # Essayer de parser la réponse JSON
                response_text = result['response'].strip()
                
                # Extraire uniquement la partie JSON (au cas où il y aurait du texte avant/après)
                import re
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    json_str = json_match.group(0)
                    parsed_result = json.loads(json_str)
                    
                    # Structurer la réponse
                    structured_result = {
                        'success': True,
                        'people_count': {
                            'success': True,
                            'count': parsed_result.get('people_count', 0)
                        },
                        'detections': []
                    }
                    
                    # Traiter les résultats des détections
                    detection_results = parsed_result.get('detections', [])
                    for i, detection_result in enumerate(detection_results):
                        if i < len(detections):
                            detection_id = detections[i]['id']
                            result_text = detection_result.get('result', '').upper()
                            is_match = result_text == 'YES' or result_text == 'OUI'
                            
                            structured_result['detections'].append({
                                'id': detection_id,
                                'success': True,
                                'match': is_match,
                                'raw_response': detection_result.get('result', '')
                            })
                    
                    return structured_result
                else:
                    return {
                        'success': False,
                        'error': 'Format JSON invalide dans la réponse',
                        'raw_response': response_text
                    }
            except json.JSONDecodeError as e:
                return {
                    'success': False,
                    'error': f'Erreur de décodage JSON: {str(e)}',
                    'raw_response': result['response']
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Erreur lors du traitement de la réponse: {str(e)}',
                    'raw_response': result['response']
                }
        else:
            return result
    
    def test_connection(self) -> Dict[str, Any]:
        """Teste la connexion avec OpenAI ou LM Studio"""
        try:
            # Tester la connexion avec une requête simple
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": "Hello, are you working?"}
                ],
                max_tokens=10
            )
            
            api_name = "LM Studio" if self.api_mode == "lmstudio" else "OpenAI"
            return {
                'success': True,
                'api_mode': self.api_mode,
                'current_model': self.model,
                'response': response.choices[0].message.content
            }
        except Exception as e:
            api_name = "LM Studio" if self.api_mode == "lmstudio" else "OpenAI"
            return {
                'success': False,
                'error': f'Impossible de se connecter à {api_name}: {str(e)}'
            }
