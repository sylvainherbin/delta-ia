#!/usr/bin/env python3
"""Delta — organisation courante OPÉRER -> raw/organisation.json (D77).

Lecture locale, sans modèle : rôles réduits et missions comptées par projet.
Un échec de lecture remplace le relevé précédent et laisse le passage continuer.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.dates import maintenant_iso  # noqa: E402
from deltalib.etat import ecrire_json  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
DELAI = 20


class LectureImpossible(ValueError):
    """Raison contrôlée : jamais de sortie brute ni de détail d'exception OPÉRER."""


def lire_vue(vue: str) -> dict:
    try:
        resultat = subprocess.run(
            ["operer", "--json", vue], capture_output=True, text=True,
            encoding="utf-8", timeout=DELAI, shell=False,
        )
    except FileNotFoundError:
        raise LectureImpossible("exécutable operer absent") from None
    except subprocess.TimeoutExpired:
        raise LectureImpossible(f"{vue} : délai de {DELAI} s dépassé") from None
    except UnicodeError:
        raise LectureImpossible(f"{vue} : JSON illisible") from None
    except OSError:
        raise LectureImpossible(f"{vue} : exécution impossible") from None
    if resultat.returncode:
        raise LectureImpossible(f"{vue} : code de sortie {resultat.returncode}")
    try:
        donnees = json.loads(resultat.stdout)
    except ValueError:
        raise LectureImpossible(f"{vue} : JSON illisible") from None
    if not isinstance(donnees, dict) or donnees.get("vue") != vue:
        raise LectureImpossible(f"{vue} : structure JSON invalide")
    return donnees


def _texte(objet: dict, cle: str, vue: str, obligatoire: bool = False) -> str | None:
    valeur = objet.get(cle)
    if (valeur is not None and not isinstance(valeur, str)) or (obligatoire and not valeur):
        raise LectureImpossible(f"{vue} : champ {cle} invalide")
    return valeur


def _elements(vue: dict, cle: str) -> list[dict]:
    valeurs = vue.get(cle)
    if not isinstance(valeurs, list) or not all(isinstance(v, dict) for v in valeurs):
        raise LectureImpossible(f"{vue['vue']} : champ {cle} invalide")
    return valeurs


def est_depot(dossier: str) -> bool:
    """Un dossier est un dépôt de projet s'il contient un `.git` (fichier ou dossier)."""
    return (Path(dossier) / ".git").exists()


def projet_du_dossier(dossier: str | None, depot=None) -> str | None:
    """Dernier segment du dossier seulement s'il est un dépôt ; la racine commune des projets donne None."""
    if not dossier:
        return None
    if (depot or est_depot)(dossier):
        return Path(dossier).name or None
    return None


def reduire(qui: dict, etat: dict, depot=None) -> dict:
    roles = []
    for role in _elements(qui, "roles"):
        dossier = _texte(role, "dossier", "qui")
        roles.append({
            "role": _texte(role, "role", "qui", obligatoire=True),
            "projet": projet_du_dossier(dossier, depot),
            "modele": _texte(role, "modele", "qui"),
            "effort": _texte(role, "effort", "qui"),
            "presence": _texte(role, "presence", "qui"),
        })
    projets = {}
    for element in _elements(etat, "elements"):
        if element.get("categorie") != "missions":
            continue
        projet = _texte(element, "projet", "etat", obligatoire=True)
        statut = _texte(element, "etat", "etat", obligatoire=True)
        executant = _texte(element, "executant", "etat")
        compte = projets.setdefault(projet, {"missions": {}, "executants": []})
        compte["missions"][statut] = compte["missions"].get(statut, 0) + 1
        genre = executant.split(":", 1)[0] if executant else None
        if genre in {"codex", "claude"} and genre not in compte["executants"]:
            compte["executants"].append(genre)
    for compte in projets.values():
        compte["missions"] = dict(sorted(compte["missions"].items()))
        compte["executants"].sort()
    if not isinstance(etat.get("totaux"), dict):
        raise LectureImpossible("etat : champ totaux invalide")
    return {"roles": roles, "projets": dict(sorted(projets.items())), "totaux": etat["totaux"]}


def relever(depot=None) -> dict:
    try:
        qui = lire_vue("qui")
        etat = lire_vue("etat")
        vue = {"statut": "ok", **reduire(qui, etat, depot)}
    except LectureImpossible as erreur:
        vue = {"statut": "echec", "raison": str(erreur)}
    return {"releve_le": maintenant_iso(), **vue}


def ecrire_releve(racine: Path) -> None:
    """Collecte commune à etat.py et à la commande autonome organisation.py."""
    organisation = relever()
    ecrire_json(racine / "raw" / "organisation.json", organisation)
    if organisation["statut"] == "echec":
        print(f"! AVERTISSEMENT : organisation OPÉRER non lue ({organisation['raison']})")
    else:
        print(f"Organisation OPÉRER : {len(organisation['roles'])} rôle(s), "
              f"{len(organisation['projets'])} projet(s) -> raw/organisation.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="organisation.py", description=__doc__)
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    ecrire_releve(args.racine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
