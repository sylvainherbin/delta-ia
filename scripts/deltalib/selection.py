"""Sélection hebdomadaire de 3 à 5 essais (mission S1) : classement déterministe, sans modèle ni réseau.

Candidats : les entrées « À tester » de la base (verdicts `tester` et `utiliser` non encore utilisés, hors essais déclarés dans
kb-essais.yaml) et les nouveautés de la veille des sept derniers jours (éléments `fort` ou `moyen` qui portent une action).

Budget d'attention : au plus TAILLE_MAX entrées par semaine ISO. La sélection est figée à la première production de la semaine
(`rapports/selection/AAAA-Www.json`) ; les appels suivants la relisent. Le minuteur publie ce JSON et son bref Markdown ;
les retours restent locaux et rien n'entre dans `docs/`.

Retours (écrits par `scripts/retour.py`, S2 ; lus ici) : `rapports/selection/retours.yaml`, liste de {date, id, retour}, retour parmi RETOURS. Le
dernier retour d'un id décide :
- `connu`, `sans_interet`, `utile` : l'entrée ne revient plus (un `utile` est jugé ; l'essai se déclare dans kb-essais.yaml) ;
- `a_revoir` : l'entrée revient `revoir_apres` jours après le retour.
Les retours pèsent aussi sur les entrées voisines (même produit et même catégorie) : +2 par `utile`, -2 par `connu` ou
`sans_interet`, dans la limite de ±6.

Barème (points entiers, chaque règle écrit sa raison) :
- priorité i de profil.yaml (rang 1 = poids n) : mots de la priorité retrouvés dans le nom, l'usage, l'exemple et le « pourquoi »
  de la fiche (ou le titre, l'action et le « pour toi » d'une nouveauté) ; mot propre 2 points, mot générique (claude, codex…) 1
  point, au plus 6 points par priorité, multipliés par le poids ;
- nouveauté : fiche ajoutée depuis 14 jours +3 ; élément de veille +3, plus 4 (`fort`) ou 2 (`moyen`) ;
- verdict `utiliser` : +2 ;
- retours voisins : voir ci-dessus ; déjà proposée sans retour : -3 par présentation, et plus proposée à la 3e.
À score égal : date la plus récente, puis id. Deux entrées au plus par (produit, catégorie) et deux nouveautés de la veille au plus.
Le compte et les quotas (D71) ne reçoivent aucun bonus propre : le bloc « Compte et quotas » les pousse déjà en tête de chaque
compte rendu ; ils ne montent ici que par les priorités de profil.yaml (« limites hebdomadaires »).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import yaml

from . import profil as profil_mod
from . import semaine as sem
from .kb import catalogue
from .sujet_d71 import mots_trouves_base

TAILLE_MAX = 5  # budget d'attention (plan du 14/10) : jamais plus
TAILLE_MIN = 3
TAILLE_DEFAUT = 5
REVOIR_APRES_DEFAUT = 28  # jours entre un retour `a_revoir` et la réapparition de l'entrée
PRESENTATIONS_MAX = 3  # une entrée proposée trois fois sans retour ne revient plus
PAR_CATEGORIE_MAX = 2
VEILLE_MAX = 2
FENETRE_NOUVEAUTE_J = 14
FENETRE_VEILLE_J = 7
RETOURS = ("utile", "connu", "sans_interet", "a_revoir")
SANS_RETOUR_POSSIBLE = ("utile", "connu", "sans_interet")  # retours qui écartent l'entrée définitivement
DOSSIER = Path("rapports") / "selection"
FICHIER_RETOURS = "retours.yaml"

POINTS_PROPRE, POINTS_GENERIQUE, PLAFOND_PRIORITE = 2, 1, 6
POINTS_NOUVEAUTE, POINTS_UTILISER = 3, 2
POINTS_IMPACT = {"fort": 4, "moyen": 2}
POINTS_RETOUR, PLAFOND_RETOURS, PENALITE_PRESENTATION = 2, 6, 3

GENERIQUES = {"claude", "codex", "chatgpt", "code", "cli", "control"}
MOTS_VIDES = {"abord", "ce", "qui", "en", "le", "la", "les", "de", "des", "du", "et", "ou", "pour", "sur", "plus", "que", "un",
              "une", "par", "avec", "sans", "entre", "dans", "son", "ses", "aux", "ces", "pas", "est", "sont"}
RE_JETON = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RE_VERSION = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")
RE_PRIX = re.compile(r"\d+(?:[.,]\d+)?\s*(?:\$|€|USD|EUR|dollars?|euros?)(?:\s*(?:/|par|per)\s*(?:mois|month|an|year|Mtok|MTok))?", re.I)
RE_SEMAINE_FICHIER = re.compile(r"\d{4}-W\d{2}\.json")
MOTS_CAR_MAX = {"quoi": 220, "pourquoi": 300}


class SelectionInvalide(ValueError):
    """Entrée illisible ou mal formée (retours, sélection figée) : jamais ignorée en silence."""


# --- texte -------------------------------------------------------------------------------------------------------------

def _plat(texte) -> str:
    return re.sub(r"\s+", " ", texte).strip() if isinstance(texte, str) else ""


def _court(texte, limite: int) -> str:
    t = _plat(texte)
    return t if len(t) <= limite else t[: limite - 1].rstrip() + "…"


def _sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower()) if unicodedata.category(c) != "Mn")


def _racine_mot(jeton: str) -> str:
    return jeton.rstrip("sx")[:6] if "-" not in jeton else jeton


def jetons(texte: str) -> set[str]:
    return {_racine_mot(j) for j in RE_JETON.findall(_sans_accent(texte or ""))}


def mots_de_priorite(priorite: str) -> list[tuple[str, str, int]]:
    """[(mot affiché, racine, points)] : mots de plus de 2 lettres, hors mots vides ; un mot générique vaut 1 point."""
    vus: dict[str, tuple[str, str, int]] = {}
    for j in RE_JETON.findall(_sans_accent(priorite)):
        if len(j) < 3 or j in MOTS_VIDES:
            continue
        vus.setdefault(_racine_mot(j), (j, _racine_mot(j), POINTS_GENERIQUE if j in GENERIQUES else POINTS_PROPRE))
    return list(vus.values())


# --- retours -----------------------------------------------------------------------------------------------------------

def lire_retours(dossier: Path) -> list[dict]:
    """[{date, id, retour}] dans l'ordre du fichier. Absent ou vide : []. Mal formé : SelectionInvalide."""
    chemin = dossier / FICHIER_RETOURS
    if not chemin.exists():
        return []
    try:
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as err:
        raise SelectionInvalide(f"{chemin} illisible : {err}") from err
    if brut is None:
        return []
    if not isinstance(brut, list):
        raise SelectionInvalide(f"{chemin} : liste de {{date, id, retour}} attendue")
    res = []
    for n, r in enumerate(brut, 1):
        ou = f"{chemin} : retour {n}"
        if not isinstance(r, dict) or not {"date", "id", "retour"} <= set(r) or set(r) - {"date", "id", "retour", "note"}:
            raise SelectionInvalide(f"{ou} : {{date, id, retour}} attendu")
        jour = str(r["date"])
        try:
            if date.fromisoformat(jour).isoformat() != jour:
                raise ValueError
        except ValueError as err:
            raise SelectionInvalide(f"{ou} : date AAAA-MM-JJ attendue") from err
        if not isinstance(r["id"], str) or not r["id"].strip():
            raise SelectionInvalide(f"{ou} : id attendu")
        if r["retour"] not in RETOURS:
            raise SelectionInvalide(f"{ou} : retour parmi {', '.join(RETOURS)} (reçu : {r['retour']!r})")
        res.append({"date": jour, "id": r["id"].strip(), "retour": r["retour"]})
    return res


