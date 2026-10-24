#!/usr/bin/env python3
"""Delta — pont du bilan OPÉRER des réglages vers les `constats_internes` des fiches `kb-modeles/*.yaml`.

Usage :
  reglages_pont.py collecter [--dossier D] [--json]            lance le bilan de chaque source et range l'export daté dans D
  reglages_pont.py maj --export SOURCE=CHEMIN [...] [--seuil N] [--dry-run] [--json]
                                                               écrit les constats automatiques dans kb-modeles/*.yaml
  reglages_pont.py tout [--dossier D] [--seuil N] [--dry-run] [--json]
                                                               collecter, puis maj sur les exports du jour
  maj et tout : [--ajustements FICHIER] [--politique FICHIER] [--sans-ajustements]   ajustements proposés (lot 4)

Sources (`principal`, `essai`) : `principal` lance `operer reglages bilan --json` ; les commandes se redéfinissent, et `essai` (lecture
seule, sur une autre machine) se déclare, dans ~/.config/delta/reglages-bilans.json : {"essai": ["ssh", …]} (variable
DELTA_REGLAGES_CONFIG pour un autre fichier). Une source sans commande, injoignable ou à la sortie inattendue est un échec visible :
elle figure dans le bilan, le code de sortie est 3 et rien de ses constats n'est touché. Un export valide sans mission (instance neuve)
est une réponse, pas un échec.

Regroupement : fiche × effort × nature × source. L'exécutant d'une mission décide la famille de fiches (`executants_operer` de chaque
kb-modeles/<famille>.yaml, `claude:<role>` couvrant tous les rôles) ; le modèle OPÉRER désigne la fiche par `modele`, `modele_operer`
ou `aliases_modele` de cette famille seulement ; un alias partagé, un modèle ou un effort absents de la fiche donnent « sans fiche »,
jamais une fiche devinée. Les exécutants d'une même famille sont confondus : le constat le dit. Une mission présente dans deux groupes
d'une même cellule n'est comptée qu'une fois.

Seuil (défaut 5 missions relues par cellule) : à 5, l'intervalle de confiance d'une part est large de plus de 0,5 ; en dessous, aucune
part n'a de sens. Sous 5 aucun constat n'est écrit ; sous 10 le constat porte la réserve d'effectif réduit. Les cellules écartées (sous le
seuil, sans fiche, nature `inconnue`, modèle ou effort absent du journal) sont listées dans le bilan avec leur motif.

Constat : texte fait de nombres (effectifs, parts, médiane), jamais de chemin, de machine, de compte ni d'identifiant de mission
(`refuser_si_prive`). Valeur inconnue = « inconnu », jamais estimée. Chaque constat porte `cle_auto` (auto:SOURCE:EFFORT:NATURE) dans le
YAML seulement (le catalogue public ne garde pas ce champ) : c'est la clé qui permet de remplacer le constat automatique précédent. Les
constats sans `cle_auto` (manuels) ne sont jamais lus ni réécrits : seul leur bloc est découpé et recopié tel quel. Si seul le jour a
changé, le constat existant reste (aucune écriture pour rien) ; une cellule non renouvelée est signalée « obsolète » et conservée.

Rien n'est écrit dans docs/ : `catalogue.py modeles` régénère docs/data/kb/modeles.json.

Ajustements proposés (lot 4) : depuis l'export `principal` seulement, chaque cellule (famille, nature) de la règle par mission est
comparée au témoin en vigueur, la case `<nature>.*` de `operer.reglage_missions.<famille>.table` (politique lue comme OPÉRER).
Un ajustement ne change qu'une clé (modèle ou effort), à seuil atteint des deux côtés ; « economie » (effort plus bas, ou prix API
public de sortie plus bas d'après la fiche) si l'acceptation au premier tour observée n'est pas plus basse que celle du témoin,
« renfort » si la borne basse de son intervalle de Wilson à 95 % dépasse la part du témoin. Format : id `reglage-…`, `reglage`
{cle, temoin, essai}, `motif`, `observations` (témoin et essai : effectifs, parts, intervalle, corrections ; `jetons`, `quota` et
`equivalent_api` séparés, jamais convertis), `limites`, `qualification` (Delta Lab sur le K8 : protocole partiel pour `operer essai
ouvrir`, champs à compléter, aucun deviné). Une baisse sur des missions différentes n'attribue jamais un gain au réglage : le
motif dit un écart observé, les limites le disent non apparié. Les ajustements vont dans la couche personnelle
(`<etat>/delta-ia/personnel/ajustements-reglages.json`, jamais publié), entrent « proposé » dans la boucle d'adoption
(deltalib/adoptions.py) et n'en sortent que par un essai Delta Lab ouvert sur leur id. Un ajustement non renouvelé reste listé
(`actuel: false`). Rien n'est appliqué : aucune politique, aucun essai, aucune mission n'est écrit ici.

Codes : 0 fait ; 1 erreur (YAML illisible, export invalide) ; 2 usage ; 3 fait, mais au moins une source ou les ajustements
en échec.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parent.parent
SEUIL_DEFAUT = 5
SEUIL_EFFECTIF_REDUIT = 10
SOURCES = ("principal", "essai")
POSTES = {"principal": "poste principal", "essai": "instance d'essai"}
COMMANDES_DEFAUT = {"principal": ["operer", "reglages", "bilan", "--json"]}
DOSSIER_DEFAUT = Path.home() / ".local/state/delta/reglages-bilans"
CONFIG_DEFAUT = Path.home() / ".config/delta/reglages-bilans.json"
DELAI_COMMANDE_S = 120
EFFORTS_RANG = ("minimal", "low", "medium", "high", "xhigh", "max")
Z95 = 1.96
LIMITES_AJUSTEMENT = (
    "Missions différentes, non appariées : l'écart observé peut venir des tâches, pas du réglage.",
    "Tous les exécutants de la famille et toutes les tailles sont confondus.",
    "Aucun gain n'est attribué au réglage : seule la qualification par Delta Lab peut en établir un.",
    "Jetons, équivalent API et quota sont trois grandeurs distinctes, jamais converties l'une dans l'autre.",
)

# Ce qui ne doit jamais apparaître dans un texte publié.
MOTIFS_PRIVES = [
    re.compile(r"\bm-[0-9a-f]{12}\b"),                  # identifiant de mission
    re.compile(r"(?:^|[\s(\"'])(?:/home/|~/|/tmp/|/var/)"),  # chemin
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),         # adresse IP
    re.compile(r"\b(?:ssh|sudo)\b", re.I),
    re.compile(r"@\w"),                                 # compte ou courriel
    re.compile(r"\b(?:hp-essai|herbin|\.local)\b", re.I),
]


class ErreurPont(Exception):
    pass


# ───────────────────────────── sources et collecte ─────────────────────────────

def commandes_sources(config: Path | None = None) -> dict[str, list[str] | None]:
    chemin = config or Path(os.environ.get("DELTA_REGLAGES_CONFIG") or CONFIG_DEFAUT)
    surcharge: dict = {}
    if chemin.is_file():
        try:
            surcharge = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ErreurPont(f"{chemin} illisible : {e}") from e
        if not isinstance(surcharge, dict):
            raise ErreurPont(f"{chemin} : objet JSON attendu")
    res: dict[str, list[str] | None] = {}
    for s in SOURCES:
        cmd = surcharge.get(s, COMMANDES_DEFAUT.get(s))
        ok = isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd)
        res[s] = cmd if ok else None
    return res


def verifier_export(doc: object) -> dict:
    if not isinstance(doc, dict) or doc.get("vue") != "reglages_bilan" or doc.get("version") != 1:
        raise ErreurPont("export inattendu (vue `reglages_bilan`, version 1 attendues)")
    if not isinstance(doc.get("groupes"), list):
        raise ErreurPont("export inattendu : `groupes` absent")
    return doc


def collecter(dossier: Path, maintenant: datetime | None = None, config: Path | None = None,
              ranger=None) -> list[dict]:
    """Un export daté par source ; une entrée {source, statut: ok|echec, chemin, motif, missions}.
    `ranger(commande, doc)` (facultatif) reçoit l'export `principal` valide : la collecte hebdomadaire alimente ainsi
    l'instantané privé partagé de l'instance (deux couches, lot L4) par la même lecture du journal, sans second collecteur ;
    son échec est noté dans `instantane`, sans toucher à l'export."""
    maintenant = maintenant or datetime.now().astimezone()
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = maintenant.strftime("%Y-%m-%d_%H%M")
    resultats = []
    for source, cmd in commandes_sources(config).items():
        res = {"source": source, "statut": "echec", "chemin": None, "motif": None, "missions": None}
        resultats.append(res)
        if cmd is None:
            res["motif"] = "commande non configurée"
            continue
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=DELAI_COMMANDE_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            res["motif"] = f"commande impossible : {type(e).__name__}"
            continue
        if p.returncode != 0:
            res["motif"] = f"code {p.returncode}"
            continue
        try:
            doc = verifier_export(json.loads(p.stdout))
        except (ValueError, ErreurPont) as e:
            res["motif"] = f"sortie inattendue : {e}"[:160]
            continue
        chemin = dossier / f"{horodatage}-{source}.json"
        chemin.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
        res.update(statut="ok", chemin=str(chemin), missions=doc.get("missions"))
        if ranger is not None and source == "principal":
            try:
                res["instantane"] = ranger(cmd, doc)
            except Exception as e:  # noqa: BLE001 — l'export reste valable ; l'instantané garde sa dernière version
                res["instantane"] = f"non rangé : {e}"[:160]
    return resultats


