"""Types communs : élément brut, résultat d'une source, erreurs."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field

PRODUITS = ("claude", "claude-code", "chatgpt", "codex", "actu")
PERIMETRES = ("claude", "openai", "actu")
TYPES = ("github_changelog", "github_releases", "html", "rss", "json")
STATUTS = ("ok", "bloque", "a_valider", "desactive")
STATUTS_ACTIFS = ("ok", "a_valider")


class ErreurSource(Exception):
    """Erreur qui met une source en échec sans bloquer les autres."""


class ErreurReseau(ErreurSource):
    """Réponse HTTP non exploitable (délai, refus, code d'erreur)."""


class FormatInattendu(ErreurSource):
    """La réponse est arrivée mais sa structure n'est pas celle attendue.

    Un analyseur qui ne reconnaît aucune entrée doit lever cette erreur : jamais de liste vide silencieuse.
    """


def normaliser_titre(titre: str) -> str:
    """Minuscules, sans accents, sans ponctuation, espaces réduits : base stable pour le hachage."""
    t = unicodedata.normalize("NFKD", titre or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return t.strip()


def construire_id(produit: str, version: str | None, date_publication: str | None, titre: str) -> str:
    """Identifiant stable : produit + version (ou date, ou `nd`) + hachage du titre (SPEC §7.2)."""
    cle = version or date_publication or "nd"
    cle = re.sub(r"[^A-Za-z0-9.\-]+", "-", cle).strip("-")
    h = hashlib.sha1(normaliser_titre(titre).encode("utf-8")).hexdigest()[:10]
    return f"{produit}-{cle}-{h}"


@dataclass
class Element:
    """Format brut commun produit par tous les analyseurs."""

    produit: str
    titre: str
    version: str | None
    date_publication: str | None  # AAAA-MM-JJ ou None, jamais devinée
    url: str
    contenu: str
    source_id: str
    officielle: bool
    id: str = field(default="")

    def __post_init__(self) -> None:
        if self.produit not in PRODUITS:
            raise ValueError(f"produit inconnu : {self.produit!r}")
        if not self.titre or not self.titre.strip():
            raise FormatInattendu(f"élément sans titre (source {self.source_id})")
        if not self.url:
            raise FormatInattendu(f"élément sans URL (source {self.source_id}, titre {self.titre[:60]!r})")
        self.titre = self.titre.strip()
        if not self.id:
            self.id = construire_id(self.produit, self.version, self.date_publication, self.titre)

    def en_dict(self) -> dict:
        d = asdict(self)
        # ordre lisible dans le JSON
        ordre = ["id", "produit", "titre", "version", "date_publication", "url", "contenu", "source_id", "officielle"]
        return {k: d[k] for k in ordre}


@dataclass
class ResultatSource:
    """Ce qu'une source rapporte : ses éléments et, éventuellement, un échec partiel explicite."""

    elements: list[Element]
    partiel: str | None = None  # message si une partie de la source a échoué (ex. dates indisponibles)
