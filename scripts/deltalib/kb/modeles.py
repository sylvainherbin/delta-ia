"""Types de la base de référence (SPEC §7.4, D40, D41)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

CATEGORIES = ("fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis")
CATEGORIES_COURTES = ("parametres", "raccourcis")  # D41 : gabarit court
PRODUITS_PAR_PERIMETRE = {"claude": ("claude", "claude-code"), "openai": ("chatgpt", "codex")}
PERIMETRE_DU_PRODUIT = {p: per for per, ps in PRODUITS_PAR_PERIMETRE.items() for p in ps}
STATUTS_USAGE = ("utilise", "non_utilise", "inconnu")
VERDICTS = ("utiliser", "tester", "ignorer")
NATURES_USAGE = ("syntaxe", "etapes")  # D49


def gabarit_de(categorie: str) -> str:
    return "court" if categorie in CATEGORIES_COURTES else "complet"


def slug(texte: str, longueur: int = 80) -> str:
    t = unicodedata.normalize("NFKD", texte or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:longueur].strip("-") or "sans-nom"


@dataclass
class EntreeExtraite:
    """Ce que l'extraction sait d'une entrée, sans aucun modèle (D40, étape 1)."""

    produit: str
    categorie: str
    nom: str
    usage: str
    description_source: str
    url: str
    libelle: str
    origine: str  # identifiant de la documentation dans sources.yaml
    groupe: str | None = None  # section de la page, pour lire et découper
    cle: str | None = None  # base du slug si différente du nom
    usage_nature: str = "syntaxe"  # D49 : `syntaxe` ou `etapes` (page narrative)
    id: str = field(default="")

    def __post_init__(self) -> None:
        if self.categorie not in CATEGORIES:
            raise ValueError(f"catégorie inconnue : {self.categorie!r}")
        if self.usage_nature not in NATURES_USAGE:
            raise ValueError(f"usage_nature inconnue : {self.usage_nature!r}")
        if self.produit not in PERIMETRE_DU_PRODUIT:
            raise ValueError(f"produit inconnu : {self.produit!r}")
        self.nom = (self.nom or "").strip()
        self.usage = (self.usage or "").strip("\n")
        self.description_source = (self.description_source or "").strip()
        if not self.id:
            self.id = f"{self.produit}-{self.categorie}-{slug(self.cle or self.nom)}"
