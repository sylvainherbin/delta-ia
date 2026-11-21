"""Client HTTP : délai d'attente, nouvelles tentatives, User-Agent explicite, jeton GitHub optionnel."""

from __future__ import annotations

import os
import copy
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin

import idna  # dépendance de requests, qui encode l'hôte de la même façon (UTS 46)
import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from urllib3.util import connection as _connexion

from .modeles import ErreurReseau

USER_AGENT = "Delta-veille/0.1 (+https://github.com/sylvainherbin/delta-ia; veille personnelle)"
DELAI = (10, 30)  # connexion, lecture, en secondes
TENTATIVES = 3
ATTENTES = (2, 4)  # secondes entre les tentatives
TAILLE_MAX = 8 * 1024 * 1024  # 8 Mo, au-delà on refuse


def _cle_hote(hote: str, port: int) -> tuple[str, int]:
    return hote.strip("[]").rstrip(".").lower(), int(port)


def verifier_destination(url: str, autoriser_http: bool = False) -> tuple[tuple[str, int], tuple[str, ...]]:
    """Chaque requête et chaque redirection : schéma déclaré et toutes les IP routables. Rend ((hôte, port), IP contrôlées),
    dans l'ordre de la résolution et sans doublon : la connexion se fait à ces IP, l'une après l'autre, sans nouvelle
    résolution (un rebond DNS vers une adresse interne n'est pas suivi, même quand la première IP refuse)."""
    try:
        adresse = urlparse(url)
        if adresse.scheme not in (("https", "http") if autoriser_http else ("https",)):
            raise ValueError("schéma interdit")
        if not adresse.hostname or adresse.username is not None or adresse.password is not None:
            raise ValueError("hôte absent ou identifiants interdits")
        port = adresse.port or (443 if adresse.scheme == "https" else 80)
        hote = adresse.hostname
        if not hote.isascii():  # nom accentué : contrôlé et résolu sous la forme punycode que requests passe à la connexion
            hote = idna.encode(hote, uts46=True).decode("ascii")
        ips = socket.getaddrinfo(hote, port, type=socket.SOCK_STREAM)
        if not ips:
            raise ValueError("aucune adresse résolue")
        for _, _, _, _, sockaddr in ips:
            ip = ipaddress.ip_address(sockaddr[0])
            ip = getattr(ip, "ipv4_mapped", None) or ip
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                raise ValueError("adresse non routable")
        return _cle_hote(hote, port), tuple(dict.fromkeys(sockaddr[0] for *_, sockaddr in ips))
    except (ValueError, OSError) as exc:
        raise ErreurReseau(f"DESTINATION_REFUSEE : {exc}") from exc


class AdaptateurEpingle(HTTPAdapter):
    """Connexion aux IP contrôlées par `verifier_destination`, l'une après l'autre, sans nouvelle résolution. L'hôte reste
    celui de l'URL pour l'en-tête Host, le SNI et la vérification du certificat : seule l'adresse du socket est imposée.
    Sans IP contrôlée pour (hôte, port), la connexion est refusée ; si toutes refusent, la dernière erreur est levée."""

    def __init__(self) -> None:
        self.epingles: dict[tuple[str, int], tuple[str, ...]] = {}
        super().__init__()

    def init_poolmanager(self, *args, **kwargs) -> None:
        super().init_poolmanager(*args, **kwargs)
        epingles = self.epingles

        def classe(base):
            class Connexion(base):
                def _new_conn(self):
                    ips = epingles.get(_cle_hote(self.host, self.port))
                    if not ips:
                        raise NewConnectionError(self, f"DESTINATION_REFUSEE : aucune IP contrôlée pour {self.host}:{self.port}")
                    erreur = None
                    for ip in ips:  # repli sur les seules adresses déjà contrôlées, jamais une résolution neuve
                        try:
                            return _connexion.create_connection((ip, self.port), self.timeout, source_address=self.source_address,
                                                                socket_options=self.socket_options)
                        except socket.timeout as e:
                            erreur = ConnectTimeoutError(self, f"Connection to {self.host} ({ip}) timed out")
                            erreur.__cause__ = e
                        except OSError as e:
                            erreur = NewConnectionError(self, f"Failed to establish a new connection: {e}")
                            erreur.__cause__ = e
                    raise erreur
            return Connexion

        class Pool(HTTPConnectionPool):
            ConnectionCls = classe(HTTPConnection)

        class PoolTLS(HTTPSConnectionPool):
            ConnectionCls = classe(HTTPSConnection)

        self.poolmanager.pool_classes_by_scheme = {"http": Pool, "https": PoolTLS}