def ranger_instance(cmd: list[str], doc: dict) -> str:
    """Instantané partagé de l'installation historique (`<etat>/delta-ia/personnel/reglages-bilan.json`)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from deltalib.couches import bilan, racines
    res = bilan.enregistrer(racines.resoudre(historique=True), cmd, doc)
    return f"rangé ({res['bilan']}, {res['couples_rattaches']} couples)"


# ───────────────────────────── fiches et correspondance ─────────────────────────────

def charger_familles(racine: Path) -> dict[str, dict]:
    """famille → {executants, fiches: {id: {aliases, efforts}}, texte, chemin}."""
    familles = {}
    for chemin in sorted((racine / "kb-modeles").glob("*.yaml")):
        if chemin.name == "forfaits.yaml":
            continue
        texte = chemin.read_text(encoding="utf-8")
        doc = yaml.safe_load(texte)
        if not isinstance(doc, dict) or not isinstance(doc.get("modeles"), list):
            raise ErreurPont(f"{chemin.name} : `modeles` attendu")
        fiches = {}
        for m in doc["modeles"]:
            noms = {m["modele"], m.get("modele_operer") or m["modele"], *(m.get("aliases_modele") or [])}
            prix = m.get("prix_api") if isinstance(m.get("prix_api"), dict) else {}
            fiches[m["modele"]] = {"noms": noms, "efforts": {e["effort"] for e in m.get("efforts") or []},
                                   "operer": m.get("modele_operer") or m["modele"],
                                   "prix_sortie": prix.get("sortie_usd") if isinstance(prix.get("sortie_usd"), (int, float)) else None}
        familles[chemin.stem] = {
            "executants": list(doc.get("executants_operer") or []),
            "fiches": fiches,
            "chemin": chemin,
        }
    return familles


def famille_de(executant: str, familles: dict[str, dict]) -> str | None:
    for nom, f in familles.items():
        for motif in f["executants"]:
            if motif == executant or (motif.endswith(":<role>") and executant.startswith(motif[:-len("<role>")])):
                return nom
    return None


def fiche_de(famille: dict, modele: str) -> str | None:
    """L'unique fiche de la famille qui porte ce nom OPÉRER ; None si absente ou ambiguë."""
    trouvees = [i for i, f in famille["fiches"].items() if modele in f["noms"]]
    return trouvees[0] if len(trouvees) == 1 else None


