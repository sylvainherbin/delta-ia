"""Lecture déterministe du Markdown de documentation : titres, tableaux, listes, premiers blocs de code."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RE_TITRE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_RE_CLOTURE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    niveau: int
    titre: str  # texte du titre, backticks retirés
    brut: str  # titre tel qu'écrit
    debut: int  # indice de ligne du titre
    fin: int  # indice de ligne exclu (prochain titre de niveau <= niveau, ou fin)
    chemin: tuple[str, ...]  # titres parents puis titre


def nettoyer(texte: str) -> str:
    """Retire le balisage léger (liens, gras, backticks, kbd) sans toucher au texte."""
    t = re.sub(r"<kbd>(.*?)</kbd>", r"\1", texte)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = t.replace("**", "").replace("`", "")
    # seules les balises HTML connues sont retirées : `<path>`, `<id>`, `<name>` font partie de la syntaxe
    t = re.sub(r"</?(?:a|b|i|em|strong|code|span|div|p|br|sup|sub|img|small|u|mark|kbd|Note|Tip|Warning|Info)\b[^>]*/?>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def lignes_hors_code(lignes: list[str]) -> list[bool]:
    """Pour chaque ligne, True si elle est hors d'un bloc de code clôturé."""
    dedans = False
    res = []
    for l in lignes:
        if _RE_CLOTURE.match(l):
            res.append(False)
            dedans = not dedans
            continue
        res.append(not dedans)
    return res


def sections(texte: str) -> tuple[list[str], list[Section]]:
    lignes = texte.splitlines()
    hors = lignes_hors_code(lignes)
    titres = []
    for i, l in enumerate(lignes):
        if hors[i]:
            m = _RE_TITRE.match(l)
            if m:
                titres.append((i, len(m.group(1)), m.group(2)))
    res: list[Section] = []
    pile: list[tuple[int, str]] = []
    for k, (i, niv, brut) in enumerate(titres):
        fin = len(lignes)
        for j, n2, _ in titres[k + 1:]:
            if n2 <= niv:
                fin = j
                break
        while pile and pile[-1][0] >= niv:
            pile.pop()
        titre = nettoyer(brut)
        pile.append((niv, titre))
        res.append(Section(niv, titre, brut, i, fin, tuple(t for _, t in pile)))
    return lignes, res


def cellules(ligne: str) -> list[str]:
    """Découpe une ligne de tableau Markdown ; `\\|` est un caractère, pas un séparateur."""
    l = ligne.strip()
    if l.startswith("|"):
        l = l[1:]
    if l.endswith("|") and not l.endswith("\\|"):
        l = l[:-1]
    morceaux = re.split(r"(?<!\\)\|", l)
    return [m.strip().replace("\\|", "|") for m in morceaux]


@dataclass
class Tableau:
    entetes: list[str]
    lignes: list[list[str]]
    debut: int


def tableaux(lignes: list[str], debut: int = 0, fin: int | None = None) -> list[Tableau]:
    fin = len(lignes) if fin is None else fin
    hors = lignes_hors_code(lignes)
    res: list[Tableau] = []
    i = debut
    while i < fin - 1:
        if hors[i] and lignes[i].lstrip().startswith("|") and re.match(r"^\s*\|?\s*:?-+:?\s*(\||$)", lignes[i + 1]):
            entetes = cellules(lignes[i])
            rangs = []
            j = i + 2
            while j < fin and lignes[j].lstrip().startswith("|"):
                rangs.append(cellules(lignes[j]))
                j += 1
            res.append(Tableau(entetes, rangs, i))
            i = j
        else:
            i += 1
    return res


def premier_bloc_code(lignes: list[str], debut: int, fin: int, max_lignes: int = 12) -> str | None:
    i = debut
    while i < fin:
        if _RE_CLOTURE.match(lignes[i]):
            corps = []
            j = i + 1
            while j < fin and not _RE_CLOTURE.match(lignes[j]):
                corps.append(lignes[j])
                j += 1
            texte = "\n".join(corps[:max_lignes]).strip("\n")
            if texte.strip():
                return texte + ("\n…" if len(corps) > max_lignes else "")
            i = j + 1
            continue
        i += 1
    return None


def premiere_liste(lignes: list[str], debut: int, fin: int, ordonnee: bool, max_items: int = 8) -> str | None:
    hors = lignes_hors_code(lignes)
    motif = re.compile(r"^\s*\d+[.)]\s+" if ordonnee else r"^\s*[-*]\s+")
    i = debut
    while i < fin:
        if hors[i] and motif.match(lignes[i]):
            items = []
            while i < fin and (motif.match(lignes[i]) or (lignes[i].startswith("   ") and items)):
                if motif.match(lignes[i]):
                    items.append(lignes[i].strip())
                i += 1
            return "\n".join(items[:max_items]) + ("\n…" if len(items) > max_items else "")
        i += 1
    return None


def premier_paragraphe(lignes: list[str], debut: int, fin: int, max_car: int = 500) -> str | None:
    hors = lignes_hors_code(lignes)
    courant: list[str] = []
    for i in range(debut, fin):
        l = lignes[i]
        texte_ok = hors[i] and l.strip() and not l.lstrip().startswith(("#", "|", "<", ">", "!", "import ", "---"))
        if texte_ok:
            courant.append(l.strip())
        elif courant:
            break
    if not courant:
        return None
    p = " ".join(courant)
    return p if len(p) <= max_car else p[:max_car].rsplit(" ", 1)[0] + " …"


def premier_code_en_ligne(lignes: list[str], debut: int, fin: int) -> str | None:
    hors = lignes_hors_code(lignes)
    for i in range(debut, fin):
        if hors[i]:
            m = re.search(r"`([^`]{2,120})`", lignes[i])
            if m:
                return m.group(1)
    return None


def usage_de(lignes: list[str], debut: int, fin: int) -> str | None:
    """Syntaxe recopiée : premier bloc de code, sinon première liste d'étapes, sinon premier code en ligne,
    sinon premier paragraphe. Jamais reformulée."""
    return (premier_bloc_code(lignes, debut, fin) or premiere_liste(lignes, debut, fin, True)
            or premier_code_en_ligne(lignes, debut, fin) or premier_paragraphe(lignes, debut, fin))
