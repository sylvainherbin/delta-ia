"""D64-bis : sections de CONTEXTE.md identifiées par ctx-id, empreintes et péremption.

- Chaque titre `#`, `##` ou `###` est suivi (première ligne non vide) d'un commentaire `<!-- ctx-id: X -->` : X est la
  clé stable de la section, jamais son numéro ni son titre. Un titre sans ctx-id, un ctx-id en double ou du texte
  avant le premier titre sont des erreurs (`ContexteInvalide`).
- Le sha1 d'une section porte sur son propre corps, du titre jusqu'au titre suivant quel que soit son niveau, sans la
  ligne de titre ni les lignes ctx-id : renommer une section ne périme rien.
- Une ligne `<!-- ctx-id-deprecie: X -->` déclare X déprécié : une entrée qui le cite est périmée.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_RE_TITRE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_RE_CTX = re.compile(r"^\s*<!--\s*ctx-id:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
_RE_DEPRECIE = re.compile(r"^\s*<!--\s*ctx-id-deprecie:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
PREFIXE_PROJET = "projet."
PROJET_HORS = {"projet.vue-ensemble"}  # la section « ## 2. Projets » elle-même n'est pas un projet
POURQUOI_MAX = 160
SHA1_VIDE = hashlib.sha1(b"").hexdigest()  # corps vide : section-titre, citer une sous-section


class ContexteInvalide(ValueError):
    pass


def analyser(texte: str) -> tuple[dict[str, dict], set[str]]:
    """({ctx-id: {titre, niveau, parent, sha1}}, {ctx-id dépréciés})."""
    lignes = texte.splitlines()
    titres = [(i, len(m.group(1)), m.group(2)) for i, l in enumerate(lignes) if (m := _RE_TITRE.match(l))]
    deprecies = {m.group(1) for l in lignes if (m := _RE_DEPRECIE.match(l))}
    if titres and any(l.strip() for l in lignes[:titres[0][0]]):
        raise ContexteInvalide("texte avant le premier titre : il n'appartient à aucune section")
    res: dict[str, dict] = {}
    pile: list[tuple[int, str]] = []
    for k, (i, niveau, titre) in enumerate(titres):
        fin = titres[k + 1][0] if k + 1 < len(titres) else len(lignes)
        j = i + 1
        while j < fin and not lignes[j].strip():
            j += 1
        m = _RE_CTX.match(lignes[j]) if j < fin else None
        if not m:
            raise ContexteInvalide(f"ligne {i + 1} : titre sans ctx-id juste dessous : {titre!r}")
        cle = m.group(1)
        if cle in res:
            raise ContexteInvalide(f"ctx-id en double : {cle}")
        corps = [l.rstrip() for n, l in enumerate(lignes[i + 1:fin], start=i + 1)
                 if n != j and not _RE_DEPRECIE.match(l) and not _RE_CTX.match(l)]
        while pile and pile[-1][0] >= niveau:
            pile.pop()
        res[cle] = {"titre": titre, "niveau": niveau, "parent": pile[-1][1] if pile else None,
                    "sha1": hashlib.sha1("\n".join(corps).strip().encode("utf-8")).hexdigest()}
        pile.append((niveau, cle))
    doublons = deprecies & set(res)
    if doublons:
        raise ContexteInvalide(f"ctx-id à la fois actif et déprécié : {sorted(doublons)}")
    return res, deprecies


def sections(texte: str) -> dict[str, dict]:
    return analyser(texte)[0]


def _lire(racine) -> str | None:
    try:
        return (Path(racine) / "CONTEXTE.md").read_text(encoding="utf-8")
    except OSError:
        return None


def empreintes(racine) -> dict[str, str]:
    """{ctx-id: sha1} du CONTEXTE.md courant ; vide s'il est absent."""
    t = _lire(racine)
    return {k: v["sha1"] for k, v in sections(t).items()} if t is not None else {}


def deprecies(racine) -> set[str]:
    t = _lire(racine)
    return analyser(t)[1] if t is not None else set()


def projets(racine) -> list[str]:
    t = _lire(racine)
    if t is None:
        return []
    return [k for k in sections(t) if k.startswith(PREFIXE_PROJET) and k not in PROJET_HORS]


def resoudre(racine, citations: dict[str, str]) -> dict[str, dict]:
    """{ctx-id: pourquoi} -> {ctx-id: {sha1, pourquoi}}. Clé inconnue ou dépréciée, pourquoi vide ou trop long : ValueError."""
    t = _lire(racine)
    if t is None:
        raise ValueError("CONTEXTE.md introuvable")
    courantes, dep = analyser(t)
    erreurs = []
    for k, pq in citations.items():
        if k in dep:
            erreurs.append(f"ctx-id déprécié : {k}")
        elif k not in courantes:
            erreurs.append(f"ctx-id inconnu : {k}")
        elif courantes[k]["sha1"] == SHA1_VIDE:
            erreurs.append(f"section au corps vide : {k} (cite une sous-section)")
        erreurs += [f"{k} : {e}" for e in erreurs_pourquoi(pq)]
    if erreurs:
        raise ValueError("; ".join(erreurs) + f" (ctx-id connus : {', '.join(sorted(courantes))})")
    return {k: {"sha1": courantes[k]["sha1"], "pourquoi": pq.strip()} for k, pq in citations.items()}


def erreurs_pourquoi(pq) -> list[str]:
    if not isinstance(pq, str) or not pq.strip():
        return ["`pourquoi` vide"]
    if "\n" in pq.strip():
        return ["`pourquoi` sur plusieurs lignes"]
    if len(pq.strip()) > POURQUOI_MAX:
        return [f"`pourquoi` de {len(pq.strip())} caractères (> {POURQUOI_MAX})"]
    return []


def sections_perimees(contexte_sections: dict | None, courantes: dict[str, str], deprecies_: set[str] = frozenset()) -> list[str]:
    """ctx-id cités dont la section a changé, disparu ou été dépréciée."""
    if not contexte_sections:
        return []
    res = []
    for k, v in contexte_sections.items():
        sha = v.get("sha1") if isinstance(v, dict) else v
        if k in deprecies_ or courantes.get(k) != sha:
            res.append(k)
    return res


def est_perime(contexte_sections: dict | None, courantes: dict[str, str], deprecies_: set[str] = frozenset()) -> bool | None:
    """True si une section citée a changé, disparu ou été dépréciée ; False sinon ; None avant D64 (null)."""
    if contexte_sections is None:
        return None
    return bool(sections_perimees(contexte_sections, courantes, deprecies_))


def format_valide(cs) -> bool:
    """Format D64-bis : {ctx-id: {"sha1": 40 hexadécimaux, "pourquoi": une ligne de 160 caractères au plus}}."""
    return isinstance(cs, dict) and all(
        isinstance(k, str) and re.fullmatch(r"[A-Za-z0-9._-]+", k) and isinstance(v, dict) and set(v) == {"sha1", "pourquoi"}
        and isinstance(v["sha1"], str) and re.fullmatch(r"[0-9a-f]{40}", v["sha1"]) and not erreurs_pourquoi(v["pourquoi"])
        for k, v in cs.items())
