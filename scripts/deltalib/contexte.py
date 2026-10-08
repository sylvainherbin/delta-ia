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
import unicodedata
from pathlib import Path

_RE_TITRE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_RE_CTX = re.compile(r"^\s*<!--\s*ctx-id:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
_RE_DEPRECIE = re.compile(r"^\s*<!--\s*ctx-id-deprecie:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
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


# D96 : réévaluation des éléments récents dont une section citée de CONTEXTE.md a changé depuis leur publication.
REEVALUER_JOURS = 7
REEVALUER_MAX = 10
RAISON_REEVALUE_INCHANGE = "réévalué, inchangé"
_ORDRE_IMPACT = {"fort": 0, "moyen": 1, "faible": 2, "nul": 3}


def empreinte_fichier(racine) -> str | None:
    """sha1 de CONTEXTE.md entier (même calcul que `contexte_empreinte` des fichiers du jour), None s'il est absent."""
    try:
        return hashlib.sha1((Path(racine) / "CONTEXTE.md").read_bytes()).hexdigest()
    except OSError:
        return None


def a_reevaluer(racine, dossier: str, jour, fenetre: int = REEVALUER_JOURS, plafond: int = REEVALUER_MAX) -> dict:
    """D96 : éléments des `fenetre` derniers jours (fichiers docs/data/<dossier>/AAAA-MM-JJ.json de `jour - fenetre` à `jour`)
    dont une section citée dans `contexte_sections` a changé d'empreinte, disparu ou été dépréciée depuis leur publication.

    Pour un même id, seule la version la plus récente compte (une révision remplace l'élément). Un élément écarté par
    « réévalué, inchangé » dans un fichier postérieur n'est pas repris tant que CONTEXTE.md garde l'empreinte de ce fichier.
    Retourne {"reevaluer": [{id, date, impact, sections_modifiees}] (10 au plus, les plus forts d'abord, puis les plus récents),
    "reevaluer_total": n avant plafond}. `contexte_sections` null (avant D64) ou vide : jamais réévalué.
    ContexteInvalide ou CONTEXTE.md absent : propagé (ContexteInvalide) / ValueError, à signaler par l'appelant."""
    import json
    from datetime import timedelta

    texte = _lire(racine)
    if texte is None:
        raise ValueError("CONTEXTE.md introuvable")
    courantes_complet, deprecies_ = analyser(texte)
    courantes = {k: v["sha1"] for k, v in courantes_complet.items()}
    empreinte_courante = empreinte_fichier(racine)
    debut = (jour - timedelta(days=fenetre)).isoformat()
    fichiers = []
    for f in sorted((Path(racine) / "docs" / "data" / dossier).glob("????-??-??.json")):
        if debut <= f.stem <= jour.isoformat():
            try:
                q = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # valider.py signale un fichier du jour illisible ; la réévaluation ne s'y arrête pas
            if isinstance(q, dict):
                fichiers.append((f.stem, q))
    derniers: dict[str, tuple[str, dict]] = {}
    traites: dict[str, str] = {}  # id -> jour du dernier « réévalué, inchangé » valable pour l'empreinte courante
    for stem, q in fichiers:  # ordre chronologique : le plus récent remplace
        for e in q.get("elements") or []:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                derniers[e["id"]] = (stem, e)
        if q.get("contexte_empreinte") == empreinte_courante:
            for x in q.get("ecartes") or []:
                if isinstance(x, dict) and isinstance(x.get("id"), str) \
                        and str(x.get("raison", "")).strip().lower().startswith(RAISON_REEVALUE_INCHANGE):
                    traites[x["id"]] = stem
    trouves = []
    for ident, (stem, e) in derniers.items():
        modifiees = sections_perimees(e.get("contexte_sections") if isinstance(e.get("contexte_sections"), dict) else None,
                                      courantes, deprecies_)
        if not modifiees or traites.get(ident, "") > stem:
            continue
        trouves.append({"id": ident, "date": stem, "impact": e.get("impact"), "sections_modifiees": sorted(modifiees)})
    trouves.sort(key=lambda x: x["id"])
    trouves.sort(key=lambda x: x["date"], reverse=True)
    trouves.sort(key=lambda x: _ORDRE_IMPACT.get(x["impact"], 4))  # tris stables : impact, puis date décroissante, puis id
    return {"reevaluer": trouves[:plafond], "reevaluer_total": len(trouves)}


# Ancrage des `pour_toi` (REGLES §4) : un `pour_toi` nomme un projet, un outil ou une habitude de CONTEXTE.md. Les termes sont
# tirés du fichier lui-même, sans valeur codée en dur : noms de projets (`projet.<nom>`), titres de section, parties du ctx-id,
# segments en `code`, segments en **gras**, première cellule des lignes de tableau et noms propres de la prose des sections citées.
ANCRAGE_LONGUEUR_MIN = 3
ANCRAGE_MOTS_MAX = 4  # un segment plus long est une phrase, pas un nom
_RE_CODE = re.compile(r"`([^`\n]+)`")
_RE_GRAS = re.compile(r"\*\*([^*\n]+)\*\*")
_RE_CELLULE = re.compile(r"^\s*\|\s*([^|\n]+?)\s*\|")
_RE_MOT = re.compile(r"[A-Za-zÀ-ÿ][\wÀ-ÿ.+-]*[\wÀ-ÿ+]")
_RE_NUMERO = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
_RE_FIN_TITRE = re.compile(r"\s+[—–:(].*$|\s+-\s.*$")
# Mots de gabarit qui ne désignent aucun projet ni outil : une section ou un tableau les emploie comme étiquettes.
_GABARIT = frozenset({"element", "valeur", "nature", "etat", "stack", "objectif", "revue", "regle", "exemple", "note", "usage",
                      "profil", "config", "env", "methode", "optimisation", "projet", "projets", "outil", "outils", "nom",
                      "observe", "declare", "deduit", "inconnu", "oui", "non", "tout", "rien",
                      "claude", "codex", "chatgpt", "anthropic", "openai"})  # les sujets de la veille ne désignent pas l'utilisateur


def normaliser_ancrage(texte: str) -> str:
    """Sans casse ni accents, tout signe non alphanumérique réduit à une espace : `claude-code` et « Claude Code » se valent."""
    decompose = unicodedata.normalize("NFKD", str(texte).casefold())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", sans_accents).split())


def _terme_utilisable(t: str) -> bool:
    n = normaliser_ancrage(t)
    return len(n) >= ANCRAGE_LONGUEUR_MIN and len(n.split()) <= ANCRAGE_MOTS_MAX and not n.isdigit() and n not in _GABARIT


def _termes_code(segment: str) -> set[str]:
    """`tmux -L <nom>` -> tmux ; `docs/data/etat.json` -> le chemin et son nom de fichier (pas ses dossiers, trop génériques)."""
    premier = re.sub(r"<[^>]*>", " ", segment).split()
    if not premier:
        return set()
    mot = premier[0].strip("[](){}.,;:'\"")
    return {mot, segment.strip(), mot.rsplit("/", 1)[-1]}


def _noms_propres(ligne: str) -> set[str]:
    """Noms d'outils et de produits dans la prose : suite de mots capitalisés (Linux Mint), un mot seul n'y comptant pas
    en début de phrase ; mot à majuscule interne (macOS, iPhone). Un sigle en capitales (CLI, API) est écarté."""
    prose = re.sub(r"`[^`\n]*`|\*\*|\[[^\]\n]*\]|<!--.*?-->", " ", ligne)
    res: set[str] = set()
    suite: list[str] = []
    seul_en_debut = False  # la suite en cours ne compte qu'un mot, en début de phrase

    def vider() -> None:
        nonlocal suite, seul_en_debut
        if suite and not (len(suite) == 1 and seul_en_debut):
            res.add(" ".join(suite))
        suite, seul_en_debut = [], False

    debut = True
    for m in re.finditer(r"[^\s]+", prose):
        brut = m.group(0)
        mot = _RE_MOT.search(brut)
        mot = mot.group(0) if mot and len(mot.group(0)) >= ANCRAGE_LONGUEUR_MIN and not mot.group(0).isupper() else None
        if mot and re.search(r"[a-zà-ÿ][A-Z]", mot):
            res.add(mot)
        if mot and mot[0].isupper():
            if not suite:
                seul_en_debut = debut
            suite.append(mot)
        else:
            vider()
        fin_de_phrase = brut[-1] in ".!?;|" or brut in {"-", "*"} or brut.startswith("|")
        if fin_de_phrase or brut[-1] in ",):":
            vider()
        debut = fin_de_phrase
    vider()
    return res


def _corps_par_section(texte: str) -> dict[str, tuple[str, list[str]]]:
    """{ctx-id: (titre, lignes du corps)} ; mêmes bornes que `analyser` (corps jusqu'au titre suivant, ctx-id exclu)."""
    lignes = texte.splitlines()
    titres = [(i, m.group(2)) for i, l in enumerate(lignes) if (m := _RE_TITRE.match(l))]
    res: dict[str, tuple[str, list[str]]] = {}
    for k, (i, titre) in enumerate(titres):
        fin = titres[k + 1][0] if k + 1 < len(titres) else len(lignes)
        cle = next((m.group(1) for l in lignes[i + 1:fin] if l.strip() and (m := _RE_CTX.match(l))), None)
        if cle is None:
            continue
        res[cle] = (titre, [l for l in lignes[i + 1:fin] if not _RE_CTX.match(l) and not _RE_DEPRECIE.match(l)])
    return res


def termes_ancrage(texte: str) -> dict:
    """Termes d'ancrage d'un CONTEXTE.md : {"projets": {noms}, "sections": {ctx-id: {termes normalisés}}}.

    `projets` : un nom par section `projet.<nom>`. `sections[ctx-id]` : titre de la section (sans numéro ni complément après
    « — », « : » ou « ( »), parties du ctx-id après son premier élément, segments `code` (commande, chemin, nom de fichier),
    segments **gras**, première cellule des lignes de tableau et noms propres de la prose (mot capitalisé hors début de phrase,
    majuscule interne) du corps. Les étiquettes de gabarit et les segments de plus de
    4 mots sont écartés. ContexteInvalide si la structure ctx-id est invalide."""
    analyser(texte)  # structure invalide : propagée
    projets: set[str] = set()
    sections: dict[str, set[str]] = {}
    for cle, (titre, corps) in _corps_par_section(texte).items():
        brut: set[str] = set()
        if cle.startswith("projet.") and len(cle) > len("projet."):
            nom = cle[len("projet."):]
            projets.add(normaliser_ancrage(nom))
            brut.add(nom)
        brut.add(_RE_FIN_TITRE.sub("", _RE_NUMERO.sub("", titre)))
        brut.update(cle.split(".")[1:])
        for l in corps:
            for m in _RE_CODE.finditer(l):
                brut.update(_termes_code(m.group(1)))
            brut.update(m.group(1).strip(" :") for m in _RE_GRAS.finditer(l))
            brut.update(_noms_propres(l))
            if (m := _RE_CELLULE.match(l)) and not set(m.group(1)) <= set("-: "):
                brut.add(re.sub(r"[`*]", "", m.group(1)))
        sections[cle] = {normaliser_ancrage(t) for t in brut if _terme_utilisable(t)}
    return {"projets": {p for p in projets if p}, "sections": sections}


def termes_nommes(pour_toi: str, termes: dict, citees) -> list[str]:
    """Termes d'ancrage (projets de CONTEXTE.md et termes des sections `citees`) présents dans `pour_toi`, triés. Comparaison
    sans casse ni accents, sur des mots entiers. Une section citée mais absente de `termes` est ignorée."""
    texte = f" {normaliser_ancrage(pour_toi)} "
    candidats = set(termes["projets"])
    for k in citees or ():
        candidats |= termes["sections"].get(k, set())
    return sorted(t for t in candidats if f" {t} " in texte)
