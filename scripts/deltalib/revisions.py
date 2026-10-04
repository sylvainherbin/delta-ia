"""D76 : cache local des textes validés, amorçage par l'historique et diff de phrases."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from .modeles import PERIMETRES, empreinte_contenu
from .textes import normaliser_contenu

MAX_PHRASES = 20
MAX_CARACTERES = 1000
SEUIL_MODIFICATION = 0.6


def chemin_cache(racine: Path, perimetre: str, ident: str) -> Path:
    """Les ids natifs peuvent être des URL : aucun chemin ne doit sortir de raw/revisions/."""
    if perimetre not in PERIMETRES:
        raise ValueError(f"périmètre inconnu : {perimetre}")
    nom = ident if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,179}", ident) else "id-" + hashlib.sha256(ident.encode()).hexdigest()
    return racine / "raw" / "revisions" / perimetre / f"{nom}.md"


def ecrire_cache(racine: Path, perimetre: str, ident: str, texte: str) -> None:
    chemin = chemin_cache(racine, perimetre, ident)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(".md.tmp")
    temporaire.write_text(normaliser_contenu(texte).strip(), encoding="utf-8")
    temporaire.replace(chemin)


def _correspond(texte: str, empreinte: str) -> bool:
    # Migration : l'état pré-D76 hachait encore les URL signées. Le texte brut de
    # l'archive permet de retrouver cette version sans deviner le texte précédent.
    return empreinte_contenu(texte) == empreinte or hashlib.sha1(texte.strip().encode()).hexdigest()[:16] == empreinte


def textes_precedents(racine: Path, perimetre: str, empreintes: dict[str, str]) -> dict[str, str]:
    """Lecture seule, y compris en dry-run ; n'accepte qu'un texte correspondant à l'état.

    Un cache resté en avance après un rétablissement de state/ par l'orchestrateur
    est écarté. Les archives sont parcourues une seule fois, de la plus récente à la plus ancienne.
    """
    textes = {}
    for ident, empreinte in empreintes.items():
        try:
            texte = chemin_cache(racine, perimetre, ident).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if _correspond(texte, empreinte):
            textes[ident] = normaliser_contenu(texte).strip()
    manquants = set(empreintes) - textes.keys()
    if not manquants:
        return textes

    def ordre(chemin):
        suffixe = chemin.stem.removeprefix(f"{perimetre}-nouveautes-").split("-")
        return chemin.parent.name, suffixe[0], int(suffixe[1]) if len(suffixe) == 2 and suffixe[1].isdigit() else 1

    archives = (racine / "raw" / "historique").glob(f"????-??-??/{perimetre}-nouveautes-*.json")
    for chemin in sorted(archives, key=ordre, reverse=True):
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(brut, dict) or brut.get("perimetre") != perimetre:
            continue
        suivis, nouveautes = brut.get("contenus_suivis"), brut.get("nouveautes")
        candidats = dict(suivis) if isinstance(suivis, dict) else {}
        candidats.update({e["id"]: e["contenu"] for e in (nouveautes if isinstance(nouveautes, list) else [])
                          if isinstance(e, dict) and e.get("id") and isinstance(e.get("contenu"), str)})
        for ident in sorted(manquants & candidats.keys()):
            texte = candidats[ident]
            if isinstance(texte, str) and _correspond(texte, empreintes[ident]):
                textes[ident] = normaliser_contenu(texte).strip()
                manquants.remove(ident)
        if not manquants:
            break
    return textes


_MOIS = (r"(?:jan(?:uary|vier|v\.)?|f[eé]b(?:ruary|\.)?|f[eé]v(?:rier|r?\.)?|mar(?:ch|s|\.)?|"
         r"apr(?:il|\.)?|avr(?:il|\.)?|may|mai|jun(?:e|\.)?|juin|jul(?:y|\.)?|juillet|"
         r"aug(?:ust|\.)?|ao[uû]t|sep(?:tember|tembre|t?\.)?|oct(?:ober|obre|\.)?|"
         r"nov(?:ember|embre|\.)?|d[eé]c(?:ember|embre|\.)?)")
_DATE = (rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{4}}|"
         rf"{_MOIS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|"
         rf"\d{{1,2}}(?:er)?\s+{_MOIS}(?:\s+\d{{4}})?)")
_RELATIVE = (r"(?:today|yesterday|just now|this (?:week|month)|"
             r"(?:(?:over|about|almost|less than)\s+)?(?:a|an|\d+)\s+"
             r"(?:minute|hour|day|week|month|year)s?\s+ago|"
             r"aujourd['’]hui|hier|à l['’]instant|il y a\s+(?:(?:environ|plus de|moins de)\s+)?"
             r"(?:un|une|\d+)\s+(?:minute|heure|jour|semaine|mois|an|année)s?)")
_MISE_A_JOUR = re.compile(
    rf"^(?:{_DATE}|(?:last\s+updated|updated|(?:derni[eè]re\s+)?mis(?:e)?\s+[àa]\s+jour)"
    rf"\s*:?\s*(?:(?:on|le)\s+)?(?:{_DATE}|{_RELATIVE}))[.!]?$", re.I)
_IMAGE = re.compile(r"!\[[^\]]*\]\((?:[^()\n]|\([^()\n]*\))*\)|!\[[^\]]*\]\[[^\]]*\]|<img\b[^>]*>", re.I)
_STRUCTURE = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+|\|)")


def phrases(texte: str) -> list[str]:
    """Écarte le balisage et les images ; les retours de ligne d'un paragraphe sont des blancs.

    Titres, listes et tableaux gardent une frontière même sans ponctuation ; les dates
    de mise à jour sont isolées pour ne pas masquer une phrase métier adjacente.
    """
    texte = _IMAGE.sub("", normaliser_contenu(texte))
    texte = re.sub(r"(\*\*|__|~~|`)(.*?)\1", r"\2", texte)
    texte = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", texte)
    blocs, courant = [], []

    def vider():
        if courant:
            blocs.append(normaliser_contenu(" ".join(courant), reduire_blancs=True))
            courant.clear()

    for ligne in texte.splitlines():
        if not ligne.strip() or re.fullmatch(r"\s*[-_*| :`~]{3,}\s*", ligne):
            vider()
            continue
        structure = bool(_STRUCTURE.match(ligne))
        ligne = _STRUCTURE.sub("", ligne).strip().strip("|").strip()
        if structure or _MISE_A_JOUR.fullmatch(ligne):
            vider()
            blocs.append(normaliser_contenu(ligne, reduire_blancs=True))
        else:
            courant.append(ligne)
    vider()
    return [p for b in blocs for p in re.split(r"(?<=[.!?])\s+(?=[^\W\d]|[\"«“])", b) if p]


def comparer_phrases(avant: str, apres: str) -> dict:
    anciennes, nouvelles = phrases(avant), phrases(apres)
    retirees, ajoutees = [], []
    for tag, a, b, c, d in SequenceMatcher(None, anciennes, nouvelles, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            retirees.extend(p for p in anciennes[a:b] if not _MISE_A_JOUR.fullmatch(p))
        if tag in ("insert", "replace"):
            ajoutees.extend(p for p in nouvelles[c:d] if not _MISE_A_JOUR.fullmatch(p))
    proches = []
    for i, retiree in enumerate(retirees):
        for j, ajoutee in enumerate(ajoutees):
            m = SequenceMatcher(None, retiree, ajoutee, autojunk=False)
            if m.quick_ratio() >= SEUIL_MODIFICATION:
                ratio = m.ratio()
                if ratio >= SEUIL_MODIFICATION:
                    proches.append((-ratio, i, j))
    pris_avant, pris_apres, modifiees = set(), set(), []
    for _, i, j in sorted(proches):
        if i in pris_avant or j in pris_apres:
            continue
        pris_avant.add(i)
        pris_apres.add(j)
        if retirees[i] != ajoutees[j]:
            modifiees.append((i, {"avant": retirees[i], "apres": ajoutees[j]}))
    changements = {
        "ajoutees": [p for j, p in enumerate(ajoutees) if j not in pris_apres],
        "retirees": [p for i, p in enumerate(retirees) if i not in pris_avant],
        "modifiees": [p for _, p in sorted(modifiees)],
    }
    tronque = any(len(liste) > MAX_PHRASES for liste in changements.values())

    def borner(phrase):
        nonlocal tronque
        if len(phrase) > MAX_CARACTERES:
            tronque = True
            return phrase[:MAX_CARACTERES - 1] + "…"
        return phrase

    for cle, liste in changements.items():
        changements[cle] = [{k: borner(v) for k, v in p.items()} if isinstance(p, dict) else borner(p)
                            for p in liste[:MAX_PHRASES]]
    if tronque:
        changements["tronque"] = True
    return changements
