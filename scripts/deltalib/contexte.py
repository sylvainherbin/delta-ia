"""D64 : empreintes par section de CONTEXTE.md.

CONTEXTE.md est découpé à chaque titre `##` ou `###`. Une section va de son titre au titre suivant, quel que soit
son niveau : un `###` a sa propre empreinte, distincte de son `##` parent. Le texte avant le premier `##` forme la
section `preambule`. Clé : le numéro du titre (`2`, `2.2`) ; à défaut, `<clé du parent>/<titre normalisé>`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

_RE_TITRE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_RE_NUMERO = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")
SECTION_PROJETS = "2"  # D64 : un nouveau `###` sous « ## 2. Projets » déclenche une repasse des « ignorer »


def _normaliser(titre: str) -> str:
    t = re.sub(r"\[[^\]]*\]", "", titre)  # étiquettes [observé], [déclaré]…
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "section"


def sections(texte: str) -> dict[str, dict]:
    """{clé: {titre, niveau, parent, sha1}} dans l'ordre du fichier."""
    lignes = texte.splitlines()
    res: dict[str, dict] = {}
    courant, debut, parent_2 = ("preambule", "(préambule)", 1, None), 0, None

    def fermer(fin: int) -> None:
        cle, titre, niveau, parent = courant
        corps = "\n".join(l.rstrip() for l in lignes[debut:fin]).strip()
        res[cle] = {"titre": titre, "niveau": niveau, "parent": parent,
                    "sha1": hashlib.sha1(corps.encode("utf-8")).hexdigest()}

    for i, l in enumerate(lignes):
        m = _RE_TITRE.match(l)
        if not m:
            continue
        fermer(i)
        niveau, titre = len(m.group(1)), m.group(2)
        num = _RE_NUMERO.match(titre)
        if niveau == 2:
            cle = num.group(1) if num else _normaliser(titre)
            parent_2, parent = cle, None
        else:
            parent = parent_2
            cle = num.group(1) if num else f"{parent_2 or 'preambule'}/{_normaliser(titre)}"
        base, k = cle, 2
        while cle in res:
            cle, k = f"{base}~{k}", k + 1
        courant, debut = (cle, titre, niveau, parent), i
    fermer(len(lignes))
    return res


def empreintes(racine) -> dict[str, str]:
    """{clé: sha1} du CONTEXTE.md courant ; vide s'il est absent."""
    chemin = Path(racine) / "CONTEXTE.md"
    try:
        return {k: v["sha1"] for k, v in sections(chemin.read_text(encoding="utf-8")).items()}
    except OSError:
        return {}


def projets(racine) -> list[str]:
    chemin = Path(racine) / "CONTEXTE.md"
    try:
        s = sections(chemin.read_text(encoding="utf-8"))
    except OSError:
        return []
    return [k for k, v in s.items() if v["parent"] == SECTION_PROJETS]


def resoudre(racine, cles: list[str]) -> dict[str, str]:
    """Liste de clés citées -> {clé: sha1 actuel}. Une clé inconnue est une erreur (ValueError)."""
    courantes = empreintes(racine)
    inconnues = [c for c in cles if c not in courantes]
    if inconnues:
        raise ValueError(f"sections inconnues dans CONTEXTE.md : {inconnues} (connues : {sorted(courantes)})")
    return {c: courantes[c] for c in cles}


def est_perime(contexte_sections: dict | None, courantes: dict[str, str]) -> bool | None:
    """True si une section citée a changé ou disparu ; False sinon ; None pour un commentaire antérieur à D64."""
    if contexte_sections is None:
        return None
    return any(courantes.get(k) != v for k, v in contexte_sections.items())
