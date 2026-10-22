"""Liste X officielle (décisions de Sylvain du 22/10/2026) : lit le brut `raw/x-liste.json` que `scripts/capteur_x.py` écrit avant
le passage (relevé par l'API X, jeton du trousseau). Aucun accès réseau ici : `url` ne sert qu'à la référence. Interne seulement :
le texte des posts n'est jamais affiché ni archivé durablement (purge de fin de passage).

Options : `comptes` (liste de @comptes dont les posts relèvent de cette source), `validite_heures` (défaut 30 : un relevé plus ancien est une erreur, pas un résultat vide), `fichier`
(chemin du brut, défaut `raw/x-liste.json` à la racine du dépôt).
Ignorés (inscrits dans `vus` sans être traités) : les posts d'un autre compte, les reposts et les réponses à un autre compte.
Identifiant : `x-<identifiant du post>`. Date : lue dans l'identifiant du post (jour UTC), jamais devinée.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..capteur_x import FICHIER_BRUT, date_du_snowflake
from ..modeles import Element, ErreurSource, FormatInattendu, ResultatSource

RACINE = Path(__file__).resolve().parents[3]
VALIDITE_HEURES = 30


def _titre(compte: str, ident: str) -> str:
    """Pas d'extrait du texte dans le titre : le texte n'est que dans `contenu`, que la purge de fin de passage vide."""
    return f"{compte} — post du {date_du_snowflake(ident):%Y-%m-%d %H:%M} UTC"


def parser_brut(brut: dict, source, maintenant: datetime | None = None) -> ResultatSource:
    if not isinstance(brut, dict) or not isinstance(brut.get("posts"), list):
        raise FormatInattendu("brut du capteur X sans liste `posts`")
    maintenant = maintenant or datetime.now(timezone.utc)
    validite = float(source.options.get("validite_heures", VALIDITE_HEURES))
    try:
        age_h = (maintenant - datetime.fromisoformat(str(brut["releve_le"]))).total_seconds() / 3600
    except (KeyError, ValueError):
        raise FormatInattendu("brut du capteur X sans date de relevé lisible") from None
    if age_h > validite:
        raise ErreurSource(f"relevé X périmé ({age_h:.0f} h) : le capteur n'a pas tourné cette nuit (scripts/capteur_x.py)")
    statut = brut.get("statut")
    if statut != "ok":
        raise ErreurSource(f"capteur X : {statut} — {brut.get('message') or 'sans message'}")
    comptes = {str(c).lower() for c in source.options.get("comptes", [])}
    if not comptes:
        raise FormatInattendu("option `comptes` absente : la source ne saurait pas quels posts lui reviennent")
    elements: list[Element] = []
    ignores: list[str] = []
    for p in brut["posts"]:
        ident = f"x-{p['id']}"
        if str(p["compte"]).lower() not in comptes or p.get("type") in ("repost", "reponse"):
            ignores.append(ident)
            continue
        texte = str(p.get("texte") or "").strip()
        elements.append(Element(
            id=ident, produit=source.produit, titre=_titre(p["compte"], p["id"]), version=None,
            date_publication=date_du_snowflake(p["id"]).date().isoformat(), url=p["url"], contenu=texte,
            source_id=source.id, officielle=source.officielle))
    return ResultatSource(elements, ignores=ignores)


def analyser(source, client, borne: str | None = None) -> ResultatSource:
    chemin = Path(source.options.get("fichier") or RACINE / FICHIER_BRUT)
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErreurSource("relevé X absent : le capteur n'a pas tourné (scripts/capteur_x.py, lancé par la chaîne de 04:00)") from None
    except (OSError, ValueError) as e:
        raise FormatInattendu(f"brut du capteur X illisible : {e}") from None
    resultat = parser_brut(brut, source)
    resultat.plus_ancienne = borne   # la fenêtre du relevé est celle du capteur (posts nouveaux seulement) : pas de « trou » face à la borne
    resultat.partiel = brut.get("partiel") or None
    return resultat
