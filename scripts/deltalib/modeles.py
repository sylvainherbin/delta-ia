"""Types communs : élément brut, résultat d'une source, erreurs."""

from __future__ import annotations

import hashlib
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


def empreinte_contenu(texte: str) -> str:
    """Empreinte du contenu, pour détecter une révision d'une entrée déjà vue (option `suivre_revisions`)."""
    return hashlib.sha1((texte or "").strip().encode("utf-8")).hexdigest()[:16]


def cle_version(version: str) -> tuple:
    """Clé de tri d'une version `x.y.z[-suffixe]` : les nombres d'abord, le suffixe ensuite."""
    base, _, suffixe = version.partition("-")
    nombres = tuple(int(n) if n.isdigit() else 0 for n in base.split("."))
    return (nombres, suffixe == "", suffixe)  # une pré-version passe avant la version finale


@dataclass
class Element:
    """Format brut commun produit par tous les analyseurs. `id` est la clé native de la source (D1)."""

    id: str
    produit: str
    titre: str
    version: str | None
    date_publication: str | None  # AAAA-MM-JJ ou None, jamais devinée
    url: str
    contenu: str
    source_id: str
    officielle: bool
    empreinte: str | None = None  # renseignée si la source suit les révisions
    revision: bool = False  # True si l'élément était connu mais son contenu a changé

    def __post_init__(self) -> None:
        if self.produit not in PRODUITS:
            raise ValueError(f"produit inconnu : {self.produit!r}")
        if not self.id or not str(self.id).strip():
            raise FormatInattendu(f"élément sans identifiant natif (source {self.source_id})")
        if not self.titre or not self.titre.strip():
            raise FormatInattendu(f"élément sans titre (source {self.source_id}, id {self.id!r})")
        if not self.url:
            raise FormatInattendu(f"élément sans URL (source {self.source_id}, id {self.id!r})")
        self.id = str(self.id).strip()
        self.titre = self.titre.strip()

    def en_dict(self) -> dict:
        d = asdict(self)
        ordre = ["id", "produit", "titre", "version", "date_publication", "url", "contenu", "source_id",
                 "officielle", "empreinte", "revision"]
        return {k: d[k] for k in ordre}


@dataclass
class ResultatSource:
    """Ce qu'une source rapporte : ses éléments et, éventuellement, un échec partiel explicite."""

    elements: list[Element]
    partiel: str | None = None  # message si une partie de la source a échoué (ex. dates indisponibles)
    ignores: list[str] = field(default_factory=list)  # identifiants d'historique à inscrire sans les traiter (D3)
    plus_ancienne: str | None = None  # date la plus ancienne vue par l'analyseur, pour la détection de trou (D4)
