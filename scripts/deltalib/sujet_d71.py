"""D71, étape 2a : repère sans jugement ce qui touche au compte et aux quotas (limites, remises à zéro, crédits,
offres, tarifs, forfaits). Filtre commun au champ `sujet_d71` de la base de référence (catalogue.mettre_a_jour) et à la
détection des nouveaux articles d'aide (analyseur `index_articles`).

Mots entiers, insensibles à la casse et aux accents ; le trait d'union et la barre valent une espace. Le pluriel est
toléré (`s` ou `x` après chaque mot) : les titres d'aide disent « Enterprise plans », « limites », « remises à zéro ».
"""

from __future__ import annotations

import re
import unicodedata

MOTS_CLES = (
    # anglais
    "usage limit", "rate limit", "limit reset", "reset", "quota", "credits", "extra usage", "plan", "pricing", "price",
    "billing", "subscription", "promotion", "offer", "free trial",
    # français
    "limite", "remise à zéro", "réinitialisation", "crédits", "forfait", "tarif", "abonnement", "offre",
)

# Bruit connu : la fonction Finances de ChatGPT parle de « credit score » (23/09). Une expression exclue écarte l'ensemble du texte.
EXCLUSIONS = ("credit score", "score de crédit")


def _normaliser(texte: str) -> str:
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", sans_accent.lower())).strip()


def _motif(expression: str) -> re.Pattern:
    mots = [re.escape(m) + "(?:s|x)?" for m in _normaliser(expression).split()]
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(mots) + r"(?![a-z0-9])")


_MOTIFS = [(m, _motif(m)) for m in MOTS_CLES]
_EXCLUS = [_motif(m) for m in EXCLUSIONS]


def mots_trouves(*textes: str | None) -> list[str]:
    """Mots-clés présents dans l'ensemble des textes ; liste vide si rien ne correspond ou si une exclusion s'applique."""
    t = _normaliser(" \n ".join(x for x in textes if x))
    if not t or any(p.search(t) for p in _EXCLUS):
        return []
    return [mot for mot, p in _MOTIFS if p.search(t)]


def correspond(*textes: str | None) -> bool:
    return bool(mots_trouves(*textes))
