import json
import os
import re
import base64
from typing import Dict, Any, List
from openai import OpenAI
import logging
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        # Déterminer le mode API (OpenAI ou LM Studio)
        self.api_mode = os.environ.get('AI_API_MODE', 'openai').lower()
        
        # Configuration commune
        self.timeout = int(os.environ.get('AI_TIMEOUT', '60'))
        # Timeout court dédié aux probes de démarrage (éviter blocage au boot)
        try:
            self.probe_timeout = float(os.environ.get('AI_PROBE_TIMEOUT', '3'))
        except Exception:
            self.probe_timeout = 3.0
        # Sortie structurée stricte (JSON uniquement)
        self.strict_output = str(os.environ.get('AI_STRICT_OUTPUT', 'false')).lower() in ['1', 'true', 'yes', 'on']
        
        # Configuration spécifique à OpenAI
        self.openai_api_key = os.environ.get('OPENAI_API_KEY', '')
        self.openai_model = os.environ.get('OPENAI_MODEL', 'gpt-4o')
        
        # Configuration spécifique à LM Studio
        self.lmstudio_url = os.environ.get('LMSTUDIO_URL', 'http://127.0.0.1:11434/v1')
        self.lmstudio_model = os.environ.get('LMSTUDIO_MODEL', 'local-model')
        
        # Configuration spécifique à Ollama (API compatible OpenAI)
        self.ollama_url = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434/v1')
        self.ollama_model = os.environ.get('OLLAMA_MODEL', '')

        # Normaliser automatiquement les URLs pour s'assurer que le suffixe /v1 est présent
        def _ensure_v1(url: str) -> str:
            try:
                p = urlparse(url)
                # Si l'URL est invalide (pas de schéma), ne pas modifier
                if not p.scheme:
                    return url
                path = (p.path or '').rstrip('/')
                # Cas fréquents: vide ou '/'
                if path in ('', '/'):
                    new_path = '/v1'
                # Déjà correct
                elif path == '/v1':
                    new_path = '/v1'
                # Autres chemins: ne pas tenter de deviner -> laisser tel quel
                else:
                    return url
                return urlunparse(p._replace(path=new_path))
            except Exception:
                return url

        orig_lm = self.lmstudio_url
        orig_ol = self.ollama_url
        self.lmstudio_url = _ensure_v1(self.lmstudio_url)
        self.ollama_url = _ensure_v1(self.ollama_url)
        if self.lmstudio_url != orig_lm:
            logger.info(f"LM Studio URL normalisée → {self.lmstudio_url} (ajout auto de /v1)")
        if self.ollama_url != orig_ol:
            logger.info(f"Ollama URL normalisée → {self.ollama_url} (ajout auto de /v1)")
        
        # Initialiser le client OpenAI approprié
        if self.api_mode == 'lmstudio':
            self.client = OpenAI(
                base_url=self.lmstudio_url,
                api_key="lm-studio",  # Valeur fictive mais requise
                timeout=self.timeout
            )
            self.model = self.lmstudio_model
            logger.info(
                f"Configuration AI Service (LM Studio):\n - URL: {self.lmstudio_url}\n - Modèle: {self.model}\n - Timeout: {self.timeout}s\n - Strict JSON: {self.strict_output}"
            )
        elif self.api_mode == 'ollama':
            self.client = OpenAI(
                base_url=self.ollama_url,
                api_key="ollama",  # Valeur fictive mais requise
                timeout=self.timeout
            )
            self.model = self.ollama_model
            logger.info(
                f"Configuration AI Service (Ollama):\n - URL: {self.ollama_url}\n - Modèle: {self.model}\n - Timeout: {self.timeout}s\n - Strict JSON: {self.strict_output}"
            )
        else:  # mode 'openai' par défaut
            self.client = OpenAI(
                api_key=self.openai_api_key,
                timeout=self.timeout
            )
            self.model = self.openai_model
            logger.info(
                f"Configuration AI Service (OpenAI):\n - Modèle: {self.model}\n - Timeout: {self.timeout}s\n - Strict JSON: {self.strict_output}"
            )
        
        # Ne pas effectuer de requête réseau au démarrage pour éviter de bloquer l'application
        # Le support strict sera vérifié à la première utilisation si nécessaire
        self.strict_supported = None
        if self.strict_output:
            logger.info("AI_STRICT_OUTPUT activé: la compatibilité json_schema sera vérifiée à la première requête.")
    
    def _get_api_name(self) -> str:
        """Retourne le nom de l'API utilisée pour les logs"""
        if self.api_mode == "lmstudio":
            return "LM Studio"
        elif self.api_mode == "ollama":
            return "Ollama"
        else:
            return "OpenAI"
    
    def _extract_content(self, response) -> str:
        """Extrait de manière robuste le contenu texte d'une complétion.
        Gère les différences entre OpenAI officiel et backends compatibles (LM Studio/Ollama).
        Retourne une chaîne (éventuellement vide) ou None si introuvable.
        """
        try:
            # Chemin standard client OpenAI v1
            content = getattr(getattr(response.choices[0], 'message', None), 'content', None)
            if content:
                return content
        except Exception:
            pass
        # Fallback: transformer en dict et inspecter
        try:
            data = None
            if hasattr(response, 'model_dump'):
                data = response.model_dump()
            elif hasattr(response, 'to_dict'):
                data = response.to_dict()
            elif isinstance(response, dict):
                data = response
            if data and isinstance(data, dict):
                choices = data.get('choices') or []
                if isinstance(choices, list) and choices:
                    ch0 = choices[0] or {}
                    msg = ch0.get('message') or {}
                    content = msg.get('content')
                    if content:
                        return content
                    # Certains backends renvoient `text` au lieu de message.content
                    txt = ch0.get('text')
                    if txt:
                        return txt
        except Exception:
            pass
        return None
    
    def _validate_detection_result(self, val) -> bool:
        """Valide le résultat d'une détection de manière cohérente"""
        if isinstance(val, bool):
            return val
        return str(val).upper() in ('YES', 'OUI', 'TRUE', '1')
    
    def _extract_json_from_text(self, text: str):
        """Extrait le JSON d'un texte de manière plus robuste"""
        # Chercher d'abord un bloc JSON entre accolades
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if json_match:
            return json_match
        # Fallback: chercher n'importe quel contenu entre accolades
        return re.search(r'\{[\s\S]*\}', text)
    
    def _parse_json_with_fallback(self, text: str):
        """Parse JSON avec fallback pour extraire du contenu encapsulé"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fallback: extraire le premier objet JSON trouvé dans le contenu
            json_match = self._extract_json_from_text(text)
            if json_match:
                return json.loads(json_match.group(0))
            raise
    
    def analyze_image(self, image_base64: str, prompt: str) -> Dict[str, Any]:
        """Analyse une image avec OpenAI ou LM Studio en utilisant l'API compatible OpenAI"""
        try:
            # Préparer l'image pour l'API vision
            image_content = f"data:image/jpeg;base64,{image_base64}"
            
            api_name = self._get_api_name()
            logger.info(f"Envoi de la requête à {api_name} avec timeout de {self.timeout}s...")
            
            # Utiliser l'API OpenAI (ou compatible) pour générer la réponse
            if self.api_mode == 'ollama' and not self.strict_output:
                # Alignement Ollama: demander un JSON pur sans schéma
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
                    max_tokens=500,
                    temperature=0,
                    extra_body={
                        "format": "json"
                    }
                )
            else:
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
            
            logger.info(f"Réponse reçue avec succès de {api_name}")
            message_content = self._extract_content(response)
            if not message_content:
                raise ValueError("Réponse IA vide ou au format inattendu (pas de content/text)")
            return {
                'success': True,
                'response': message_content,
                'model': self.model
            }
        except Exception as e:
            api_name = self._get_api_name()
            error_msg = f'Erreur lors de la connexion à {api_name}: {str(e)}'
            logger.error(f"Exception: {error_msg}")
            
            if self.api_mode == "lmstudio":
                logger.error("Assurez-vous que LM Studio est bien installé et en cours d'exécution sur votre machine.")
                logger.error("Vous pouvez l'installer depuis https://lmstudio.ai/")
            elif self.api_mode == "ollama":
                logger.error("Assurez-vous qu'Ollama est démarré (par défaut http://127.0.0.1:11434).")
                logger.error("Installez un modèle compatible (ex: llava, moondream) pour l'analyse d'images.")
            else:
                logger.error("Vérifiez votre clé API OpenAI et votre connexion internet.")
                
            logger.info(
                f"Essayez d'augmenter le délai dans le fichier .env avec AI_TIMEOUT={self.timeout*2}"
            )
            return {
                'success': False,
                'error': error_msg
            }
    
    # Les méthodes count_people et describe_scene ont été supprimées
    # car elles sont remplacées par la méthode analyze_combined qui regroupe tous les prompts en un seul
    def analyze_combined(self, image_base64: str, detections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyse une image avec un prompt combiné pour tous les besoins d'analyse
        
        Args:
            image_base64: Image en base64
            detections: Liste des détections personnalisées à vérifier
            
        Returns:
            Dict avec les résultats structurés
        """
        # Construire les prompts selon le mode strict
        if self.strict_output:
            # Prompt dédié au mode strict (json_schema): pas d'instructions de format JSON
            strict_detections = ""
            for i, detection in enumerate(detections):
                strict_detections += f"\n- Detection {i+1}: {detection['phrase']}"
            prompt_strict = (
                "Analyze this image.\n\n"
                "Provide: \n"
                "1) people_count: the number of people visible (integer)\n"
                "2) detections: for each detection below, set result to true if it matches the image, else false.\n\n"
                f"Detections:{strict_detections}"
            )
        else:
            # Mode non strict: demander du JSON via le prompt
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
        
        if self.strict_output:
            # Mode strict: demander un JSON strict et NE PAS faire de fallback
            try:
                image_content = f"data:image/jpeg;base64,{image_base64}"
                # Schéma strict pour le résultat combiné
                combined_schema = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "combined_analysis",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "people_count": {"type": "integer", "minimum": 0},
                                "detections": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "result": {"type": "boolean"}
                                        },
                                        "required": ["result"]
                                    }
                                }
                            },
                            "required": ["people_count", "detections"]
                        }
                    }
                }
                if self.api_mode == 'ollama':
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "user",
                             "content": [
                                {"type": "text", "text": prompt_strict},
                                {"type": "image_url", "image_url": {"url": image_content}}
                             ]}
                        ],
                        max_tokens=700,
                        temperature=0,
                        extra_body={
                            "format": combined_schema
                        }
                    )
                else:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "user",
                             "content": [
                                {"type": "text", "text": prompt_strict},
                                {"type": "image_url", "image_url": {"url": image_content}}
                             ]}
                        ],
                        max_tokens=700,
                        temperature=0,
                        response_format=combined_schema
                    )
                message_content = self._extract_content(response) or "{}"
                try:
                    parsed_result = self._parse_json_with_fallback(message_content)
                    if message_content != json.dumps(parsed_result, separators=(',', ':')):
                        logger.warning("Strict JSON parse required fallback extraction; backend may not enforce pure JSON content.")
                except Exception as e:
                    return {
                        'success': False,
                        'error': 'Format JSON invalide dans la réponse (mode strict)',
                        'details': str(e),
                        'raw_response': (message_content[:500] + '...') if len(message_content) > 500 else message_content
                    }
                
                structured_result = {
                    'success': True,
                    'people_count': {
                        'success': True,
                        'count': parsed_result.get('people_count', 0)
                    },
                    'detections': []
                }
                detection_results = parsed_result.get('detections', [])
                for i, detection_result in enumerate(detection_results):
                    if i < len(detections):
                        detection_id = detections[i]['id']
                        val = detection_result.get('result', False)
                        is_match = self._validate_detection_result(val)
                        structured_result['detections'].append({
                            'id': detection_id,
                            'success': True,
                            'match': is_match,
                            'raw_response': detection_result.get('result', '')
                        })
                return structured_result
            except Exception as e:
                msg = (
                    "AI_STRICT_OUTPUT est activé mais une erreur est survenue (API non supportée ou autre). "
                    "Désactivez AI_STRICT_OUTPUT dans l'Administration si vous souhaitez revenir au mode non strict."
                )
                logger.error(f"Strict JSON error in analyze_combined: {e}")
                return {
                    'success': False,
                    'error': msg,
                    'details': str(e)
                }
        else:
            result = self.analyze_image(image_base64, prompt)
            
            if result['success']:
                try:
                    # Essayer de parser la réponse JSON
                    response_text = result['response'].strip()
                    
                    # Parser le JSON avec fallback pour extraction
                    parsed_result = self._parse_json_with_fallback(response_text)
                    
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
                            val = detection_result.get('result', '')
                            is_match = self._validate_detection_result(val)
                            
                            structured_result['detections'].append({
                                'id': detection_id,
                                'success': True,
                                'match': is_match,
                                'raw_response': detection_result.get('result', '')
                            })
                    
                    return structured_result
                except json.JSONDecodeError as e:
                    return {
                        'success': False,
                        'error': f'Erreur de décodage JSON: {str(e)}',
                        'raw_response': response_text
                    }
                except Exception as e:
                    return {
                        'success': False,
                        'error': f'Erreur lors du traitement de la réponse: {str(e)}',
                        'raw_response': response_text
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
                max_tokens=10,
                timeout=self.probe_timeout
            )
            
            preview = self._extract_content(response) or ""
            return {
                'success': True,
                'api_mode': self.api_mode,
                'current_model': self.model,
                'response': preview
            }
        except Exception as e:
            api_name = self._get_api_name()
            return {
                'success': False,
                'error': f'Impossible de se connecter à {api_name}: {str(e)}'
            }
