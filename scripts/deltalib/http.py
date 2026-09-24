"""Client HTTP : délai d'attente, nouvelles tentatives, User-Agent explicite, jeton GitHub optionnel."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from .modeles import ErreurReseau

USER_AGENT = "Delta-veille/0.1 (+https://github.com/sylvainherbin/delta-ia; veille personnelle)"
DELAI = (10, 30)  # connexion, lecture, en secondes
TENTATIVES = 3
ATTENTES = (2, 4)  # secondes entre les tentatives
TAILLE_MAX = 8 * 1024 * 1024  # 8 Mo, au-delà on refuse


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
        self.tentatives = tentatives
        self.attentes = attentes
        self._dormir = dormir
        self._jeton_github = os.environ.get("GITHUB_TOKEN")  # lu, jamais écrit ni journalisé

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
                r = self.session.get(url, headers=self._entetes(url, accept), timeout=DELAI, allow_redirects=True, stream=True)
                if r.status_code == 200:
                    contenu = self._lire_borne(r, url)
            except requests.RequestException as e:
                derniere = f"{type(e).__name__}: {str(e)[:200]}"
            else:
                if r.status_code == 200:
                    r._content = contenu  # décodage par requests (charset de l'en-tête, sinon détection)
                    if not r.encoding or r.encoding.lower() == "iso-8859-1":
                        r.encoding = r.apparent_encoding or "utf-8"
                    return Reponse(r.url, r.status_code, r.headers.get("Content-Type", ""), r.text,
                                   tuple((h.status_code, h.url) for h in r.history))
                r.close()
                derniere = f"HTTP {r.status_code}"
                if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                    break  # inutile de réessayer un refus définitif
            if i < self.tentatives - 1:
                self._dormir(self.attentes[min(i, len(self.attentes) - 1)])
        raise ErreurReseau(f"{derniere} pour {url}")