# ───────────────────────────── agrégation ─────────────────────────────

def _fr(x: float, decimales: int = 2) -> str:
    return f"{x:.{decimales}f}".replace(".", ",")


def _duree(s: float) -> str:
    return f"{round(s / 60)} min" if s < 5400 else f"{_fr(s / 3600, 1)} h"


def agreger(export: dict, familles: dict[str, dict]) -> tuple[dict, dict]:
    """(cellules, ecartes). cellule = (famille, fiche, effort, nature) → {mission_id: détail}."""
    cellules: dict[tuple, dict[str, dict]] = {}
    ecartes = {"nature_inconnue": 0, "sans_reglage": 0, "sans_fiche": {}}
    deja_ecartees: dict[str, set] = {k: set() for k in ("nature_inconnue", "sans_reglage")}
    for g in export["groupes"]:
        details = g.get("details") or []
        nature, executant, modele, effort = g.get("nature"), g.get("executant"), g.get("modele"), g.get("effort")
        for i, m in enumerate(details):
            mid = m.get("mission") or f"?{id(m)}"
            if nature in (None, "", "inconnue"):
                if mid not in deja_ecartees["nature_inconnue"]:
                    deja_ecartees["nature_inconnue"].add(mid)
                    ecartes["nature_inconnue"] += 1
                continue
            if not modele or not effort:
                if mid not in deja_ecartees["sans_reglage"]:
                    deja_ecartees["sans_reglage"].add(mid)
                    ecartes["sans_reglage"] += 1
                continue
            nom_famille = famille_de(str(executant), familles)
            fiche = fiche_de(familles[nom_famille], modele) if nom_famille else None
            if fiche is None or effort not in familles[nom_famille]["fiches"][fiche]["efforts"]:
                cle = f"{nom_famille or 'famille inconnue'}|{modele}|{effort}"
                ecartes["sans_fiche"].setdefault(cle, set()).add(mid)
                continue
            cellules.setdefault((nom_famille, fiche, effort, nature), {})[mid] = m
    ecartes["sans_fiche"] = {k: len(v) for k, v in sorted(ecartes["sans_fiche"].items())}
    return cellules, ecartes


def statistiques(missions: list[dict]) -> dict:
    relues = [m for m in missions if m.get("relue")]
    corr = [m["corrections"] for m in relues if isinstance(m.get("corrections"), (int, float))]
    durees = [m["duree_a_relire_s"] for m in missions if isinstance(m.get("duree_a_relire_s"), (int, float))]
    declares = [m for m in relues if m.get("defauts_declares")]

    def moyenne(cle: str):
        v = [m["defauts"][cle] for m in declares if isinstance((m.get("defauts") or {}).get(cle), (int, float))]
        return (sum(v) / len(v)) if v else None

    return {
        "missions": len(missions),
        "relues": len(relues),
        "ok_premier_tour": sum(1 for m in relues if m.get("ok_premier_tour")),
        "corrections_moyennes": (sum(corr) / len(corr)) if corr else None,
        "echecs": sum(1 for m in missions if m.get("echec")),
        "remplacees": sum(1 for m in missions if m.get("remplacee")),
        "duree_mediane_s": statistics.median(durees) if durees else None,
        "missions_duree": len(durees),
        "defauts_declares": len(declares),
        "defauts_bloquants_moyens": moyenne("BLOQUANT"),
        "defauts_a_noter_moyens": moyenne("A_NOTER"),
        "jetons_mesures": sum(1 for m in missions if m.get("jetons_mesures") is not None),
    }


def refuser_si_prive(texte: str) -> None:
    for motif in MOTIFS_PRIVES:
        if motif.search(texte):
            raise ErreurPont(f"texte public refusé (motif privé {motif.pattern!r})")