@dataclass
class Reponse:
    url: str
    statut: int
    content_type: str
    texte: str
    redirections: tuple = ()  # ((statut, url), …) des sauts suivis, dans l'ordre ; vide sans redirection

    @property
    def est_markdown(self) -> bool:
        return "markdown" in self.content_type or urlparse(self.url).path.endswith(".md")

    @property
    def est_json(self) -> bool:
        return "json" in self.content_type


class Client:
    """Un `requests.Session` avec la politique de robustesse de Delta."""

    def __init__(self, session: requests.Session | None = None, tentatives: int = TENTATIVES,
                 attentes: tuple[int, ...] = ATTENTES, dormir=time.sleep) -> None:
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.trust_env = False  # aucun proxy implicite ne contourne la résolution contrôlée
        self._epingles = None
        if isinstance(self.session, requests.Session):
            adaptateur = AdaptateurEpingle()
            self.session.mount("https://", adaptateur)
            self.session.mount("http://", adaptateur)
            self._epingles = adaptateur.epingles
        self._autoriser_http = False
        self.tentatives = tentatives
        self.attentes = attentes
        self._dormir = dormir
        self._jeton_github = os.environ.get("GITHUB_TOKEN")  # lu, jamais écrit ni journalisé

    def pour_source(self, source):
        client = copy.copy(self)
        client._autoriser_http = source.url.startswith("http://") or source.options.get("autoriser_http") is True
        return client

    def _obtenir(self, url: str, accept: str | None):
        historique = []
        for saut in range(11):
            cle, ips = verifier_destination(url, self._autoriser_http)
            if self._epingles is not None:
                self._epingles[cle] = ips  # chaque saut : la connexion suit la résolution contrôlée, jamais une seconde
            r = self.session.get(url, headers=self._entetes(url, accept), timeout=DELAI, allow_redirects=False, stream=True)
            if r.status_code not in (301, 302, 303, 307, 308):
                return r, tuple(historique)
            cible = r.headers.get("Location")
            historique.append((r.status_code, url))
            r.close()
            if not cible or saut == 10:
                raise ErreurReseau("DESTINATION_REFUSEE : redirection absente ou trop de sauts")
            url = urljoin(url, cible)
        raise ErreurReseau("DESTINATION_REFUSEE : trop de redirections")

    def _entetes(self, url: str, accept: str | None) -> dict:
        h = {"Accept": accept} if accept else {}
        if self._jeton_github and urlparse(url).hostname == "api.github.com":
            h["Authorization"] = f"Bearer {self._jeton_github}"
            h.setdefault("Accept", "application/vnd.github+json")
        return h

    @staticmethod
    def _lire_borne(r, url: str) -> bytes:
        """Lit le corps par morceaux et s'arrête net au-delà de TAILLE_MAX, sans tout télécharger."""
        morceaux: list[bytes] = []
        total = 0
        for m in r.iter_content(chunk_size=64 * 1024):
            total += len(m)
            if total > TAILLE_MAX:
                r.close()
                raise ErreurReseau(f"réponse trop volumineuse (plus de {TAILLE_MAX // (1024 * 1024)} Mo) pour {url}")
            morceaux.append(m)
        return b"".join(morceaux)

    def get(self, url: str, accept: str | None = None) -> Reponse:
        derniere = None
        for i in range(self.tentatives):
            try:
                r, historique = self._obtenir(url, accept)
                if r.status_code == 200:
                    contenu = self._lire_borne(r, url)
            except requests.RequestException as e:
                derniere = f"{type(e).__name__}: {str(e)[:200]}"
            else:
                if r.status_code == 200:
                    r._content = contenu  # décodage par requests (charset de l'en-tête, sinon détection)
                    if not r.encoding or r.encoding.lower() == "iso-8859-1":
                        r.encoding = r.apparent_encoding or "utf-8"
                    reponse = Reponse(r.url, r.status_code, r.headers.get("Content-Type", ""), r.text, historique)
                    r.close()
                    return reponse
                r.close()
                derniere = f"HTTP {r.status_code}"
                if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                    break  # inutile de réessayer un refus définitif
            if i < self.tentatives - 1:
                self._dormir(self.attentes[min(i, len(self.attentes) - 1)])
        raise ErreurReseau(f"{derniere} pour {url}")
