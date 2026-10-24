"""Sources OPÉRER du magasin personnel (lot L4, conception §2.2.1) : bilan des réglages, essais, projection modèle × effort.

Source unique du bilan interne : `operer reglages bilan --json` de l'instance (contrat `version: 1`, `vue: reglages_bilan`,
discipline:src/delta/operer/FORMAT.md), qui lit le journal sans lancer de mission ni relever de compte. Son résultat est
gardé tel quel dans un instantané privé `personnel/reglages-bilan.json`, avec la commande, les filtres `depuis`/`nature`,
`jusqu_au`, `lignes_ignorees`, l'heure de lecture et le SHA-256 du JSON canonique du résultat : deux lecteurs (MCP local,
Bureau, pilote des réserves) qui citent la même empreinte et les mêmes filtres parlent du même instantané.

La projection `personnel/modeles-efforts.json` rattache chaque groupe du bilan à une fiche couple commune
`kb:delta:modeles:<id-couple>` par les champs exacts `modele` et `effort`. Un alias ne vaut que s'il désigne un seul modèle
(au besoin départagé par la famille de l'exécutant : `claude:<rôle>` → modèles d'exécutant `claude`) ; un modèle ou un
effort nul, un alias ambigu ou un effort sans fiche restent dans `non_rattaches` avec leur motif, jamais rattachés au couple
courant par supposition. Les groupes gardent nature et exécutant et leurs métriques recopiées sans recalcul ; les `details`
(missions et événements) restent dans l'instantané seul.

Essais OPÉRER (`operer essai --json liste`) : instantané `personnel/essais-operer.json`, rattaché aux fiches par l'id de
fiche du protocole ; la leçon APPRENDRE d'un essai clos est écrite par OPÉRER, ce module ne la recopie que par référence.

Écritures sous le verrou des écrivains du magasin (`couches-import`), atomiques, en 0600 ; aucun appel de modèle.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import schemas
from .racines import Racines
from .stockage import empreinte, ecrire, verrou

COMMANDE_BILAN = ["operer", "reglages", "bilan", "--json"]
COMMANDE_ESSAIS = ["operer", "essai", "--json", "liste"]
DELAI_S = 120
# Métriques d'un groupe reprises dans la fiche (conception §2.2.1) ; les autres restent dans l'instantané.
CHAMPS_GROUPE = ("nature", "executant", "modele", "effort", "missions", "missions_relues", "ok_premier_tour",
                 "part_ok_premier_tour", "corrections_moyennes")
CHAMPS_JETONS = ("statut", "total_mesure", "missions_mesurees", "missions_inconnues")
CHAMPS_QUOTA = ("statut", "moyenne_pct", "missions_estimees", "missions_inconnues", "jauges")


class SourceIndisponible(RuntimeError):
    """Commande OPÉRER absente, en échec ou à la sortie hors contrat : rien n'est écrit, le dernier instantané reste."""


Executer = Callable[[list[str]], str]