def dernier_retour(retours: list[dict]) -> dict[str, dict]:
    """{id: retour} : le plus récent par date, à date égale le dernier du fichier."""
    res: dict[str, dict] = {}
    for r in retours:
        if r["id"] not in res or r["date"] >= res[r["id"]]["date"]:
            res[r["id"]] = r
    return res


FICHIER_VERROU = "retours.yaml.lock"
MARQUE_ID_INCONNU = "identifiant absent de toute sélection"


class IdInconnu(SelectionInvalide):
    pass


def ids_proposes(dossier: Path) -> dict[str, str]:
    """{id: première semaine où l'entrée a été proposée}, lu dans les fichiers AAAA-Www.json de `dossier`."""
    res: dict[str, str] = {}
    for chemin in sorted(dossier.glob("*.json")) if dossier.is_dir() else []:
        if not RE_SEMAINE_FICHIER.fullmatch(chemin.name):
            continue
        doc = lire_figee(dossier, chemin.stem)
        for e in doc["entrees"]:
            res.setdefault(e["id"], chemin.stem)
    return res


def enregistrer_retour(dossier: Path, ident: str, retour: str, jour: date) -> tuple[dict, bool]:
    """Ajoute {date, id, retour} à la fin de retours.yaml ; (ligne, ajoutee). Même retour le même jour : rien n'est écrit (ajoutee=False).

    Refuse un retour hors RETOURS (ValueError), un id absent de toute sélection (IdInconnu) et un fichier existant mal formé
    (SelectionInvalide) sans rien écrire. Verrou exclusif sur un fichier à part, écriture par fichier temporaire puis `replace` ;
    les lignes déjà présentes, clés supplémentaires (`note`) comprises, sont conservées telles quelles.
    """
    if retour not in RETOURS:
        raise ValueError(f"retour {retour!r} inconnu : {', '.join(RETOURS)}")
    ident = ident.strip()
    dossier.mkdir(parents=True, exist_ok=True)
    with open(dossier / FICHIER_VERROU, "a", encoding="utf-8") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        connus = ids_proposes(dossier)
        if ident not in connus:
            raise IdInconnu(f"{MARQUE_ID_INCONNU} : {ident!r}")
        existants = lire_retours(dossier)  # valide le fichier : mal formé -> SelectionInvalide, avant toute écriture
        ligne = {"date": jour.isoformat(), "id": ident, "retour": retour}
        if dernier_retour(existants).get(ident) == ligne:
            return ligne, False
        chemin = dossier / FICHIER_RETOURS
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8")) if chemin.exists() else None
        tmp = chemin.with_name(chemin.name + ".tmp")
        tmp.write_text(yaml.safe_dump((brut or []) + [ligne], allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(tmp, chemin)
    return ligne, True


def bilan_mensuel(dossier: Path, mois: str) -> dict:
    """Bilan des entrées proposées pendant le mois `mois` (AAAA-MM) : une semaine appartient au mois de son lundi.

    Chaque id compte une fois (sa première apparition du mois) avec son dernier retour connu à l'appel, quelle qu'en soit la date.
    `taux_utiles` = utiles / proposées (un silence compte contre) ; `taux_utiles_sur_retours` = utiles / entrées avec retour (None sans retour).
    """
    try:
        debut = date.fromisoformat(f"{mois}-01")
    except ValueError as err:
        raise ValueError(f"mois {mois!r} : AAAA-MM attendu") from err
    if debut.strftime("%Y-%m") != mois:
        raise ValueError(f"mois {mois!r} : AAAA-MM attendu")
    dernier = dernier_retour(lire_retours(dossier))
    vus: dict[str, str] = {}
    semaines = []
    for chemin in sorted(dossier.glob("*.json")) if dossier.is_dir() else []:
        if not RE_SEMAINE_FICHIER.fullmatch(chemin.name) or _lundi(chemin.stem).strftime("%Y-%m") != mois:
            continue
        semaines.append(chemin.stem)
        for e in lire_figee(dossier, chemin.stem)["entrees"]:
            vus.setdefault(e["id"], chemin.stem)
    repartition = {r: 0 for r in RETOURS} | {"sans_retour": 0}
    for ident in vus:
        repartition[(dernier.get(ident) or {}).get("retour") or "sans_retour"] += 1
    n, avec = len(vus), len(vus) - repartition["sans_retour"]
    taux = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    return {"mois": mois, "semaines": semaines, "proposees": n, "avec_retour": avec, "repartition": repartition,
            "taux_utiles": taux(repartition["utile"], n), "taux_utiles_sur_retours": taux(repartition["utile"], avec)}


def rendre_bilan(b: dict) -> str:
    if not b["proposees"]:
        return f"Bilan {b['mois']} : aucune entrée proposée ce mois-ci"
    r = b["repartition"]
    pct = lambda v: "—" if v is None else f"{v:g} %"  # noqa: E731
    return "\n".join([f"Bilan {b['mois']} : {b['proposees']} entrée(s) proposée(s) en {len(b['semaines'])} semaine(s), {b['avec_retour']} avec retour",
                      f"  utile {r['utile']} · connu {r['connu']} · sans_interet {r['sans_interet']} · a_revoir {r['a_revoir']} · sans retour {r['sans_retour']}",
                      f"  Taux d'entrées utiles : {pct(b['taux_utiles'])} des proposées ; {pct(b['taux_utiles_sur_retours'])} des entrées avec retour"])


# --- caducité ----------------------------------------------------------------------------------------------------------

SANS_CADUCITE = "caducité non renseignée dans la fiche (ni version, ni prix, ni limite, ni disponibilité)"


def caducite(textes: list[str], version: str | None = None, disponibilite: str | None = None) -> str:
    """Condition de caducité tirée uniquement des textes de la fiche : version citée, prix, limites ou quotas, disponibilité.
    Aucune valeur n'est devinée : sans repère, l'entrée le dit."""
    plein = " ".join(_plat(t) for t in textes if isinstance(t, str))
    parties = []
    versions = [version] if version else []
    for v in RE_VERSION.findall(plein):
        if v not in versions:
            versions.append(v)
    if versions:
        parties.append("version citée " + ", ".join(f"v{v.lstrip('v')}" for v in versions[:2]))
    prix = list(dict.fromkeys(_plat(m.group(0)) for m in RE_PRIX.finditer(plein)))
    if prix:
        parties.append("prix cité " + ", ".join(prix[:2]))
    mots = mots_trouves_base(plein)
    if mots:
        parties.append("limites ou tarifs cités (" + ", ".join(sorted(set(mots))[:3]) + ")")
    if _plat(disponibilite):
        parties.append("disponibilité (" + _court(disponibilite, 80) + ")")
    return "caduque si change : " + " ; ".join(parties) if parties else SANS_CADUCITE


# --- candidats ---------------------------------------------------------------------------------------------------------

def _candidat_fiche(e: dict, jour: date) -> dict:
    reco = e.get("recommandation") if isinstance(e.get("recommandation"), dict) else {}
    ajout = catalogue.date_ajout(e)
    exemple, usage = _plat(e.get("exemple")), _plat(e.get("usage"))
    cible = exemple or usage
    nom = _plat(e.get("nom")) or e["id"]
    quoi = f"Essayer {nom}" + (f" : {_court(cible, MOTS_CAR_MAX['quoi'])}" if cible and cible != nom else "")
    pourquoi = _court(reco.get("pourquoi"), MOTS_CAR_MAX["pourquoi"])
    return {
        "id": e["id"], "origine": "a-tester", "produit": e.get("produit"), "categorie": e.get("categorie"), "nom": nom,
        "verdict": reco.get("verdict"), "date": ajout, "impact": None,
        "recent": bool(ajout and ajout >= (jour - timedelta(days=FENETRE_NOUVEAUTE_J)).isoformat()),
        "texte": " ".join([nom, usage, exemple, _plat(reco.get("pourquoi"))]),
        "quoi": quoi, "pourquoi": pourquoi or "la fiche n'explique pas ce que cela change pour toi",
        "caduque": caducite([e.get("description"), e.get("description_source"), reco.get("pourquoi"), usage],
                            None, e.get("disponibilite")),
    }


def _enrichir_element(racine: Path, ligne: dict) -> dict:
    """Complète une ligne du bilan hebdomadaire avec le « pour toi » et le résumé du fichier quotidien, s'ils sont lisibles."""
    chemin = racine / "docs" / "data" / ligne["perimetre"] / f"{ligne['jour']}.json"
    try:
        for e in json.loads(chemin.read_text(encoding="utf-8")).get("elements", []):
            if isinstance(e, dict) and e.get("id") == ligne["id"]:
                return {"pour_toi": _plat(e.get("pour_toi")), "resume": _plat(e.get("resume"))}
    except (OSError, ValueError, AttributeError):
        pass
    return {"pour_toi": "", "resume": ""}


def _candidat_element(racine: Path, ligne: dict) -> dict:
    plus = _enrichir_element(racine, ligne)
    titre = _plat(ligne.get("titre")) or ligne["id"]
    action = _plat(ligne.get("action"))
    return {
        "id": ligne["id"], "origine": "veille", "produit": ligne.get("produit"), "categorie": "veille", "nom": titre,
        "verdict": None, "date": ligne["jour"], "impact": ligne.get("impact"), "recent": True,
        "texte": " ".join([titre, action, plus["pour_toi"]]),
        "quoi": _court(action, MOTS_CAR_MAX["quoi"]),
        "pourquoi": _court(plus["pour_toi"] or titre, MOTS_CAR_MAX["pourquoi"]),
        "caduque": caducite([titre, action, plus["resume"]], ligne.get("version"), None),
    }


# Une action qui commence par « revérifier » (R5, D71 sans échéance publiée) est un rendez-vous de contrôle, pas un essai.
RE_REVERIFICATION = re.compile(r"^\W*rev[ée]rifi", re.I)


def _lignes_veille(racine: Path, jour: date) -> tuple[list[dict], list[str]]:
    """Éléments `fort` ou `moyen` à action des sept derniers jours (bilans de la semaine en cours et de la précédente), hors
    revérifications (`RE_REVERIFICATION`)."""
    debut = (jour - timedelta(days=FENETRE_VEILLE_J)).isoformat()
    lignes, avertissements = {}, []
    for semaine in dict.fromkeys([sem.semaine_de(jour - timedelta(days=7)), sem.semaine_de(jour)]):
        doc = sem.construire(racine, semaine)
        if doc["statut"] != "ok":
            avertissements.append(f"veille {semaine} : {doc['raison']}")
        for l in [*doc["d71"], *doc["elements"]]:
            if l.get("action") and not RE_REVERIFICATION.search(_plat(l["action"])) and l["jour"] >= debut and l["jour"] <= jour.isoformat() and l.get("certitude") != "non_confirme":
                lignes[(l["perimetre"], l["id"])] = l
    return list(lignes.values()), avertissements


def candidats(racine: Path, jour: date) -> tuple[list[dict], list[str]]:
    """(candidats, avertissements). Erreur de lecture de la base : exception, jamais une liste vide silencieuse."""
    entrees = catalogue._toutes_les_entrees(racine)
    if not entrees:
        raise SelectionInvalide("base de référence vide ou absente (docs/data/kb/)")
    essais = catalogue.lire_essais(racine)
    par_id = {e["id"]: e for e in entrees}
    a_tester = catalogue.construire_a_tester(entrees, jour.isoformat(), essais)
    pool = [_candidat_fiche(par_id[x["id"]], jour) for x in a_tester["entrees"] if not x["essai"] and x["id"] in par_id]
    lignes, avertissements = _lignes_veille(racine, jour)
    deja = {c["id"] for c in pool}
    pool += [_candidat_element(racine, l) for l in lignes if l["id"] not in deja]
    return pool, avertissements


# --- classement --------------------------------------------------------------------------------------------------------

def _lundi(semaine: str) -> date:
    return sem.bornes(semaine)[0]


def _presentations(dossier: Path, semaine: str) -> dict[str, list[date]]:
    """{id: [lundis des sélections antérieures qui l'ont proposé]}."""
    res: dict[str, list[date]] = {}
    for f in sorted(dossier.glob("????-W??.json")) if dossier.is_dir() else []:
        if not RE_SEMAINE_FICHIER.fullmatch(f.name) or f.stem >= semaine:
            continue
        try:
            for e in json.loads(f.read_text(encoding="utf-8"))["entrees"]:
                res.setdefault(e["id"], []).append(_lundi(f.stem))
        except (OSError, ValueError, KeyError, TypeError, sem.SemaineInvalide) as err:
            raise SelectionInvalide(f"{f} illisible : {err}") from err
    return res


def _clefs_connues(dossier: Path, pool: list[dict], racine: Path) -> dict[str, tuple]:
    """{id: (produit, catégorie)} pour rattacher un retour à ses voisines : base, candidats et sélections passées."""
    res = {e["id"]: (e.get("produit"), e.get("categorie")) for e in catalogue._toutes_les_entrees(racine)}
    res.update({c["id"]: (c["produit"], c["categorie"]) for c in pool})
    for f in sorted(dossier.glob("????-W??.json")) if dossier.is_dir() else []:
        try:
            for e in json.loads(f.read_text(encoding="utf-8")).get("entrees", []):
                res.setdefault(e["id"], (e.get("produit"), e.get("categorie")))
        except (OSError, ValueError, TypeError):
            continue
    return res


def noter(c: dict, priorites: list[str], retours_voisins: dict[tuple, int], presentations: int) -> tuple[int, list[str]]:
    """(score, raisons) : chaque règle qui compte écrit sa raison."""
    points, raisons = 0, []
    mots_texte = jetons(c["texte"])
    n = len(priorites)
    for i, texte in enumerate(priorites):
        trouves = [(m, p) for m, r, p in mots_de_priorite(texte) if r in mots_texte]
        if trouves:
            gain = min(sum(p for _, p in trouves), PLAFOND_PRIORITE) * (n - i)
            points += gain
            raisons.append(f"priorité {i + 1} « {texte} » : {', '.join(m for m, _ in trouves)} (+{gain})")
    if c["origine"] == "veille":
        gain = POINTS_NOUVEAUTE + POINTS_IMPACT.get(c["impact"], 0)
        points += gain
        raisons.append(f"nouveauté de la veille, impact {c['impact']} (+{gain})")
    elif c["recent"]:
        points += POINTS_NOUVEAUTE
        raisons.append(f"fiche ajoutée le {c['date']} (+{POINTS_NOUVEAUTE})")
    if c["verdict"] == "utiliser":
        points += POINTS_UTILISER
        raisons.append(f"verdict « utiliser » (+{POINTS_UTILISER})")
    voisin = retours_voisins.get((c["produit"], c["categorie"]), 0)
    if voisin:
        raisons.append(f"retours passés sur {c['produit']}/{c['categorie']} ({voisin:+d})")
        points += voisin
    if presentations:
        points -= PENALITE_PRESENTATION * presentations
        raisons.append(f"déjà proposée {presentations} fois sans retour (-{PENALITE_PRESENTATION * presentations})")
    if not raisons:
        raisons.append("aucun lien établi avec tes priorités : retenue faute de mieux")
    return points, raisons


def _retours_voisins(retours_dernier: dict[str, dict], clefs: dict[str, tuple]) -> dict[tuple, int]:
    res: dict[tuple, int] = {}
    for ident, r in retours_dernier.items():
        clef = clefs.get(ident)
        if clef is None or r["retour"] == "a_revoir":
            continue
        res[clef] = res.get(clef, 0) + (POINTS_RETOUR if r["retour"] == "utile" else -POINTS_RETOUR)
    return {k: max(-PLAFOND_RETOURS, min(PLAFOND_RETOURS, v)) for k, v in res.items()}


def classer(racine: Path, dossier: Path, jour: date, taille: int, revoir_apres: int) -> dict:
    """Document de sélection pour la semaine de `jour` (rien n'est écrit)."""
    if not TAILLE_MIN <= taille <= TAILLE_MAX:
        raise SelectionInvalide(f"taille de {TAILLE_MIN} à {TAILLE_MAX} (budget d'attention), pas {taille}")
    if revoir_apres < 0:
        raise SelectionInvalide("délai « à revoir » : un nombre de jours positif ou nul")
    semaine = sem.semaine_de(jour)
    priorites = profil_mod.charger(racine)["priorites"]
    pool, avertissements = candidats(racine, jour)
    retours = dernier_retour(lire_retours(dossier))
    presentations = _presentations(dossier, semaine)
    clefs = _clefs_connues(dossier, pool, racine)
    voisins = _retours_voisins(retours, clefs)

    ecartees = {"retour": 0, "a_revoir_attente": 0, "trop_proposee": 0}
    notees = []
    for c in pool:
        r = retours.get(c["id"])
        if r and r["retour"] in SANS_RETOUR_POSSIBLE:
            ecartees["retour"] += 1
            continue
        if r and r["retour"] == "a_revoir" and date.fromisoformat(r["date"]) + timedelta(days=revoir_apres) > jour:
            ecartees["a_revoir_attente"] += 1
            continue
        depuis = date.fromisoformat(r["date"]) if r else date.min
        n_prec = sum(1 for lundi in presentations.get(c["id"], []) if lundi > depuis)
        if n_prec >= PRESENTATIONS_MAX:
            ecartees["trop_proposee"] += 1
            continue
        score, raisons = noter(c, priorites, voisins, n_prec)
        notees.append((score, c, raisons))
    notees.sort(key=lambda t: (-t[0], _inverse(t[1]["date"] or ""), t[1]["id"]))

    choisies, par_categorie = [], {}
    for score, c, raisons in notees:
        clef = (c["produit"], c["categorie"])
        if len(choisies) >= taille or par_categorie.get(clef, 0) >= PAR_CATEGORIE_MAX:
            continue
        if c["origine"] == "veille" and sum(1 for x in choisies if x["origine"] == "veille") >= VEILLE_MAX:
            continue
        par_categorie[clef] = par_categorie.get(clef, 0) + 1
        choisies.append({
            "rang": len(choisies) + 1, "id": c["id"], "origine": c["origine"], "produit": c["produit"],
            "categorie": c["categorie"], "nom": c["nom"], "quoi": c["quoi"], "pourquoi": c["pourquoi"],
            "caduque_si": c["caduque"], "score": score, "classement": raisons,
        })
    if not choisies:
        avertissements.append("aucun candidat : base entièrement jugée, essayée ou en attente de revoir")
    return {
        "semaine": semaine, "jour": jour.isoformat(), "taille": taille, "revoir_apres_jours": revoir_apres,
        "priorites": priorites, "candidats": len(pool), "ecartees": ecartees, "avertissements": avertissements,
        "entrees": choisies,
    }


def _inverse(texte: str) -> tuple:
    return tuple(-ord(c) for c in texte)


# --- fichier de la semaine ---------------------------------------------------------------------------------------------

def chemin_semaine(dossier: Path, semaine: str) -> Path:
    return dossier / f"{semaine}.json"


def lire_figee(dossier: Path, semaine: str) -> dict | None:
    chemin = chemin_semaine(dossier, semaine)
    if not chemin.exists():
        return None
    try:
        doc = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("entrees"), list):
            raise ValueError("clé `entrees` absente")
        sem.bornes(semaine)
        if doc.get("semaine") != semaine or len(doc["entrees"]) > TAILLE_MAX:
            raise ValueError("semaine incohérente ou budget de cinq essais dépassé")
        return doc
    except (OSError, ValueError) as err:
        raise SelectionInvalide(f"{chemin} illisible : {err} (relancer avec --refaire)") from err


def ecrire(dossier: Path, doc: dict) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = chemin_semaine(dossier, doc["semaine"])
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(chemin)
    ecrire_markdown(dossier, doc)
    return chemin


def rendre_markdown(doc: dict) -> str:
    """Cinq lignes au plus : titre et raison courte, sans les annotations privées de retour."""
    def texte(valeur, limite):
        return re.sub(r"([\\`*_[\]<>])", r"\\\1", _court(valeur, limite))

    if not doc["entrees"]:
        return f"Sélection {doc['semaine']} : aucun essai à proposer.\n"
    return "\n".join(f"- {texte(e['nom'], 100)} — {texte(e['pourquoi'], 140)}"
                     for e in doc["entrees"]) + "\n"


def ecrire_markdown(dossier: Path, doc: dict) -> None:
    chemin = dossier / f"{doc['semaine']}.md"
    contenu = rendre_markdown(doc)
    if chemin.exists() and chemin.read_text(encoding="utf-8") == contenu:
        return
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(contenu, encoding="utf-8")
    tmp.replace(chemin)


def annoter_retours(doc: dict, dossier: Path) -> dict:
    """Ajoute à chaque entrée le dernier retour connu (`retour`, `retour_le`), lu au moment de l'appel : le fichier figé ne change pas."""
    retours = dernier_retour(lire_retours(dossier))
    entrees = [{**e, "retour": (retours.get(e["id"]) or {}).get("retour"), "retour_le": (retours.get(e["id"]) or {}).get("date")}
               for e in doc["entrees"]]
    return {**doc, "entrees": entrees}


def obtenir(racine: Path, dossier: Path, jour: date, taille: int, revoir_apres: int, refaire: bool = False) -> tuple[dict, bool]:
    """(document, produit_maintenant) : relit la sélection figée de la semaine, ou la produit et l'écrit."""
    semaine = sem.semaine_de(jour)
    if not refaire:
        figee = lire_figee(dossier, semaine)
        if figee is not None:
            ecrire_markdown(dossier, figee)
            return annoter_retours(figee, dossier), False
    doc = classer(racine, dossier, jour, taille, revoir_apres)
    ecrire(dossier, doc)
    return annoter_retours(doc, dossier), True


# --- rendus ------------------------------------------------------------------------------------------------------------

def rendre_texte(doc: dict, expliquer: bool = False) -> str:
    lignes = [f"Sélection {doc['semaine']} : {len(doc['entrees'])} entrée(s) sur {doc['candidats']} candidates"]
    for e in doc["entrees"]:
        marque = f"  [retour : {e['retour']}]" if e.get("retour") else ""
        lignes += [f"{e['rang']}. {e['quoi']}{marque}", f"   Pourquoi : {e['pourquoi']}", f"   {e['caduque_si'][0].upper()}{e['caduque_si'][1:]}"]
        if expliquer:
            lignes.append(f"   Classement ({e['score']} pt) : " + " ; ".join(e["classement"]))
    lignes += [f"! AVERTISSEMENT {a}" for a in doc.get("avertissements", [])]
    return "\n".join(lignes)


def rendre_bref(doc: dict) -> str:
    """Une ligne par entrée, pour le bref de Delta-pilote : rang, quoi essayer, identifiant."""
    if not doc["entrees"]:
        return f"Sélection {doc['semaine']} : aucune entrée à proposer"
    return "\n".join([f"Sélection {doc['semaine']} ({len(doc['entrees'])} essais)"]
                     + [f"{e['rang']}. {_court(e['quoi'], 110)} [{e['id']}]" for e in doc["entrees"]])
