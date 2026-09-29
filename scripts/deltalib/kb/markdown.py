"""Lecture déterministe du Markdown de documentation : titres, tableaux, listes, premiers blocs de code."""

from __future__ import annotations

import re
import textwrap
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


def _bloc(lignes: list[str], i: int, fin: int) -> tuple[list[str], int]:
    """Corps du bloc de code clôturé qui s'ouvre à la ligne i, et indice de la ligne qui suit sa clôture."""
    corps, j = [], i + 1
    while j < fin and not _RE_CLOTURE.match(lignes[j]):
        corps.append(lignes[j])
        j += 1
    return corps, j + 1


def _indente(corps: list[str]) -> bool:
    return any(x.strip() for x in corps) and all(x.startswith((" ", "\t")) for x in corps if x.strip())


def _liste(lignes: list[str], debut: int, fin: int, ordonnee: bool, max_items: int = 8,
           max_lignes: int = 12) -> tuple[int, int, str, bool] | None:
    """Première liste de la plage : (indice de début, indice de fin exclu, texte, contient un bloc de code).
    Une ligne replacée à la ligne ou indentée juste sous un item le complète. Un bloc de code appartient à l'item
    qui le précède s'il est suivi d'un autre item, ou si son contenu est indenté comme l'item ; il est recopié
    désindenté, 12 lignes au plus."""
    hors = lignes_hors_code(lignes)
    motif = re.compile(r"^\s*\d+[.)]\s+" if ordonnee else r"^\s*[-*]\s+")
    i = debut
    while i < fin and not (hors[i] and motif.match(lignes[i])):
        i += 1
    if i >= fin:
        return None
    depart, items, code = i, [], False
    while i < fin:
        l = lignes[i]
        if hors[i] and motif.match(l):
            items.append([l.strip()])
            i += 1
        elif hors[i] and l.strip() and lignes[i - 1].strip() and not _RE_CLOTURE.match(lignes[i - 1]) \
                and not l.lstrip().startswith(("#", "|", "<", ">")):
            items[-1][-1] += " " + l.strip()  # suite de l'item, replacée à la ligne
            i += 1
        elif not l.strip() or _RE_CLOTURE.match(l):
            j, blocs = i, []
            while j < fin and (not lignes[j].strip() or _RE_CLOTURE.match(lignes[j])):
                if _RE_CLOTURE.match(lignes[j]):
                    corps, j = _bloc(lignes, j, fin)
                    blocs.append(corps)
                else:
                    j += 1
            suite = j < fin and hors[j] and motif.match(lignes[j])
            gardes = blocs if suite or (blocs and all(_indente(c) for c in blocs)) else []
            for corps in gardes:
                items[-1].append(textwrap.dedent("\n".join(corps[:max_lignes])).strip("\n")
                                 + ("\n…" if len(corps) > max_lignes else ""))
                code = True
            if not suite:
                i = j if gardes else i
                break
            i = j
        else:
            break
    texte = "\n".join("\n".join(x) for x in items[:max_items]) + ("\n…" if len(items) > max_items else "")
    return depart, i, texte, code


def premiere_liste(lignes: list[str], debut: int, fin: int, ordonnee: bool, max_items: int = 8) -> str | None:
    r = _liste(lignes, debut, fin, ordonnee, max_items)
    return r[2] if r else None


def premier_paragraphe(lignes: list[str], debut: int, fin: int, max_car: int = 500) -> str | None:
    hors = lignes_hors_code(lignes)
    courant: list[str] = []
    balise = False  # attributs d'un composant écrit sur plusieurs lignes (`<Composant` … `/>`)
    for i in range(debut, fin):
        l = lignes[i]
        if balise or (hors[i] and re.match(r"^\s*<[A-Za-z]", l) and ">" not in l):
            balise = not l.rstrip().endswith(">")
            if courant:
                break
            continue
        texte_ok = hors[i] and l.strip() and not l.lstrip().startswith(("#", "|", "<", ">", "!", "import ", "---"))
        if texte_ok:
            courant.append(l.strip())
        elif courant:
            break
    if not courant:
        return None
    p = " ".join(courant)
    return p if len(p) <= max_car else p[:max_car].rsplit(" ", 1)[0] + " …"


def _note_index(ligne: str) -> bool:
    """Note d'en-tête des pages de documentation (« … see llms.txt … appending `.md` … ») : pas un usage."""
    return ligne.lstrip().startswith(">") and ("llms.txt" in ligne or "Documentation Index" in ligne)


def premier_code_en_ligne(lignes: list[str], debut: int, fin: int) -> str | None:
    hors = lignes_hors_code(lignes)
    for i in range(debut, fin):
        if hors[i] and not _note_index(lignes[i]):
            m = re.search(r"`([^`]{2,120})`", lignes[i])
            if m:
                return m.group(1)
    return None


_RE_MODE = re.compile(r"^\s*<(/?)ContentModeSwitch\b([^>]*)")


def _surface(attributs: str) -> str:
    m = re.search(r"\bids?=\"([^\"]*)\"", attributs)
    return m.group(1) if m else ""


def _borne_mode(lignes: list[str], debut: int, fin: int) -> int:
    """Une section ouverte dans un bloc `<ContentModeSwitch>` s'arrête là où commence un bloc d'une autre surface
    (ChatGPT web, CLI, IDE) : la suite ne la décrit plus."""
    ouverts = []
    for i in range(debut):
        m = _RE_MODE.match(lignes[i])
        if m:
            ouverts = ouverts[:-1] if m.group(1) else ouverts + [_surface(m.group(2))]
    if not ouverts:
        return fin
    surface, profondeur = ouverts[-1], 0
    for i in range(debut, fin):
        m = _RE_MODE.match(lignes[i])
        if not m:
            continue
        if not m.group(1):
            if profondeur == 0 and _surface(m.group(2)) != surface:
                return i
            profondeur += 1
        elif profondeur:
            profondeur -= 1
    return fin


def usage_et_nature(lignes: list[str], debut: int, fin: int) -> tuple[str | None, str]:
    """Usage recopié et sa nature (D49) : `syntaxe` (bloc de code, code en ligne) ou `etapes` (liste d'étapes,
    paragraphe d'une page narrative). Ordre : bloc de code, liste d'étapes, code en ligne, paragraphe ; un bloc de
    code qui fait partie d'une liste d'étapes est rendu avec la liste entière."""
    fin = _borne_mode(lignes, debut, fin)
    premier = next((i for i in range(debut, fin) if _RE_CLOTURE.match(lignes[i])), fin)
    pos = debut
    while (liste := _liste(lignes, pos, fin, True)) and liste[0] < premier:
        if liste[3] and premier < liste[1]:  # le premier bloc de code est une étape de la liste : la liste entière
            return liste[2], "etapes"
        pos = max(liste[1], liste[0] + 1)
    for fonction, nature in ((premier_bloc_code, "syntaxe"), (lambda l, d, f: premiere_liste(l, d, f, True), "etapes"),
                             (premier_code_en_ligne, "syntaxe"), (premier_paragraphe, "etapes")):
        v = fonction(lignes, debut, fin)
        if v:
            return v, nature
    return None, "syntaxe"


def usage_de(lignes: list[str], debut: int, fin: int) -> str | None:
    """Syntaxe recopiée, jamais reformulée (voir `usage_et_nature`)."""
    return usage_et_nature(lignes, debut, fin)[0]
