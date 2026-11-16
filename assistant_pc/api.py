"""Client de l'API du serveur Chat IA. Chaque requête porte X-Client: pc (et le jeton une fois connecté).

HTTPS : le certificat maison est épinglé par son empreinte SHA-256. Avant toute requête, on lit le
certificat présenté (sans rien envoyer), on compare l'empreinte, puis ce certificat-là devient la seule
autorité de confiance du contexte TLS. Une empreinte différente : connexion refusée, sans alternative.
"""
import hashlib
import json
import socket
import ssl
import threading
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import VERSION, normalize_fingerprint

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENTS = 10


class ApiError(Exception):
    """Erreur à montrer telle quelle à l'utilisateur."""


class Unreachable(ApiError):
    pass


class AuthError(ApiError):
    pass


class CertMismatch(ApiError):
    pass


def fingerprint_of(der: bytes) -> str:
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 64, 2))


def unreachable_message(host: str, port: int) -> str:
    return (f"Serveur injoignable ({host}:{port}).\n"
            "Vérifiez que le VPN est connecté, puis réessayez.")


class Api:
    def __init__(self, base_url: str, fingerprint: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        parts = urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ApiError("Adresse du serveur invalide (exemple : https://192.168.1.41:8443)")
        self.https = parts.scheme == "https"
        self.host = parts.hostname
        self.port = parts.port or (443 if self.https else 80)
        self.fingerprint = normalize_fingerprint(fingerprint)
        self.token = token
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()
        self._current_response: httpx.Response | None = None

    # ---------- Connexion sûre ----------

    def _pinned_context(self) -> ssl.SSLContext:
        if not self.fingerprint:
            raise CertMismatch("Aucune empreinte de certificat valide dans les paramètres : connexion refusée.")
        probe = ssl.create_default_context()
        probe.check_hostname = False
        probe.verify_mode = ssl.CERT_NONE  # seulement pour lire le certificat ; rien n'est envoyé sur cette connexion
        try:
            with socket.create_connection((self.host, self.port), timeout=5) as sock:
                with probe.wrap_socket(sock, server_hostname=self.host) as tls:
                    der = tls.getpeercert(binary_form=True)
        except ssl.SSLError as e:
            raise ApiError(f"Échec de la connexion chiffrée : {e.reason or e}")
        except OSError:
            raise Unreachable(unreachable_message(self.host, self.port))
        seen = fingerprint_of(der)
        if seen != self.fingerprint:
            raise CertMismatch(
                "Le certificat du serveur ne correspond pas à l'empreinte enregistrée : connexion refusée.\n\n"
                f"Attendue : {self.fingerprint}\nReçue : {seen}\n\n"
                "Si le certificat a été renouvelé, mettez à jour l'empreinte dans les paramètres "
                "après l'avoir vérifiée sur le serveur.")
        ctx = ssl.create_default_context(cadata=der)  # ce certificat seul, pas les autorités de Windows
        ctx.check_hostname = False  # l'épinglage remplace la vérification du nom
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        return ctx

    def client(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                verify = self._pinned_context() if self.https else False
                self._client = httpx.Client(
                    base_url=self.base_url,
                    verify=verify,
                    timeout=httpx.Timeout(connect=6, read=60, write=120, pool=10),
                    headers={"X-Client": "pc", "User-Agent": f"AssistantPC/{VERSION}"},
                    trust_env=False,  # pas de proxy système : rien ne passe ailleurs que vers le serveur
                    follow_redirects=False,
                )
            return self._client

    def close(self):
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _request(self, method: str, path: str, auth: bool = True, headers: dict | None = None, **kw) -> httpx.Response:
        try:
            r = self.client().request(method, path, headers={**(self._headers() if auth else {}), **(headers or {})}, **kw)
        except ApiError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise Unreachable(unreachable_message(self.host, self.port))
        except httpx.TimeoutException:
            raise ApiError("Le serveur met trop de temps à répondre.")
        except httpx.HTTPError as e:
            raise ApiError(f"Erreur réseau : {e}")
        self._check(r)
        return r

    @staticmethod
    def _detail(r: httpx.Response) -> str:
        try:
            detail = r.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str) and detail:
            return detail
        return f"Erreur du serveur ({r.status_code})"

    def _check(self, r: httpx.Response):
        if r.status_code == 401:
            raise AuthError(self._detail(r) if "login" in r.request.url.path else
                            "Session expirée ou jeton révoqué : reconnectez-vous.")
        if r.status_code >= 400:
            raise ApiError(self._detail(r))

    # ---------- Routes ----------

    def ping(self) -> str:
        """Test de connexion : le serveur répond-il, et le jeton est-il valide ?"""
        try:
            r = self.client().get("/api/models", headers=self._headers())
        except ApiError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise Unreachable(unreachable_message(self.host, self.port))
        except httpx.HTTPError as e:
            raise ApiError(f"Erreur réseau : {e}")
        if r.status_code == 401:
            return "Serveur joignable." + (" Jeton refusé : reconnectez-vous." if self.token else "")
        self._check(r)
        return "Serveur joignable, connecté."

    def login(self, username: str, password: str, device: str) -> dict:
        r = self._request("POST", "/api/app/login", auth=False,
                          json={"username": username, "password": password, "device": device})
        return r.json()

    def logout(self):
        self._request("DELETE", "/api/app/token")

    def models(self) -> list[dict]:
        return self._request("GET", "/api/models").json()

    def new_conversation(self, model: str) -> int:
        return self._request("POST", "/api/conversations", json={"model": model}).json()["id"]

    def conversation(self, cid: int) -> dict:
        return self._request("GET", f"/api/conversations/{cid}").json()

    def recent(self) -> list[dict]:
        """Conversations créées par les applis (enregistrées ou non), les plus récentes d'abord."""
        return self._request("GET", "/api/conversations", params={"origin": "appli"}).json()

    def saved(self) -> list[dict]:
        return self._request("GET", "/api/app/saved").json()

    def save(self, cid: int, where: str):
        self._request("POST", f"/api/conversations/{cid}/save", json={"where": where})

    def upload(self, path: Path) -> dict:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ApiError("Fichier trop lourd (25 Mo maximum)")
            data = path.read_bytes()
        except OSError as e:
            raise ApiError(f"Lecture du fichier impossible : {e.strerror or e}")
        return self.upload_bytes(data, path.name)

    def upload_bytes(self, data: bytes, name: str) -> dict:
        if not data:
            raise ApiError("Fichier vide")
        if len(data) > MAX_FILE_BYTES:
            raise ApiError("Fichier trop lourd (25 Mo maximum)")
        return self._request("POST", "/api/attachments", params={"name": name}, content=data,
                             headers={"Content-Type": "application/octet-stream"}).json()

    def transcribe(self, wav: bytes, prompt: str = "") -> str:
        """Dictée : un segment WAV 16 kHz mono, transcrit par le serveur."""
        params = {"prompt": prompt} if prompt else {}
        r = self._request("POST", "/api/transcribe", params=params, content=wav,
                          headers={"Content-Type": "audio/wav"}, timeout=40)
        return str(r.json().get("text", ""))

    def send(self, cid: int, payload: dict, stop: threading.Event):
        """Génère les événements du flux (un objet JSON par ligne) jusqu'à la fin ou l'arrêt demandé."""
        timeout = httpx.Timeout(connect=6, read=600, write=120, pool=10)  # chargement du modèle, longue réflexion
        try:
            with self.client().stream("POST", f"/api/conversations/{cid}/messages", json=payload,
                                      headers=self._headers(), timeout=timeout) as r:
                if r.status_code >= 400:
                    r.read()
                    self._check(r)
                self._current_response = r
                for line in r.iter_lines():
                    if stop.is_set():
                        return
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        yield event
        except ApiError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise Unreachable(unreachable_message(self.host, self.port))
        except httpx.ReadTimeout:
            raise ApiError("Le serveur ne répond plus (aucune donnée depuis 10 minutes).")
        except httpx.HTTPError as e:
            if stop.is_set():
                return
            raise ApiError(f"Connexion interrompue : {e}. Le VPN est-il toujours connecté ?")
        finally:
            self._current_response = None

    def abort_stream(self):
        r = self._current_response
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
