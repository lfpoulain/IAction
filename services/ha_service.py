import time
import base64
import hashlib
import logging
from typing import Callable, Optional

import cv2
import numpy as np
import requests
from urllib.parse import urlparse


class HAService:
    """
    Service de polling Home Assistant pour récupérer des images d'une entité
    et fournir les frames décodées au reste de l'application via un callback.

    API principale:
      - run_loop(on_frame, is_running_fn): boucle de polling bloquante
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        entity_id: str,
        image_attr: str = "entity_picture",
        poll_interval: float = 1.0,
        state_timeout: float = 5.0,
        image_timeout: float = 8.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip('/')
        self.token = token or ""
        self.entity_id = entity_id or ""
        self.image_attr = image_attr or "entity_picture"
        self.poll_interval = max(float(poll_interval or 1.0), 0.1)
        self.logger = logger or logging.getLogger(__name__)
        self.state_timeout = float(state_timeout or 5.0)
        self.image_timeout = float(image_timeout or 8.0)

        self.session = requests.Session()
        if self.token:
            self.session.headers.update({'Authorization': f'Bearer {self.token}'})

        # État pour déduplication
        self._last_image_hash: Optional[str] = None
        self._last_source_url: Optional[str] = None  # URL sans anti-cache

        # Fallbacks d'attributs possibles dans HA
        self._fallback_attrs = [
            self.image_attr,
            'entity_picture', 'entity_picture_local', 'image', 'file', 'thumbnail', 'last_thumbnail', 'picture'
        ]

    def _resize_frame_for_analysis(self, frame):
        """Redimensionne une frame en 720p pour l'analyse IA de manière centralisée"""
        try:
            if frame is None:
                return None
            # Vérifier si déjà en 720p pour éviter un redimensionnement inutile
            height, width = frame.shape[:2]
            if height == 720 and width == 1280:
                return frame
            return cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
        except Exception as e:
            self.logger.warning(f"Erreur lors du redimensionnement: {e}")
            return frame

    def run_loop(self, on_frame: Callable[[np.ndarray], None], is_running_fn: Callable[[], bool]) -> None:
        """
        Lance la boucle de polling. Bloque tant que is_running_fn() est True.
        Appelle on_frame(frame_bgr) lorsqu'une nouvelle image utile est disponible.
        """
        if not self.base_url or not self.token or not self.entity_id:
            self.logger.error("HA Polling: configuration incomplète (HA_BASE_URL, HA_TOKEN, HA_ENTITY_ID requis)")
            return

        state_url = f"{self.base_url}/api/states/{self.entity_id}"
        headers_json = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        self.logger.info(
            f"HA Polling: démarrage - base_url={self.base_url or 'N/A'}, "
            f"entity_id={self.entity_id or 'N/A'}, image_attr={self.image_attr}, poll_interval={self.poll_interval}"
        )

        while is_running_fn():
            loop_start = time.time()
            try:
                self.logger.info(f"HA Polling: GET état -> {state_url}")
                resp = self.session.get(state_url, headers=headers_json, timeout=self.state_timeout)
                if resp.status_code != 200:
                    self.logger.warning(f"HA Polling: statut {resp.status_code} sur {state_url}")
                    time.sleep(self._remaining(loop_start))
                    continue

                # Parse JSON d'état
                try:
                    data = resp.json()
                except Exception as je:
                    self.logger.warning(
                        f"HA Polling: JSON invalide depuis {state_url} (len={len(getattr(resp,'text','') or '')}) : {je}"
                    )
                    time.sleep(self._remaining(loop_start))
                    continue

                attrs = data.get('attributes', {}) if isinstance(data, dict) else {}
                try:
                    top_keys = list(data.keys()) if isinstance(data, dict) else type(data)
                    attr_keys = list(attrs.keys()) if isinstance(attrs, dict) else []
                    self.logger.info(f"HA Polling: clés état={top_keys} | clés attributes={attr_keys}")
                except Exception:
                    pass

                # Résoudre l'attribut d'image
                img_path = self._resolve_image_attr(attrs)
                self.logger.info(
                    f"HA Polling: état récupéré (200) pour {self.entity_id}. Attribut '{self.image_attr}' présent: {bool(img_path)}"
                )
                if not img_path:
                    self.logger.warning("HA Polling: attribut image introuvable – vérifiez HA_IMAGE_ATTR")
                    time.sleep(self._remaining(loop_start))
                    continue

                # Data URI inline
                if isinstance(img_path, str) and img_path.startswith('data:'):
                    if self._handle_data_uri(img_path, on_frame):
                        time.sleep(self._remaining(loop_start))
                        continue

                # Contenu base64 dans un objet { content: ... }
                if isinstance(img_path, dict) and isinstance(img_path.get('content'), str):
                    if self._handle_base64_content(img_path['content'], on_frame):
                        time.sleep(self._remaining(loop_start))
                        continue

                # URL absolue ou relative
                img_url = self._to_absolute_url(img_path)
                self.logger.info(f"HA Polling: image URL = {img_url}")

                # Skip rapide si URL source identique
                if self._last_source_url and img_url == self._last_source_url:
                    self.logger.info("HA Polling: même URL source que précédemment – skip téléchargement/analyse")
                    time.sleep(self._remaining(loop_start))
                    continue

                # Décider si l'on ajoute un paramètre anti-cache
                base_host = urlparse(self.base_url).netloc if self.base_url else ''
                urlp = urlparse(img_url)
                is_same_host = (urlp.netloc == base_host and base_host != '')
                # Détecter URL signées (ex: S3 presigned) où l'ajout de paramètres casse la signature
                q = urlp.query or ''
                is_signed = any(k in q for k in (
                    'AWSAccessKeyId', 'Signature', 'X-Amz-Signature', 'X-Amz-Algorithm', 'X-Amz-Credential', 'X-Amz-Expires'
                ))

                if is_same_host and not is_signed:
                    sep = '&' if '?' in img_url else '?'
                    img_url_fetch = f"{img_url}{sep}t={int(time.time()*1000)}"
                else:
                    img_url_fetch = img_url

                # Télécharger l'image (éviter d'envoyer l'Authorization HA vers des hôtes tiers)
                if is_same_host:
                    img_resp = self.session.get(img_url_fetch, timeout=self.image_timeout)
                else:
                    img_resp = requests.get(
                        img_url_fetch,
                        timeout=self.image_timeout,
                        headers={'User-Agent': 'IAction-HA/1.0', 'Accept': 'image/*'}
                    )
                if img_resp.status_code != 200:
                    self.logger.warning(f"HA Polling: échec téléchargement image {img_resp.status_code}")
                    time.sleep(self._remaining(loop_start))
                    continue

                img_bytes = img_resp.content
                self.logger.info(
                    f"HA Polling: image téléchargée (HTTP 200), taille={len(img_bytes)} bytes, "
                    f"content-type={img_resp.headers.get('Content-Type','?')}"
                )

                # Déduplication par hash
                try:
                    img_hash = hashlib.md5(img_bytes).hexdigest()
                    if self._last_image_hash and img_hash == self._last_image_hash:
                        self.logger.info("HA Polling: image identique à la précédente (hash match) – skip analyse")
                        self._last_source_url = img_url
                        time.sleep(self._remaining(loop_start))
                        continue
                except Exception:
                    img_hash = None

                # Décoder
                np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.logger.warning("HA Polling: image non décodable – format non supporté ?")
                    time.sleep(self._remaining(loop_start))
                    continue

                try:
                    h, w = frame.shape[:2]
                    self.logger.info(f"HA Polling: image décodée {w}x{h}, taille={len(img_bytes)} bytes")
                except Exception:
                    self.logger.info("HA Polling: dimensions image indisponibles")

                # Normaliser en 1280x720 pour l'analyse
                frame = self._resize_frame_for_analysis(frame)

                # Mettre à jour l'état de déduplication puis publier
                if img_hash:
                    self._last_image_hash = img_hash
                self._last_source_url = img_url

                on_frame(frame)

            except Exception as e:
                self.logger.warning(f"HA Polling: exception {e}")
            finally:
                time.sleep(self._remaining(loop_start))

    # Helpers
    def _remaining(self, loop_start: float) -> float:
        elapsed = time.time() - loop_start
        remaining = max(self.poll_interval - elapsed, 0.0)
        return remaining if remaining > 0 else 0.0

    def _resolve_image_attr(self, attrs: dict):
        # valeur directe par nom
        val = attrs.get(self.image_attr)
        if val:
            return self._normalize_attr_value(val)
        # fallback
        for key in self._fallback_attrs:
            val = attrs.get(key)
            if val:
                self.logger.info(f"HA Polling: fallback -> usage de l'attribut '{key}'")
                return self._normalize_attr_value(val)
        return None

    @staticmethod
    def _normalize_attr_value(val):
        # si dict, essayer des clés URL communes, sinon content base64 géré ailleurs
        if isinstance(val, dict):
            for k in ['url', 'href', 'link', 'image', 'file']:
                if isinstance(val.get(k), str):
                    return val[k]
            return val
        return val

    def _to_absolute_url(self, img_path: str) -> str:
        if isinstance(img_path, str) and img_path.startswith('http'):
            return img_path
        p = img_path or ''
        if isinstance(p, str) and not p.startswith('/'):
            p = '/' + p
        return f"{self.base_url}{p}"

    def _handle_data_uri(self, data_uri: str, on_frame: Callable[[np.ndarray], None]) -> bool:
        try:
            comma_idx = data_uri.find(',')
            b64_part = data_uri[comma_idx + 1:] if comma_idx != -1 else data_uri
            img_bytes = base64.b64decode(b64_part)
            # Dédup par hash
            img_hash = hashlib.md5(img_bytes).hexdigest()
            if self._last_image_hash and img_hash == self._last_image_hash:
                self.logger.info("HA Polling: image identique à la précédente (hash match) – skip analyse")
                return True
            np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                self.logger.warning("HA Polling: Data URI non décodable")
                return True
            try:
                h, w = frame.shape[:2]
                self.logger.info(f"HA Polling: Data URI décodée {w}x{h}, taille={len(img_bytes)} bytes")
            except Exception:
                pass
            frame = self._resize_frame_for_analysis(frame)
            self._last_image_hash = img_hash
            self._last_source_url = 'data-uri'
            on_frame(frame)
            return True
        except Exception as e:
            self.logger.warning(f"HA Polling: échec décodage Data URI: {e}")
            return True

    def _handle_base64_content(self, content_b64: str, on_frame: Callable[[np.ndarray], None]) -> bool:
        try:
            img_bytes = base64.b64decode(content_b64)
            img_hash = hashlib.md5(img_bytes).hexdigest()
            if self._last_image_hash and img_hash == self._last_image_hash:
                self.logger.info("HA Polling: image identique à la précédente (hash match) – skip analyse")
                return True
            np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                self.logger.warning("HA Polling: contenu base64 non décodable")
                return True
            try:
                h, w = frame.shape[:2]
                self.logger.info(f"HA Polling: contenu base64 décodé {w}x{h}, taille={len(img_bytes)} bytes")
            except Exception:
                pass
            frame = self._resize_frame_for_analysis(frame)
            self._last_image_hash = img_hash
            self._last_source_url = 'base64-object'
            on_frame(frame)
            return True
        except Exception as e:
            self.logger.warning(f"HA Polling: échec décodage contenu base64: {e}")
            return True
