import requests
import json
import os
from typing import Dict, Any

class AIService:
    def __init__(self):
        self.base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = os.getenv('OLLAMA_MODEL', 'llama3.2-vision:latest')
    
    def analyze_image(self, image_base64: str, prompt: str) -> Dict[str, Any]:
        """Analyse une image avec Ollama"""
        try:
            url = f"{self.base_url}/api/generate"
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [image_base64],
                "stream": False
            }
            
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'response': result.get('response', ''),
                    'model': self.model
                }
            else:
                return {
                    'success': False,
                    'error': f'Erreur HTTP {response.status_code}: {response.text}'
                }
                
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'Erreur de connexion: {str(e)}'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Erreur inattendue: {str(e)}'
            }
    
    def count_people(self, image_base64: str) -> Dict[str, Any]:
        """Compte le nombre de personnes dans l'image"""
        prompt = """Analyse cette image et compte précisément le nombre de personnes visibles. 
        Réponds uniquement par un nombre entier (par exemple: 0, 1, 2, 3, etc.).
        Si tu ne vois aucune personne, réponds 0."""
        
        result = self.analyze_image(image_base64, prompt)
        
        if result['success']:
            try:
                # Extraire le nombre de la réponse
                response_text = result['response'].strip()
                # Chercher le premier nombre dans la réponse
                import re
                numbers = re.findall(r'\d+', response_text)
                if numbers:
                    count = int(numbers[0])
                    return {
                        'success': True,
                        'count': count,
                        'raw_response': response_text
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Impossible d\'extraire le nombre de personnes',
                        'raw_response': response_text
                    }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Erreur lors du parsing: {str(e)}',
                    'raw_response': result['response']
                }
        else:
            return result
    
    def describe_scene(self, image_base64: str) -> Dict[str, Any]:
        """Décrit la scène dans l'image"""
        prompt = """Décris brièvement ce qui se passe dans cette image en français. 
        Concentre-toi sur les actions, les objets principaux et les personnes présentes.
        Garde ta description concise (maximum 2-3 phrases)."""
        
        return self.analyze_image(image_base64, prompt)
    
    def check_custom_detection(self, image_base64: str, detection_phrase: str) -> Dict[str, Any]:
        """Vérifie si une phrase de détection correspond à l'image"""
        prompt = f"""Analyse cette image et détermine si elle correspond à cette description: "{detection_phrase}"
        
        Réponds uniquement par "OUI" ou "NON" selon que l'image correspond ou non à la description.
        Sois précis dans ton analyse."""
        
        result = self.analyze_image(image_base64, prompt)
        
        if result['success']:
            response_text = result['response'].strip().upper()
            is_match = 'OUI' in response_text
            
            return {
                'success': True,
                'match': is_match,
                'raw_response': result['response']
            }
        else:
            return result
    
    def test_connection(self) -> Dict[str, Any]:
        """Teste la connexion avec Ollama"""
        try:
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [model['name'] for model in models]
                
                return {
                    'success': True,
                    'available_models': model_names,
                    'current_model': self.model,
                    'model_available': self.model in model_names
                }
            else:
                return {
                    'success': False,
                    'error': f'Erreur HTTP {response.status_code}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Impossible de se connecter à Ollama: {str(e)}'
            }
