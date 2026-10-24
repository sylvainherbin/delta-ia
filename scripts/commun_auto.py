#!/usr/bin/env python3
"""Produit et publie la génération commune (lot L2 des deux couches), sous le verrou de la chaîne nocturne.

Appelé par delta-ia-commun.service depuis le dépôt principal après fusion, une fois par jour après la chaîne :
1. import dans les racines de l'installation historique (magasin personnel et génération commune hors du dépôt) ;
   extraction de la base sans filtre de système depuis `raw/kb/`, traductions dans `kb-traductions/fr.json` au plus
   `production.budget_traduction` textes nouveaux (0 par défaut : cache seul) ;
2. publication dans la route versionnée `docs/commun/v1/` (génération active et précédente, `index.json`) ;
3. validation de la route, commit des seuls chemins `docs/commun/v1/` et `kb-traductions/fr.json`, push.
Les routes actuelles (`docs/data`) ne sont ni lues autrement qu'en entrée ni modifiées. Une erreur laisse les fichiers
en place, sans reset ni rebase automatique. Sans distant, commit local seulement.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from deltalib.couches import config as mod_config
from deltalib.couches import publication
from deltalib.couches import racines as mod_racines
from deltalib.couches.projection import importer
from deltalib.couches.traduction import RedacteurClaude

RACINE = Path(__file__).resolve().parent.parent
ROUTE = Path("docs/commun/v1")
CACHE = Path("kb-traductions/fr.json")


def git(racine: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    res = subprocess.run(["git", *args], cwd=racine, env=env, capture_output=True, text=True, timeout=300)
    if res.returncode:
        raise RuntimeError(f"git {' '.join(args)} : {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout.strip()


def est_publie(chemin: str) -> bool:
    """Seuls chemins que ce service écrit : la route versionnée et le cache de traductions."""
    return chemin == CACHE.as_posix() or chemin.startswith(ROUTE.as_posix() + "/")


def changements(racine: Path) -> set[str]:
    sortie = set(filter(None, git(racine, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all").split("\0")))
    return {ligne[3:] for ligne in sortie if len(ligne) > 3}


def verifier_arbre(racine: Path) -> None:
    hors = sorted(c for c in changements(racine) if not est_publie(c))
    if hors:
        raise RuntimeError(f"arbre modifié hors de la route commune ({len(hors)} chemin(s)) ; aucune publication")


def publier(racine: Path, maintenant: datetime) -> str:
    if git(racine, "branch", "--show-current") != "main":
        raise RuntimeError("publication réservée à main après fusion")
    verifier_arbre(racine)
    distant = bool(git(racine, "remote"))
    if distant:
        git(racine, "fetch", "origin", "main")
        if git(racine, "rev-list", "--count", "origin/main..HEAD") != "0":
            raise RuntimeError("commit local non publié ; intervention requise")
        git(racine, "merge", "--ff-only", "origin/main")
    racines = mod_racines.resoudre(historique=True)
    conf = mod_config.charger(racines)
    budget = conf["production"]["budget_traduction"]
    redacteur = RedacteurClaude(conf["production"]["modele_traduction"]) if budget > 0 else None
    res = importer(racine, racines, traductions=racine / CACHE, redacteur=redacteur, budget=budget)
    pub = publication.publier(racines, racine / ROUTE, maintenant, conf["production"]["cycle_attendu_h"])
    erreurs = publication.valider_route(racine / ROUTE)
    if erreurs:
        raise RuntimeError(f"route commune invalide : {erreurs[0]}")
    verifier_arbre(racine)
    git(racine, "add", "--", ROUTE.as_posix(), *([CACHE.as_posix()] if (racine / CACHE).exists() else []))
    indexes = set(filter(None, git(racine, "diff", "--cached", "--name-only", "-z").split("\0")))
    if any(not est_publie(c) for c in indexes):
        raise RuntimeError("index modifié hors de la route commune ; aucun commit")
    if indexes:
        jour = maintenant.astimezone(ZoneInfo("Europe/Paris")).date().isoformat()
        git(racine, "commit", "-m", f"delta(commun): {jour} — génération {pub['generation']}", "--",
            ROUTE.as_posix(), *([CACHE.as_posix()] if (racine / CACHE).exists() else []))
        if distant:
            git(racine, "push", "origin", f"{git(racine, 'rev-parse', 'HEAD')}:refs/heads/main")
    trad = res.traduction or {}
    return (f"commun-auto : {pub['generation']} ({'nouvelle' if pub['nouvelle'] else 'inchangée'}), "
            f"{res.textes['traduits_fr']}/{res.textes['textes']} textes en français, "
            f"{trad.get('acceptees', 0)} traduits ce jour")


def executer(racine: Path, maintenant: datetime) -> str:
    commun = Path(git(racine, "rev-parse", "--git-common-dir"))
    if not commun.is_absolute():
        commun = racine / commun
    # Même verrou que la chaîne de 04:00 et la sélection du lundi : attente bornée par TimeoutStartSec du service.
    with (commun / "delta-passage.lock").open("a") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        return publier(racine, maintenant)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        print(executer(args.racine.resolve(), datetime.now(ZoneInfo("Europe/Paris"))))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"commun-auto : {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