def composer_constat(st: dict, source: str, famille: str, effort: str, nature: str, jour: str) -> dict:
    n, nr = st["missions"], st["relues"]
    poste = POSTES[source]
    parts = [
        f"Observation interne automatique, {poste}, nature « {nature} », effort {effort}.",
        f"Effectif : {n} missions, dont {nr} relues.",
        f"Acceptées dès le premier tour : {st['ok_premier_tour']} sur {nr} ({round(100 * st['ok_premier_tour'] / nr)} %).",
    ]
    c = st["corrections_moyennes"]
    parts.append(f"Corrections moyennes avant acceptation : {_fr(c) if c is not None else 'inconnu'}.")
    parts.append(f"Échecs : {st['echecs']} sur {n} ; missions remplacées : {st['remplacees']} sur {n}.")
    if st["duree_mediane_s"] is not None:
        parts.append(f"Durée médiane jusqu'à la relecture : {_duree(st['duree_mediane_s'])} ({st['missions_duree']} missions mesurées).")
    else:
        parts.append("Durée médiane jusqu'à la relecture : inconnue.")
    if st["defauts_declares"]:
        b, a = st["defauts_bloquants_moyens"], st["defauts_a_noter_moyens"]
        parts.append(
            f"Défauts déclarés par la relecture pour {st['defauts_declares']} missions sur {nr} relues ; "
            f"par mission déclarante, bloquants {_fr(b, 1) if b is not None else 'inconnu'}, à noter {_fr(a, 1) if a is not None else 'inconnu'}.")
    else:
        parts.append(f"Défauts : aucun déclaré par la relecture sur les {nr} missions relues (comptage non renseigné, non nul).")
    parts.append(f"Coût : jetons mesurés pour {st['jetons_mesures']} missions sur {n} ; pas d'indice coût/qualité à ce niveau.")
    if nr < SEUIL_EFFECTIF_REDUIT:
        parts.append(f"Effectif réduit (moins de {SEUIL_EFFECTIF_REDUIT} missions relues) : ces parts ne permettent aucune comparaison.")
    parts.append(
        f"Tous les exécutants de la famille {famille} sont confondus et les missions ne sont pas de difficulté comparable ; "
        "observation locale datée, pas un barème universel.")
    texte = " ".join(parts)
    titre = f"Bilan automatique des missions « {nature} », effort {effort} ({poste})"
    source_txt = f"Bilan automatique OPÉRER des réglages, {poste}"
    for t in (texte, titre, source_txt):
        refuser_si_prive(t)
    return {"date": jour, "titre": titre, "constat": texte, "source": source_txt, "cle_auto": f"auto:{source}:{effort}:{nature}"}


# ───────────────────────────── ajustements proposés (lot 4) ─────────────────────────────

def wilson(succes: int, n: int) -> tuple[float, float] | tuple[None, None]:
    """Intervalle de Wilson à 95 % d'une part ; (None, None) sans effectif."""
    if not n:
        return None, None
    p, z2 = succes / n, Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    demi = Z95 * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5) / (1 + z2 / n)
    return max(0.0, centre - demi), min(1.0, centre + demi)


def lire_table_politique(chemin: Path) -> dict:
    """famille → nature → cases {taille: {modele, effort}} de `operer.reglage_missions` ; {} sans table."""
    try:
        doc = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, ValueError) as e:
        raise ErreurPont(f"politique d'instance illisible : {type(e).__name__}") from e
    table = ((doc.get("operer") or {}).get("reglage_missions") if isinstance(doc, dict) else None) or {}
    res: dict[str, dict] = {}
    for famille, f in table.items() if isinstance(table, dict) else ():
        natures = (f or {}).get("table") if isinstance(f, dict) else None
        if isinstance(natures, dict):
            res[famille] = {n: c for n, c in natures.items() if isinstance(c, dict)}
    return res


