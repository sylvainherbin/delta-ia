"""État `state/<perimetre>.json` : identifiants déjà vus, empreintes. Détection des nouveautés et validation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .dates import maintenant_iso
from .modeles import Element

VERSION_ETAT = 1


def charger_etat(chemin: Path) -> dict:
    if not chemin.exists():
        return {"version": VERSION_ETAT, "maj_le": None, "vus": {}}
    with open(chemin, encoding="utf-8") as f:
        etat = json.load(f)
    if not isinstance(etat, dict) or not isinstance(etat.get("vus"), dict):
        raise ValueError(f"{chemin}: état illisible (clé `vus` attendue)")
    return etat


def ecrire_json(chemin: Path, donnees: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    tmp.replace(chemin)


def premier_passage(etat: dict) -> bool:
    return not etat.get("vus")


def sources_connues(etat: dict) -> set[str]:
    """Sources déjà vues par un `--valider` (clé `sources` de l'état) ou dont un identifiant figure dans `vus`.

    La clé `sources` est la trace fiable (D30) : une source dont aucun élément n'a encore été couvert par un
    fichier quotidien y figure quand même, sinon ses nouveautés en attente glisseraient vers `ignores`.
    """
    connues = {s for s in (etat.get("sources") or {})}
    connues |= {v.get("source_id") for v in etat.get("vus", {}).values() if v.get("source_id")}
    return connues


def detecter(elements: list[Element], etat: dict, fenetre_depuis: date | None,
             fenetre_par_source: dict[str, date] | None = None) -> tuple[list[Element], list[str]]:
    """Sépare les nouveautés des éléments à ignorer.

    - identifiant connu : rien, sauf si la source suit les révisions et que l'empreinte a changé,
      auquel cas l'élément revient en nouveauté avec `revision: true` (D1) ;
    - daté avant la fenêtre : ignoré, mais retenu pour que `--valider` l'inscrive dans l'état ; la fenêtre
      est celle du périmètre, ou celle de la source si `fenetre_par_source` en donne une (amorçage, D30) ;
    - non daté : jamais ignoré à cause de la fenêtre, c'est une nouveauté (D3) ;
    - sinon : nouveauté.
    """
    vus = etat.get("vus", {})
    fenetre_par_source = fenetre_par_source or {}
    nouveautes: list[Element] = []
    ignores: list[str] = []
    deja: set[str] = set()
    for e in elements:
        if e.id in deja:
            continue  # même identifiant natif rapporté par deux sources (ex. general et codex-app)
        deja.add(e.id)
        if e.id in vus:
            connue = vus[e.id].get("empreinte")
            if e.empreinte and connue and connue != e.empreinte:
                e.revision = True
                nouveautes.append(e)
            continue
        fenetre = fenetre_par_source.get(e.source_id, fenetre_depuis)
        if fenetre is not None and e.date_publication is not None and date.fromisoformat(e.date_publication) < fenetre:
            ignores.append(e.id)
            continue
        nouveautes.append(e)
    nouveautes.sort(key=lambda e: (e.date_publication or "9999", e.source_id, e.id), reverse=True)
    return nouveautes, sorted(ignores)


DOSSIERS = {"claude": "claude", "openai": "openai", "actu": "actu"}  # périmètre -> docs/data/<dossier>


def ids_couverts(quotidien: dict) -> tuple[set[str], set[str]]:
    """Identifiants que le fichier quotidien comptabilise : (ids_bruts des éléments, ids écartés)."""
    bruts: set[str] = set()
    for e in quotidien.get("elements", []):
        for i in e.get("ids_bruts") or []:
            bruts.add(i)
        if e.get("id"):
            bruts.add(e["id"])
    ecartes = {x["id"] for x in quotidien.get("ecartes", []) if isinstance(x, dict) and x.get("id")}
    return bruts, ecartes


def valider(etat: dict, brut: dict, quotidien: dict) -> tuple[dict, dict]:
    """Fait avancer l'état d'après le fichier quotidien de l'agent (D5, D13).

    Inscrits : les nouveautés brutes reprises dans `ids_bruts` ou `ecartes`, les `ignores` du fichier brut,
    les identifiants `web-*`. Les nouveautés brutes absentes restent en attente et sont listées.
    Retourne (état, bilan) avec bilan = {inscrits, revises, en_attente: [ids], inconnus: [ids]}.
    """
    vus = etat.setdefault("vus", {})
    empreintes = brut.get("empreintes") or {}
    horodatage = maintenant_iso()
    bruts, ecartes = ids_couverts(quotidien)
    couverts = bruts | ecartes
    bilan = {"inscrits": 0, "revises": 0, "en_attente": [], "inconnus": []}
    par_id = {e["id"]: e for e in brut.get("nouveautes", [])}
    for ident, e in par_id.items():
        if ident not in couverts:
            bilan["en_attente"].append(ident)
            continue
        empreinte = e.get("empreinte") or empreintes.get(ident)
        entree = vus.get(ident)
        if entree is None:
            vus[ident] = {"date_publication": e.get("date_publication"), "vu_le": horodatage, "source_id": e.get("source_id")}
            if empreinte:
                vus[ident]["empreinte"] = empreinte
            if ident in ecartes:
                vus[ident]["ecarte"] = True
            bilan["inscrits"] += 1
        elif empreinte and entree.get("empreinte") != empreinte:
            entree["empreinte"] = empreinte
            entree["revise_le"] = horodatage
            bilan["revises"] += 1
    for ident in couverts - set(par_id):
        if ident in vus:
            continue  # déjà connu : reprise d'un élément existant (fusion, révision déjà inscrite)
        if ident.startswith("web-"):
            vus[ident] = {"date_publication": None, "vu_le": horodatage, "source_id": "web"}
            bilan["inscrits"] += 1
        else:
            bilan["inconnus"].append(ident)  # ni dans le brut, ni dans l'état, ni issu du web : suspect
    sources_ignores = brut.get("ignores_sources") or {}
    for ident in brut.get("ignores", []):
        if ident not in vus:
            # la source est conservée : c'est la trace qui évite de ré-amorcer la source au passage suivant (D30)
            vus[ident] = {"date_publication": None, "vu_le": horodatage, "source_id": sources_ignores.get(ident), "ignore": True}
            if ident in empreintes:
                vus[ident]["empreinte"] = empreintes[ident]
            bilan["inscrits"] += 1
    traces = etat.setdefault("sources", {})
    for sid in brut.get("sources_traitees", []):  # D30 : trace de chaque source traitée, couverte ou non
        traces.setdefault(sid, {"vue_le": horodatage})
        traces[sid]["derniere_validation"] = horodatage
    etat["sources"] = dict(sorted(traces.items()))
    bilan["en_attente"].sort()
    bilan["inconnus"].sort()
    etat["version"] = VERSION_ETAT
    etat["maj_le"] = horodatage
    etat["vus"] = dict(sorted(vus.items()))
    return etat, bilan
