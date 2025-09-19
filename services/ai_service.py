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
                f"Configuration AI Service (LM Studio):\n - URL: {self.lmstudio_url}\n - Modèle: {self.model}\n - Timeout: {self.timeout}s"
            )
        elif self.api_mode == 'ollama':
            self.client = OpenAI(
                base_url=self.ollama_url,
                api_key="ollama",  # Valeur fictive mais requise
                timeout=self.timeout
            )
            self.model = self.ollama_model
            logger.info(
                f"Configuration AI Service (Ollama):\n - URL: {self.ollama_url}\n - Modèle: {self.model}\n - Timeout: {self.timeout}s"
            )
        else:  # mode 'openai' par défaut
            self.client = OpenAI(
                api_key=self.openai_api_key,
                timeout=self.timeout
            )
            self.model = self.openai_model
            logger.info(
                f"Configuration AI Service (OpenAI):\n - Modèle: {self.model}\n - Timeout: {self.timeout}s"
            )
        
        # Ne pas effectuer de requête réseau au démarrage pour éviter de bloquer l'application
        # Le support strict a été retiré; on fonctionne en mode JSON non strict par défaut
    
    def reload_from_env(self):
        """Recharge la configuration AI depuis les variables d'environnement et réinitialise le client."""
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        except Exception:
            pass

        # Mettre à jour la configuration
        self.api_mode = os.environ.get('AI_API_MODE', 'openai').lower()
        try:
            self.timeout = int(os.environ.get('AI_TIMEOUT', str(self.timeout)))
        except Exception:
            # Conserver l'ancien timeout en cas d'entrée invalide
            pass
        self.openai_api_key = os.environ.get('OPENAI_API_KEY', self.openai_api_key)
        self.openai_model = os.environ.get('OPENAI_MODEL', self.openai_model)
        self.lmstudio_url = os.environ.get('LMSTUDIO_URL', self.lmstudio_url)
        self.lmstudio_model = os.environ.get('LMSTUDIO_MODEL', self.lmstudio_model)
        self.ollama_url = os.environ.get('OLLAMA_URL', self.ollama_url)
        self.ollama_model = os.environ.get('OLLAMA_MODEL', self.ollama_model)

        # Normaliser les URLs /v1 si nécessaire
        def _ensure_v1(url: str) -> str:
            try:
                p = urlparse(url)
                if not p.scheme:
                    return url
                path = (p.path or '').rstrip('/')
                if path in ('', '/'):
                    new_path = '/v1'
                elif path == '/v1':
                    new_path = '/v1'
                else:
                    return url
                return urlunparse(p._replace(path=new_path))
            except Exception:
                return url

        self.lmstudio_url = _ensure_v1(self.lmstudio_url)
        self.ollama_url = _ensure_v1(self.ollama_url)

        # Reconstruire le client
        try:
            if self.api_mode == 'lmstudio':
                self.client = OpenAI(base_url=self.lmstudio_url, api_key="lm-studio", timeout=self.timeout)
                self.model = self.lmstudio_model
                logger.info(f"AIService rechargé → LM Studio @ {self.lmstudio_url} • modèle={self.model}")
            elif self.api_mode == 'ollama':
                self.client = OpenAI(base_url=self.ollama_url, api_key="ollama", timeout=self.timeout)
                self.model = self.ollama_model
                logger.info(f"AIService rechargé → Ollama @ {self.ollama_url} • modèle={self.model}")
            else:
                self.client = OpenAI(api_key=self.openai_api_key, timeout=self.timeout)
                self.model = self.openai_model
                logger.info(f"AIService rechargé → OpenAI • modèle={self.model}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors du rechargement AIService: {e}")
            return False

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
            if self.api_mode == 'ollama':
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
                    max_tokens=500,
                    temperature=0
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
        # Prompt simplifié: uniquement des détections en booléen pur (true/false), ordre identique
        detection_prompts = ""
        for i, detection in enumerate(detections):
            detection_prompts += f"\n{i+1}) {detection['phrase']}"
        
        prompt = f"""Analyze this image.

For each of the following detections, indicate if it matches the image.

Detections:{detection_prompts}

Return ONLY valid JSON (no other text), exactly in this format:
{{
  "detections": [
    {{ "result": true }},
    {{ "result": false }}
  ]
}}

Rules:
- The detections array MUST have exactly {len(detections)} items, in the same order as listed above.
- Each result MUST be a boolean: true or false.
"""
        
        result = self.analyze_image(image_base64, prompt)
        
        if result['success']:
            try:
                # Essayer de parser la réponse JSON
                response_text = result['response'].strip()
                
                # Parser le JSON avec fallback pour extraction
                parsed_result = self._parse_json_with_fallback(response_text)
                
                # Structurer la réponse (uniquement les détections)
                structured_result = {
                    'success': True,
                    'detections': []
                }
                
                # Traiter et normaliser la longueur des résultats des détections
                detection_results = parsed_result.get('detections', []) or []
                if len(detection_results) > len(detections):
                    logger.warning(f"IA a renvoyé {len(detection_results)} détections pour {len(detections)} attendues. Les extras seront ignorées.")
                
                for i in range(len(detections)):
                    detection_id = detections[i]['id']
                    raw_val = None
                    if i < len(detection_results):
                        item = detection_results[i] or {}
                        raw_val = item.get('result')
                        is_match = self._validate_detection_result(raw_val)
                    else:
                        is_match = False
                    structured_result['detections'].append({
                        'id': detection_id,
                        'success': True,
                        'match': is_match,
                        'raw_response': raw_val
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
