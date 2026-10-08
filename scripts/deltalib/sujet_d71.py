"""D71, étape 2a : repère sans jugement ce qui touche au compte et aux quotas (limites, remises à zéro, crédits,
offres, tarifs, forfaits). Deux listes de mots-clés, deux usages :

- `MOTS_CLES_INDEX` : titres et descriptions de l'index d'un centre d'aide (analyseur `index_articles`). Titres courts
  et ciblés : les mots à double sens (`limit`, `plan`, `reset`, `offer`) y rattrapent des articles utiles.
- `MOTS_CLES_BASE` : fiches de la base de référence (`sujet_d71` de catalogue.mettre_a_jour). Nom, usage et description
  d'origine y mêlent réglages techniques et texte libre : seulement des expressions sans double sens.

Mots entiers, insensibles à la casse et aux accents ; le trait d'union et la barre valent une espace. Le pluriel est
toléré (`s` ou `x` après chaque mot) : les titres d'aide disent « Enterprise plans », « limits », « remises à zéro ».
"""

from __future__ import annotations

import re
import unicodedata

# Mots sans double sens, communs aux deux listes.
_COMMUNS = (
    # anglais
    "usage limit", "rate limit", "limit reset", "extra usage", "free trial", "quota", "credits", "billing", "subscription",
    "pricing", "price", "promotion",
    # français
    "remise à zéro", "réinitialisation", "crédits", "forfait", "tarif", "abonnement",
)

MOTS_CLES_BASE = _COMMUNS

MOTS_CLES_INDEX = _COMMUNS + (
    "limit", "reset", "plan", "offer",  # double sens dans une fiche technique, ciblés dans un titre d'article d'aide
    "limite", "offre",
)

# Bruit connu : la fonction Finances de ChatGPT parle de « credit score » (23/09) ; « plan mode » (commande /plan de Claude
# Code) ne parle pas de forfait. Une exclusion porte sur l'expression seulement : elle est retirée du texte avant la recherche,
# un texte qui contient aussi un vrai mot-clé reste retenu. « usage » seul n'est pas un mot-clé (il ramène la Usage Policy).
EXCLUSIONS = ("credit score", "score de crédit", "plan mode", "mode plan")

# R5 (valider.py) seulement : « forfait » dit la disponibilité d'une fonction (« sur tous les forfaits payants »), pas un sujet de
# compte. Même mécanisme que EXCLUSIONS, mais hors de la détection de la base et de l'index (`mots_trouves_base` ne les connaît pas).
EXCLUSIONS_DISPONIBILITE = ("tous les forfaits", "sur les forfaits", "pour les forfaits", "dans les forfaits")


def _normaliser(texte: str) -> str:
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", sans_accent.lower())).strip()


def _motif(expression: str) -> re.Pattern:
    mots = [re.escape(m) + "(?:s|x)?" for m in _normaliser(expression).split()]
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(mots) + r"(?![a-z0-9])")


_MOTIFS_BASE = [(m, _motif(m)) for m in MOTS_CLES_BASE]
_MOTIFS_INDEX = [(m, _motif(m)) for m in MOTS_CLES_INDEX]
_EXCLUS = [_motif(m) for m in EXCLUSIONS]
_EXCLUS_DISPONIBILITE = [_motif(m) for m in EXCLUSIONS_DISPONIBILITE]


def _trouves(motifs: list, textes: tuple, exclus: list | None = None) -> list[str]:
    t = _normaliser(" \n ".join(x for x in textes if x))
    for exclusion in _EXCLUS if exclus is None else exclus:
        t = exclusion.sub(" ", t)
    return [mot for mot, p in motifs if p.search(t)]


def mots_trouves_index(*textes: str | None) -> list[str]:
    """Mots-clés de l'index d'aide présents dans les textes, une fois les expressions exclues retirées."""
    return _trouves(_MOTIFS_INDEX, textes)


def mots_trouves_base(*textes: str | None) -> list[str]:
    """Mots-clés de la base de référence présents dans les textes, une fois les expressions exclues retirées."""
    return _trouves(_MOTIFS_BASE, textes)


def mots_trouves_element(*textes: str | None) -> list[str]:
    """Mots-clés de la base présents dans un élément publié, hors disponibilité d'une fonction « sur tous les forfaits » (R5)."""
    return _trouves(_MOTIFS_BASE, textes, _EXCLUS + _EXCLUS_DISPONIBILITE)


def correspond_index(*textes: str | None) -> bool:
    return bool(mots_trouves_index(*textes))


def correspond_base(*textes: str | None) -> bool:
    return bool(mots_trouves_base(*textes))