def _mediane(valeurs: list) -> float | None:
    v = [x for x in valeurs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return statistics.median(v) if v else None


def observation(famille: dict, fiche: str, effort: str, missions: list[dict]) -> dict:
    """Observations d'une cellule, sans conversion : jetons, équivalent API et quota restent trois grandeurs."""
    st = statistiques(missions)
    bas, haut = wilson(st["ok_premier_tour"], st["relues"])
    quotas = [m["quota"] for m in missions if isinstance(m.get("quota"), dict)]
    estimes = [q.get("valeur") for q in quotas if q.get("statut") == "estimé"]
    arrondi = (lambda x: round(x, 3) if x is not None else None)
    return {
        "modele": famille["fiches"][fiche]["operer"], "fiche": fiche, "effort": effort,
        "missions": st["missions"], "relues": st["relues"], "ok_premier_tour": st["ok_premier_tour"],
        "part_ok_premier_tour": arrondi(st["ok_premier_tour"] / st["relues"]) if st["relues"] else None,
        "intervalle_95": [arrondi(bas), arrondi(haut)],
        "corrections_moyennes": arrondi(st["corrections_moyennes"]),
        "echecs": st["echecs"], "remplacees": st["remplacees"], "duree_mediane_s": st["duree_mediane_s"],
        "jetons": {"missions_mesurees": st["jetons_mesures"], "mediane": _mediane([m.get("jetons_mesures") for m in missions])},
        "quota": {"missions_estimees": sum(1 for v in estimes if isinstance(v, (int, float))), "mediane_valeur": _mediane(estimes),
                  "jauges": sorted({q["jauge"] for q in quotas if isinstance(q.get("jauge"), str)})},
        "equivalent_api": {"valeur": None, "raison": "non fourni par le bilan ; jamais déduit des jetons (entrée, sortie et "
                                                      "cache non séparés) ni du quota"},
    }


def _slug(*parts: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", "-".join(parts).lower()).strip("-")


def _pct(x: float | None) -> str:
    return "inconnu" if x is None else f"{round(100 * x)} %"


def proposer_ajustements(cellules: dict, familles: dict[str, dict], table: dict, seuil: int, jour: str,
                         source: str = "principal") -> tuple[list[dict], list[dict]]:
    """(ajustements, ecartes) : un réglage à la fois, comparé au témoin en vigueur (case `<nature>.*` de la politique).

    Sens « economie » (effort plus bas, ou modèle au prix API public de sortie plus bas) : proposé si l'acceptation observée
    au premier tour n'est pas plus basse que celle du témoin. Sens « renfort » (plus coûteux en principe) : proposé seulement
    si la borne basse de son intervalle à 95 % dépasse la part du témoin. Aucun des deux n'attribue un gain : l'ajustement
    reste « proposé » jusqu'à la qualification de Delta Lab, et rien n'est appliqué."""
    ajustements, ecartes = [], []
    par_nature: dict[tuple, dict] = {}
    for (fam, fiche, effort, nature), missions in cellules.items():
        par_nature.setdefault((fam, nature), {})[(fiche, effort)] = list(missions.values())
    for (fam, nature), couples in sorted(par_nature.items()):
        if fam not in table:
            ecartes.append({"famille": fam, "nature": nature, "motif": f"aucune table operer.reglage_missions.{fam} : "
                            "réglage non branché sur une clé de politique"})
            continue
        cases = table[fam].get(nature)
        ref = (cases or {}).get("*")
        if not isinstance(ref, dict) or not ref.get("modele") or not ref.get("effort"):
            ecartes.append({"famille": fam, "nature": nature, "motif": "aucune case « * » dans la politique : aucune clé à essayer"})
            continue
        famille = familles[fam]
        fiche_t, effort_t = fiche_de(famille, ref["modele"]), ref["effort"]
        if fiche_t is None:
            ecartes.append({"famille": fam, "nature": nature, "motif": f"modèle de la politique sans fiche : {ref['modele']}"})
            continue
        temoin = couples.get((fiche_t, effort_t))
        st_t = statistiques(temoin) if temoin else None
        if st_t is None or st_t["relues"] < seuil:
            ecartes.append({"famille": fam, "nature": nature, "motif": f"témoin {ref['modele']} {effort_t} sous le seuil "
                            f"({st_t['relues'] if st_t else 0} relues)"})
            continue
        part_t = st_t["ok_premier_tour"] / st_t["relues"]
        autres_tailles = sorted(t for t in cases if t != "*")
        for (fiche_a, effort_a), missions in sorted(couples.items()):
            if (fiche_a, effort_a) == (fiche_t, effort_t):
                continue
            nom = f"{famille['fiches'][fiche_a]['operer']} {effort_a}"
            ecart = {"famille": fam, "nature": nature, "couple": nom}
            if fiche_a != fiche_t and effort_a != effort_t:
                ecartes.append({**ecart, "motif": "deux réglages changent à la fois : un essai ne change qu'une clé"})
                continue
            st_a = statistiques(missions)
            if st_a["relues"] < seuil:
                ecartes.append({**ecart, "motif": f"sous le seuil ({st_a['relues']} relues)"})
                continue
            if fiche_a == fiche_t:
                dimension, val_t, val_a = "effort", effort_t, effort_a
                if effort_a not in EFFORTS_RANG or effort_t not in EFFORTS_RANG:
                    ecartes.append({**ecart, "motif": "rang d'effort inconnu : sens du coût inconnu"})
                    continue
                economie = EFFORTS_RANG.index(effort_a) < EFFORTS_RANG.index(effort_t)
                raison = f"effort {effort_a} au lieu de {effort_t}"
            else:
                dimension, val_t, val_a = "modele", ref["modele"], famille["fiches"][fiche_a]["operer"]
                p_t, p_a = famille["fiches"][fiche_t]["prix_sortie"], famille["fiches"][fiche_a]["prix_sortie"]
                if p_t is None or p_a is None or p_t == p_a:
                    ecartes.append({**ecart, "motif": "prix API public de sortie inconnu ou égal : sens du coût inconnu"})
                    continue
                economie = p_a < p_t
                raison = f"prix API public de sortie {_fr(p_a, 0)} $ au lieu de {_fr(p_t, 0)} $ par million de jetons"
            part_a = st_a["ok_premier_tour"] / st_a["relues"]
            bas_a, haut_a = wilson(st_a["ok_premier_tour"], st_a["relues"])
            observe = (f"acceptation au premier tour {st_a['ok_premier_tour']}/{st_a['relues']} ({_pct(part_a)}, intervalle à "
                       f"95 % {_pct(bas_a)} à {_pct(haut_a)}) contre {st_t['ok_premier_tour']}/{st_t['relues']} ({_pct(part_t)}) "
                       f"pour le témoin {ref['modele']} {effort_t}")
            if economie and part_a < part_t:
                ecartes.append({**ecart, "motif": "plus économe en principe, mais acceptation observée plus basse que le témoin"})
                continue
            if not economie and bas_a <= part_t:
                ecartes.append({**ecart, "motif": "plus coûteux en principe, sans écart d'acceptation au-delà de la précision"})
                continue
            sens = "economie" if economie else "renfort"
            motif = (f"Plus économe en principe ({raison}) ; {observe} : pas plus basse sur ces missions."
                     if economie else
                     f"Plus coûteux en principe ({raison}) ; {observe} : plus haute au-delà de la précision des effectifs.")
            limites = list(LIMITES_AJUSTEMENT)
            if min(st_t["relues"], st_a["relues"]) < SEUIL_EFFECTIF_REDUIT:
                limites.append(f"Effectif réduit (moins de {SEUIL_EFFECTIF_REDUIT} missions relues d'un côté) : intervalle large.")
            for cote, st in (("témoin", st_t), ("essai", st_a)):
                if st["jetons_mesures"] < st["missions"]:
                    limites.append(f"Jetons mesurés pour {st['jetons_mesures']} missions sur {st['missions']} ({cote}).")
            if autres_tailles:
                limites.append("La clé « * » ne règle que les missions sans taille déclarée ; la politique a aussi les cases "
                               + ", ".join(autres_tailles) + ", que Delta Lab choisit d'essayer ou non.")
            cle = f"operer.reglage_missions.{fam}.table.{nature}.*.{dimension}"
            ident = _slug("reglage", fam, nature, dimension, str(val_t), "vers", str(val_a))
            ajustements.append({
                "id": ident, "statut": "propose", "actuel": True, "propose_le": jour, "vu_le": jour, "source": source,
                "famille": fam, "nature": nature, "sens": sens,
                "reglage": {"cle": cle, "temoin": val_t, "essai": val_a},
                "motif": motif,
                "observations": {"temoin": observation(famille, fiche_t, effort_t, temoin),
                                 "essai": observation(famille, fiche_a, effort_a, missions),
                                 "comparabilite": "aucune : missions différentes, non appariées, de difficulté inconnue"},
                "limites": limites,
                "qualification": {
                    "par": "Delta Lab", "instance": "K8", "etat": "a_qualifier",
                    "protocole": {"fiche": ident, "version": jour, "titre": f"{nature} : {dimension} {val_t} → {val_a}",
                                  "hypothese": f"{motif} Hypothèse à qualifier, aucun gain attribué.",
                                  "reglage": {"cle": cle, "temoin": val_t, "essai": val_a},
                                  "portee": {"projets": "*", "natures": [nature]}},
                    "a_completer": ["methode", "part", "mesures", "min_missions", "min_favorable", "min_prometteur",
                                    "min_regression", "max_missions", "perimetre", "touche_relecture"],
                    "commandes": ["operer essai ouvrir --gabarit", "operer essai ouvrir --protocole <protocole complété>"],
                },
            })
    return ajustements, ecartes


def fusionner_ajustements(precedent: dict | None, nouveaux: list[dict], jour: str) -> list[dict]:
    """Garde la date de première proposition ; un ajustement non renouvelé reste listé (`actuel: false`), jamais retiré :
    un essai ouvert sur son id doit pouvoir s'y rattacher dans la boucle d'adoption."""
    anciens = {a["id"]: a for a in (precedent or {}).get("ajustements") or [] if isinstance(a, dict) and a.get("id")}
    res = []
    for a in nouveaux:
        if a["id"] in anciens and anciens[a["id"]].get("propose_le"):
            a = {**a, "propose_le": min(a["propose_le"], anciens[a["id"]]["propose_le"])}
        res.append(a)
    vus = {a["id"] for a in nouveaux}
    res += [{**a, "actuel": False} for i, a in sorted(anciens.items()) if i not in vus]
    return res


def ecrire_ajustements(chemin: Path, ajustements: list[dict], ecartes: list[dict], meta: dict) -> None:
    """Couche personnelle : jamais dans docs/ ni dans le dépôt. Écriture atomique."""
    doc = {"version": 1, "vue": "ajustements_reglages", **meta, "ajustements": ajustements, "ecartes": ecartes}
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(chemin)


def lire_ajustements_fichier(chemin: Path) -> dict | None:
    try:
        doc = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as e:
        raise ErreurPont(f"ajustements précédents illisibles : {type(e).__name__}") from e
    if not isinstance(doc, dict) or doc.get("vue") != "ajustements_reglages":
        raise ErreurPont("ajustements précédents hors contrat (vue ajustements_reglages attendue)")
    return doc


# ───────────────────────────── écriture dans les YAML ─────────────────────────────

def _rendre(items: list[dict]) -> list[str]:
    if not items:
        return ["  constats_internes: []"]
    corps = yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=110, default_flow_style=False)
    return ["  constats_internes:"] + ["  " + ligne for ligne in corps.rstrip("\n").split("\n")]


def appliquer_constats(texte: str, fiche: str, nouveaux: dict[str, dict]) -> tuple[str, dict]:
    """Remplace dans le bloc `constats_internes` de la fiche les seuls items portant une `cle_auto`.

    Retourne (texte, {"ecrits": [...], "inchanges": [...], "obsoletes": [...]}) par cle_auto.
    """
    lignes = texte.split("\n")
    try:
        debut = lignes.index(f"- modele: {fiche}")
    except ValueError as e:
        raise ErreurPont(f"fiche {fiche} introuvable dans le YAML") from e
    fin = next((i for i in range(debut + 1, len(lignes)) if lignes[i].startswith("- modele:")), len(lignes))
    j = next((i for i in range(debut, fin) if lignes[i].startswith("  constats_internes:")), None)
    if j is None:
        raise ErreurPont(f"fiche {fiche} : `constats_internes` absent")
    k = j + 1
    while k < fin and (lignes[k].startswith("  - ") or lignes[k].startswith("    ")):
        k += 1
    blocs: list[list[str]] = []
    for ligne in lignes[j + 1:k]:
        if ligne.startswith("  - "):
            blocs.append([])
        blocs[-1].append(ligne)

    bilan = {"ecrits": [], "inchanges": [], "obsoletes": []}
    resultat: list[list[str]] = []
    vus = set()
    for bloc in blocs:
        item = yaml.safe_load("\n".join(l[2:] for l in bloc))[0]
        cle = item.get("cle_auto") if isinstance(item, dict) else None
        if not cle:
            resultat.append(bloc)  # manuel : recopié tel quel
            continue
        vus.add(cle)
        nouveau = nouveaux.get(cle)
        if nouveau is None:
            bilan["obsoletes"].append(cle)
            resultat.append(bloc)
        elif {c: v for c, v in item.items() if c != "date"} == {c: v for c, v in nouveau.items() if c != "date"}:
            bilan["inchanges"].append(cle)
            resultat.append(bloc)
        else:
            bilan["ecrits"].append(cle)
            resultat.append(_rendre([nouveau])[1:])
    for cle in sorted(set(nouveaux) - vus):
        bilan["ecrits"].append(cle)
        resultat.append(_rendre([nouveaux[cle]])[1:])

    if not resultat:
        nouveau_bloc = ["  constats_internes: []"]
    else:
        nouveau_bloc = ["  constats_internes:"] + [l for bloc in resultat for l in bloc]
    lignes[j:k] = nouveau_bloc
    return "\n".join(lignes), bilan


# ───────────────────────────── mise à jour ─────────────────────────────

def mettre_a_jour(racine: Path, exports: dict[str, Path], seuil: int = SEUIL_DEFAUT, aujourd_hui: date | None = None,
                  dry_run: bool = False, echecs_collecte: list[dict] | None = None, ajustements: dict | None = None) -> dict:
    """`ajustements` ({chemin, politique}, facultatif) : propose aussi les ajustements de la source `principal` (lot 4)."""
    familles = charger_familles(racine)
    principal = None  # (cellules, jour) de l'export principal valide
    aujourd_hui = aujourd_hui or date.today()
    rapport = {"seuil": seuil, "sources": [], "ecrits": [], "inchanges": [], "obsoletes": [], "ecartes": {
        "sous_seuil": [], "sans_fiche": {}, "nature_inconnue": 0, "sans_reglage": 0}}
    a_ecrire: dict[tuple, dict[str, dict]] = {}  # (famille, fiche) → {cle_auto: item}
    for c in echecs_collecte or []:
        rapport["sources"].append({"source": c["source"], "statut": "echec", "motif": c["motif"]})
    for source, chemin in exports.items():
        if source not in POSTES:
            raise ErreurPont(f"source inconnue : {source}")
        try:
            export = verifier_export(json.loads(Path(chemin).read_text(encoding="utf-8")))
        except (OSError, ValueError, ErreurPont) as e:
            rapport["sources"].append({"source": source, "statut": "echec", "motif": f"export illisible : {e}"[:160]})
            continue
        rapport["sources"].append({"source": source, "statut": "ok", "missions": export.get("missions"), "groupes": len(export["groupes"])})
        jour = (export.get("jusqu_au") or "")[:10] or aujourd_hui.isoformat()
        cellules, ecartes = agreger(export, familles)
        if source == "principal":
            principal = (cellules, jour, export.get("jusqu_au"))
        rapport["ecartes"]["nature_inconnue"] += ecartes["nature_inconnue"]
        rapport["ecartes"]["sans_reglage"] += ecartes["sans_reglage"]
        for cle, n in ecartes["sans_fiche"].items():
            rapport["ecartes"]["sans_fiche"][f"{source}|{cle}"] = n
        for (famille, fiche, effort, nature), missions in sorted(cellules.items()):
            st = statistiques(list(missions.values()))
            if st["relues"] < seuil:
                rapport["ecartes"]["sous_seuil"].append(
                    {"source": source, "fiche": fiche, "effort": effort, "nature": nature, "missions": st["missions"], "relues": st["relues"]})
                continue
            c = composer_constat(st, source, famille, effort, nature, jour)
            a_ecrire.setdefault((famille, fiche), {})[c["cle_auto"]] = c

    # sources en échec : leurs constats existants ne sont ni retirés ni signalés obsolètes
    echec = {s["source"] for s in rapport["sources"] if s["statut"] == "echec"}
    for nom, famille in familles.items():
        texte = famille["chemin"].read_text(encoding="utf-8")
        modifie = False
        for fiche in famille["fiches"]:
            nouveaux = a_ecrire.get((nom, fiche), {})
            if not nouveaux and not any(f"cle_auto: auto:" in l for l in texte.split("\n")):
                continue
            texte2, b = appliquer_constats(texte, fiche, nouveaux)
            b["obsoletes"] = [c for c in b["obsoletes"] if c.split(":")[1] not in echec]
            for k in ("ecrits", "inchanges", "obsoletes"):
                rapport[k] += [f"{fiche}|{c}" for c in b[k]]
            if texte2 != texte:
                texte, modifie = texte2, True
        if modifie and not dry_run:
            famille["chemin"].write_text(texte, encoding="utf-8")
    if ajustements is not None:
        rapport["ajustements"] = maj_ajustements(familles, principal, ajustements, seuil, dry_run)
    return rapport


def maj_ajustements(familles: dict, principal: tuple | None, cible: dict, seuil: int, dry_run: bool) -> dict:
    """Propose et range les ajustements ; un échec est dit (`statut: echec`), le fichier précédent reste intact."""
    if principal is None:
        return {"statut": "echec", "motif": "export principal absent ou illisible : aucun ajustement proposé"}
    if cible.get("motif"):
        return {"statut": "echec", "motif": cible["motif"]}
    if cible.get("politique") is None:
        return {"statut": "echec", "motif": "politique d'instance non désignée : témoin inconnu"}
    cellules, jour, jusqu_au = principal
    try:
        table = lire_table_politique(cible["politique"])
        precedent = lire_ajustements_fichier(cible["chemin"])
    except ErreurPont as e:
        return {"statut": "echec", "motif": str(e)}
    proposes, ecartes = proposer_ajustements(cellules, familles, table, seuil, jour)
    tous = fusionner_ajustements(precedent, proposes, jour)
    deja = {a.get("id") for a in (precedent or {}).get("ajustements") or [] if isinstance(a, dict)}
    if not dry_run:
        ecrire_ajustements(cible["chemin"], tous, ecartes, {"jusqu_au": jusqu_au, "seuil": seuil,
                                                             "politique": "lue" if table else "sans table"})
    return {"statut": "ok", "ecrit": not dry_run, "politique": "lue" if table else "sans table",
            "proposes": [a["id"] for a in proposes], "nouveaux": [a["id"] for a in proposes if a["id"] not in deja],
            "non_renouveles": [a["id"] for a in tous if not a["actuel"]], "ecartes": ecartes}


# ───────────────────────────── présentation ─────────────────────────────

def resume_texte(rapport: dict, collecte: list[dict] | None = None) -> str:
    L = []
    for s in (collecte or []):
        L.append(f"collecte {s['source']} : {s['statut']}" + (f" ({s['motif']})" if s.get("motif") else ""))
    for s in rapport["sources"]:
        L.append(f"source {s['source']} : {s['statut']}" + (f" ({s['motif']})" if s.get("motif") else f", {s.get('missions')} missions"))
    L.append(f"seuil : {rapport['seuil']} missions relues")
    L.append(f"constats écrits : {len(rapport['ecrits'])} ; inchangés : {len(rapport['inchanges'])} ; obsolètes (conservés) : {len(rapport['obsoletes'])}")
    for c in rapport["ecrits"]:
        L.append(f"  écrit {c}")
    for c in rapport["obsoletes"]:
        L.append(f"  obsolète {c}")
    e = rapport["ecartes"]
    L.append(f"écartés : {len(e['sous_seuil'])} cellules sous le seuil, {e['nature_inconnue']} missions de nature inconnue, "
             f"{e['sans_reglage']} sans modèle ou effort au journal, {len(e['sans_fiche'])} couples sans fiche")
    for c in e["sous_seuil"]:
        L.append(f"  sous le seuil : {c['source']}|{c['fiche']}|{c['effort']}|{c['nature']} ({c['relues']} relues sur {c['missions']})")
    for c, n in e["sans_fiche"].items():
        L.append(f"  sans fiche : {c} ({n} missions)")
    a = rapport.get("ajustements")
    if a and a["statut"] != "ok":
        L.append(f"ajustements : ÉCHEC ({a['motif']})")
    elif a:
        L.append(f"ajustements proposés : {len(a['proposes'])} (dont {len(a['nouveaux'])} nouveaux) ; non renouvelés (conservés) : "
                 f"{len(a['non_renouveles'])} ; comparaisons écartées : {len(a['ecartes'])} ; rien n'est appliqué")
        for i in a["proposes"]:
            L.append(f"  proposé {i}")
    return "\n".join(L)


def cible_ajustements(fichier: Path | None, politique: Path | None) -> dict:
    """{chemin, politique, motif} : couche personnelle et politique résolues comme OPÉRER (installation historique)."""
    if fichier is not None and politique is not None:
        return {"chemin": fichier, "politique": politique, "motif": None}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from deltalib.couches import instance, racines
        r = racines.resoudre(historique=True)
        if politique is None:
            politique, _ = instance.chemin_politique(r)
        return {"chemin": fichier or r.ajustements, "politique": politique, "motif": None}
    except Exception as e:  # noqa: BLE001 — l'échec est dit dans le bilan, les constats continuent
        return {"chemin": fichier, "politique": politique, "motif": f"racines ou politique non résolues : {type(e).__name__}"}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pont bilan OPÉRER → constats internes des fiches de modèles")
    sp = p.add_subparsers(dest="cmd", required=True)
    for nom in ("collecter", "maj", "tout"):
        s = sp.add_parser(nom)
        s.add_argument("--racine", type=Path, default=RACINE)
        s.add_argument("--dossier", type=Path, default=DOSSIER_DEFAUT)
        s.add_argument("--json", action="store_true")
        if nom != "collecter":
            s.add_argument("--seuil", type=int, default=SEUIL_DEFAUT)
            s.add_argument("--dry-run", action="store_true")
            s.add_argument("--ajustements", type=Path, default=None, metavar="FICHIER",
                           help="ajustements proposés (défaut : couche personnelle, ajustements-reglages.json)")
            s.add_argument("--politique", type=Path, default=None, metavar="FICHIER",
                           help="politique d'instance (défaut : celle d'OPÉRER)")
            s.add_argument("--sans-ajustements", action="store_true")
        if nom == "maj":
            s.add_argument("--export", action="append", default=[], metavar="SOURCE=CHEMIN")
    return p


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    collecte = None
    try:
        if a.cmd in ("collecter", "tout"):
            collecte = collecter(a.dossier, ranger=ranger_instance)
        if a.cmd == "collecter":
            print(json.dumps(collecte, ensure_ascii=False) if a.json else "\n".join(
                f"{c['source']} : {c['statut']} {c['chemin'] or c['motif']}" for c in collecte))
            return 3 if any(c["statut"] != "ok" for c in collecte) else 0
        if a.cmd == "tout":
            exports = {c["source"]: Path(c["chemin"]) for c in collecte if c["statut"] == "ok"}
        else:
            exports = {}
            for e in a.export:
                source, _, chemin = e.partition("=")
                if not chemin:
                    print("--export attend SOURCE=CHEMIN", file=sys.stderr)
                    return 2
                exports[source] = Path(chemin)
            if not exports:
                print("maj : au moins un --export est requis", file=sys.stderr)
                return 2
        rapport = mettre_a_jour(a.racine, exports, a.seuil, dry_run=a.dry_run,
                                echecs_collecte=[c for c in collecte or [] if c["statut"] != "ok"],
                                ajustements=None if a.sans_ajustements else cible_ajustements(a.ajustements, a.politique))
    except ErreurPont as e:
        print(f"reglages_pont : {e}", file=sys.stderr)
        return 1
    print(json.dumps(rapport, ensure_ascii=False) if a.json else resume_texte(rapport))
    echec_ajustements = (rapport.get("ajustements") or {}).get("statut") == "echec"
    return 3 if echec_ajustements or any(s["statut"] == "echec" for s in rapport["sources"]) else 0


if __name__ == "__main__":
    sys.exit(main())