def _executer(commande: list[str]) -> str:
    try:
        p = subprocess.run(commande, capture_output=True, text=True, timeout=DELAI_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SourceIndisponible(f"{' '.join(commande[:3])} : {type(e).__name__}") from e
    if p.returncode != 0:
        raise SourceIndisponible(f"{' '.join(commande[:3])} : code {p.returncode}")
    return p.stdout


def maintenant_iso(maintenant: datetime | None = None) -> str:
    return (maintenant or datetime.now(timezone.utc)).astimezone().isoformat(timespec="seconds")


def chemins(racines: Racines) -> dict[str, Path]:
    p = racines.personnel
    return {"bilan": p / "reglages-bilan.json", "essais": p / "essais-operer.json", "couples": p / "modeles-efforts.json"}


def commande_bilan(depuis: str | None = None, nature: str | None = None) -> list[str]:
    return COMMANDE_BILAN + (["--depuis", depuis] if depuis else []) + (["--nature", nature] if nature else [])


def lire_bilan(depuis: str | None = None, nature: str | None = None, executer: Executer = _executer) -> tuple[list[str], dict]:
    commande = commande_bilan(depuis, nature)
    try:
        doc = json.loads(executer(commande))
    except ValueError as e:
        raise SourceIndisponible("bilan OPÉRER : JSON illisible") from e
    if not isinstance(doc, dict) or doc.get("vue") != "reglages_bilan" or doc.get("version") != 1 \
            or not isinstance(doc.get("groupes"), list):
        raise SourceIndisponible("bilan OPÉRER hors contrat (vue reglages_bilan, version 1, groupes attendus)")
    return commande, doc


def instantane_bilan(commande: list[str], doc: dict, depuis: str | None, nature: str | None, lu_le: str) -> dict:
    return {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "reglages_bilan", "commande": commande,
            "filtres": {"depuis": depuis, "nature": nature}, "version": doc["version"], "jusqu_au": doc.get("jusqu_au"),
            "lignes_ignorees": doc.get("lignes_ignorees"), "lu_le": lu_le, "sha256": empreinte(doc), "bilan": doc}


def lire_essais(executer: Executer = _executer) -> tuple[list[str], list]:
    try:
        doc = json.loads(executer(COMMANDE_ESSAIS))
    except ValueError as e:
        raise SourceIndisponible("essais OPÉRER : JSON illisible") from e
    if not isinstance(doc, dict) or doc.get("vue") != "essai" or not isinstance(doc.get("essais"), list):
        raise SourceIndisponible("essais OPÉRER hors contrat (vue essai, liste essais attendues)")
    return COMMANDE_ESSAIS, doc["essais"]


def essai_compact(e: dict) -> dict:
    """Ce qu'une fiche affiche d'un essai OPÉRER ; une valeur absente vaut null."""
    p = e.get("protocole") if isinstance(e.get("protocole"), dict) else {}
    clos = e.get("clos") if isinstance(e.get("clos"), dict) else {}
    return {"source": "operer", "id": e.get("id"), "fiche": p.get("fiche"), "version": p.get("version"),
            "titre": p.get("titre"), "statut": e.get("statut"), "maturite": e.get("maturite"),
            "fige_le": e.get("fige_le"), "issue": clos.get("issue"), "clos_le": clos.get("ts"), "lecon": clos.get("lecon")}


# --- rattachement d'un groupe à un couple commun ---

def modeles_communs(racines: Racines) -> tuple[str | None, dict]:
    """(génération, document `kb/modeles.json`) de la génération commune active ; (None, {}) sans génération."""
    try:
        actif = json.loads(racines.commun_actif.read_text(encoding="utf-8"))
        doc = json.loads((racines.commun / actif["generation"] / "kb" / "modeles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return None, {}
    return actif["generation"], doc


def rattacher(groupe: dict, doc: dict) -> tuple[dict | None, str | None]:
    """(fiche couple, None) ou (None, motif) ; aucune association par ressemblance de nom."""
    modele, effort, executant = groupe.get("modele"), groupe.get("effort"), str(groupe.get("executant") or "")
    if not modele or not effort:
        return None, "modele_ou_effort_inconnu"
    modeles = doc.get("modeles") if isinstance(doc.get("modeles"), dict) else {}
    candidats = [m for m in modeles.values()
                 if modele == m.get("modele") or modele in (m.get("aliases_defaut") or [])]
    if len(candidats) > 1:
        famille = executant.split(":", 1)[0]
        candidats = [m for m in candidats if m.get("executant") == famille]
        if len(candidats) != 1:
            return None, "alias_ambigu"
    if not candidats:
        return None, "modele_sans_fiche"
    m = candidats[0]
    couples = [e for e in doc.get("entrees") or [] if e.get("modele") == m.get("modele") and e.get("effort") == effort]
    if len(couples) != 1:
        return None, "effort_sans_fiche"
    return couples[0], None


def groupe_projete(g: dict) -> dict:
    jetons, quota = g.get("jetons") or {}, g.get("quota") or {}
    return {**{k: g.get(k) for k in CHAMPS_GROUPE}, "jetons": {k: jetons.get(k) for k in CHAMPS_JETONS},
            "quota": {k: quota.get(k) for k in CHAMPS_QUOTA}}


def projeter(instantane: dict, generation: str | None, doc_modeles: dict) -> dict:
    """Projection déterministe de l'instantané sur les couples communs (même entrée, mêmes octets)."""
    objets: dict[str, dict] = {}
    non_rattaches = []
    for g in instantane["bilan"]["groupes"]:
        couple, motif = rattacher(g, doc_modeles)
        if couple is None:
            non_rattaches.append({**{k: g.get(k) for k in ("nature", "executant", "modele", "effort", "missions")},
                                  "motif": motif})
            continue
        o = objets.setdefault(couple["identite"], {
            "objet": couple["identite"], "commun_empreinte": couple.get("empreinte"),
            "bilan_empreinte": instantane["sha256"], "observe_le": instantane["lu_le"],
            "jusqu_au": instantane["jusqu_au"], "groupes": []})
        o["groupes"].append(groupe_projete(g))
    for o in objets.values():
        o["groupes"].sort(key=lambda x: (str(x["nature"]), str(x["executant"]), str(x["modele"])))
    non_rattaches.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    return {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "modeles_efforts",
            "commun_generation": generation, "bilan_empreinte": instantane["sha256"], "filtres": instantane["filtres"],
            "jusqu_au": instantane["jusqu_au"], "observe_le": instantane["lu_le"], "objets": dict(sorted(objets.items())),
            "non_rattaches": non_rattaches}


def lire_instantane(racines: Racines) -> dict | None:
    """Instantané valide du bilan, ou None (absent, illisible ou hors contrat : jamais un bilan à zéro)."""
    try:
        doc = json.loads(chemins(racines)["bilan"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None if schemas.valider_personnel(doc, "reglages_bilan", "reglages-bilan.json") else doc


def age_h(instantane: dict | None, maintenant: datetime | None = None) -> float | None:
    try:
        lu = datetime.fromisoformat(instantane["lu_le"])
    except (TypeError, KeyError, ValueError):
        return None
    return ((maintenant or datetime.now(timezone.utc)) - lu).total_seconds() / 3600


def _ecrire_bilan(racines: Racines, inst: dict, res: dict) -> None:
    res["bilan"] = "modifie" if ecrire(chemins(racines)["bilan"], inst) else "inchange"


def _projeter_et_resumer(racines: Racines, inst: dict, res: dict) -> None:
    generation, doc_modeles = modeles_communs(racines)
    projection = projeter(inst, generation, doc_modeles)
    res["couples"] = "modifie" if ecrire(chemins(racines)["couples"], projection) else "inchange"
    res.update(empreinte=inst["sha256"], filtres=inst["filtres"], jusqu_au=inst["jusqu_au"], lu_le=inst["lu_le"],
               couples_rattaches=len(projection["objets"]), groupes_non_rattaches=len(projection["non_rattaches"]))


def enregistrer(racines: Racines, commande: list[str], doc: dict, maintenant: datetime | None = None) -> dict:
    """Range un bilan déjà lu par un autre appelant (collecte hebdomadaire du pont des réglages) : une seule lecture du
    journal alimente l'instantané partagé, sans second collecteur. Seuls les bilans sans filtre sont rangés ici."""
    if list(commande) != COMMANDE_BILAN:
        raise SourceIndisponible("bilan filtré ou commande différente : instantané partagé non remplacé")
    if not isinstance(doc, dict) or doc.get("vue") != "reglages_bilan" or doc.get("version") != 1 \
            or not isinstance(doc.get("groupes"), list):
        raise SourceIndisponible("bilan OPÉRER hors contrat (vue reglages_bilan, version 1, groupes attendus)")
    res = {"bilan": None, "essais": None, "couples": None, "echecs": []}
    with verrou(racines.verrous, "couches-import"):
        inst = instantane_bilan(list(commande), doc, None, None, maintenant_iso(maintenant))
        _ecrire_bilan(racines, inst, res)
        _projeter_et_resumer(racines, inst, res)
    return res


def rafraichir(racines: Racines, depuis: str | None = None, nature: str | None = None, si_ancien_h: float | None = None,
               executer: Executer = _executer, maintenant: datetime | None = None) -> dict:
    """Relit le bilan et les essais OPÉRER, réécrit les instantanés et la projection. Un instantané du bilan plus récent
    que `si_ancien_h` et de mêmes filtres est gardé ; les essais sont toujours relus. Une source en échec ne touche pas au dernier instantané valide de cette
    source et figure dans `echecs`. Rend un résumé sans contenu personnel."""
    filtres = {"depuis": depuis, "nature": nature}
    res = {"bilan": None, "essais": None, "couples": None, "echecs": []}
    with verrou(racines.verrous, "couches-import"):
        actuel = lire_instantane(racines)
        age = age_h(actuel, maintenant)
        garde = si_ancien_h is not None and actuel is not None and actuel["filtres"] == filtres \
            and age is not None and age < si_ancien_h
        lu_le = maintenant_iso(maintenant)
        if garde:
            inst, res["bilan"] = actuel, "garde"
        else:
            try:
                commande, doc = lire_bilan(depuis, nature, executer)
                inst = instantane_bilan(commande, doc, depuis, nature, lu_le)
                _ecrire_bilan(racines, inst, res)
            except SourceIndisponible as e:
                inst = actuel
                res["echecs"].append(str(e))
        # les essais sont relus à chaque fois : `--si-ancien` ne garde que le bilan (lecture du journal coûteuse), un essai
        # ouvert ou clos depuis le dernier instantané ne doit pas attendre le prochain bilan
        try:
            commande, essais = lire_essais(executer)
            doc_essais = {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "essais_operer",
                          "commande": commande, "lu_le": lu_le, "sha256": empreinte(essais), "essais": essais}
            res["essais"] = "modifie" if ecrire(chemins(racines)["essais"], doc_essais) else "inchange"
        except SourceIndisponible as e:
            res["echecs"].append(str(e))
        if inst is not None:
            _projeter_et_resumer(racines, inst, res)
    return res


def resume(racines: Racines, couple: str | None = None) -> dict:
    """Ce que lit un second consommateur (pilote des réserves) pour vérifier qu'il parle du même instantané : empreinte,
    filtres, `jusqu_au`, heure de lecture ; avec `couple`, les groupes projetés de ce couple (identité ou id)."""
    inst = lire_instantane(racines)
    if inst is None:
        return {"statut": "absent", "chemin": "personnel/reglages-bilan.json"}
    r = {"statut": "disponible", "chemin": "personnel/reglages-bilan.json", "sha256": inst["sha256"],
         "filtres": inst["filtres"], "commande": inst["commande"], "version": inst["version"],
         "jusqu_au": inst["jusqu_au"], "lignes_ignorees": inst["lignes_ignorees"], "lu_le": inst["lu_le"],
         "missions": inst["bilan"].get("missions"), "groupes": len(inst["bilan"]["groupes"])}
    if couple is not None:
        try:
            proj = json.loads(chemins(racines)["couples"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            proj = {"objets": {}, "bilan_empreinte": None}
        ident = couple if couple.startswith("kb:delta:modeles:") else f"kb:delta:modeles:{couple}"
        o = proj["objets"].get(ident)
        r["couple"] = {"objet": ident, "projection_a_jour": proj.get("bilan_empreinte") == inst["sha256"],
                       "groupes": o["groupes"] if o else []}
    return r
