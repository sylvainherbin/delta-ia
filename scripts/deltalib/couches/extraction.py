"""Extraction couvrant tous les systèmes (conception §1.2, lot L2) : la référence commune ne dépend pas du profil.

`profil.yaml` (`base.exclure_systemes`) filtre aujourd'hui l'extraction de la base de l'instance productrice : une fiche
propre à Windows ou à macOS n'entre pas dans `docs/data/kb`. Ici, les mêmes extracteurs déterministes relisent les copies
locales des pages de documentation (`raw/kb/`) **sans aucun système exclu** ; chaque fiche porte les systèmes auxquels la
documentation la borne (`systemes`, null si elle n'en désigne aucun seul), et c'est l'instance qui filtre. Aucun appel
réseau ni modèle ; le profil n'est pas lu (la liste en cours de l'extracteur est remplacée le temps de l'extraction, puis
rendue).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import classement as cl
from ..kb import catalogue, extracteurs
from ..kb import systemes as mod_systemes
from ..kb.documentation import ErreurDocumentation, charger_documentation

SYSTEMES = tuple(mod_systemes.SYSTEMES)  # windows, macos, linux
_MOTIFS_VARIANTES = {s: re.compile(m, re.I) for s, m in extracteurs._MOTIFS_SYSTEMES.items()}


@dataclass
class Extraction:
    entrees: dict[str, list[dict]] = field(default_factory=dict)  # périmètre → champs C des fiches extraites
    extraites: dict[str, set[str]] = field(default_factory=dict)  # périmètre → documentations lues en entier
    couverture: dict[str, dict] = field(default_factory=dict)  # périmètre → comptes et documentations en échec


def systemes_de(nom: str, description: str | None, usage: str | None = None) -> list[str] | None:
    """Systèmes auxquels la documentation borne une fiche (« Windows only », nom `…-powershell-…`, raccourci `Cmd+K`) ;
    None quand elle n'en désigne aucun seul (fiche multi-systèmes ou sans mention)."""
    propres = sorted(s for s in SYSTEMES if mod_systemes.systeme_exclu_de(nom, description or "", [s]) == s)
    if propres:
        return propres
    variantes = [v.strip() for v in re.split(r",?\s+or\s+|,\s+", usage or "") if v.strip()]
    if not variantes or any(re.search(r"Linux", v) for v in variantes):
        return None
    par_variante = [{s for s, rx in _MOTIFS_VARIANTES.items() if rx.search(v)} for v in variantes]
    if all(par_variante):
        return sorted(set().union(*par_variante))
    return None


def _fiche_c(entree: dict) -> dict:
    """Champs C d'une fiche du catalogue, selon la table de classement (même liste positive que l'import)."""
    return {k: v for k, v in entree.items() if cl.classer("kb_catalogue", f"entrees[].{k}") == cl.COMMUN}


def extraire_tous_systemes(brut: Path, sources: Path, jour: str | None = None) -> Extraction:
    """Fiches de toutes les documentations actives de `sources`, lues dans `<brut>/raw/kb/`, sans filtre de système."""
    res = Extraction()
    try:
        docs = [d for d in charger_documentation(sources) if d.active]
    except (ErreurDocumentation, OSError) as e:
        res.couverture["_"] = {"statut": "indisponible", "motif": f"documentation illisible : {type(e).__name__}"}
        return res
    precedents = extracteurs._systemes_exclus
    extracteurs.definir_systemes_exclus([])
    try:
        for perimetre in sorted({d.perimetre for d in docs}):
            ds = [d for d in docs if d.perimetre == perimetre]
            extraites, ok, echecs = catalogue.extraire(brut, ds)
            res.entrees[perimetre] = [
                {**_fiche_c(catalogue.nouvelle_entree(x, jour or "")), "systemes": systemes_de(x.nom, x.description_source, x.usage)}
                for x in extraites]
            res.extraites[perimetre] = set(ok)
            res.couverture[perimetre] = {
                "documentations": len(ds), "lues": len(ok), "fiches": len(extraites),
                "echecs": sorted({e["doc"] for e in echecs})}
    finally:
        extracteurs.definir_systemes_exclus(precedents)
    return res
