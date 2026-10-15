#!/usr/bin/env python3
"""Produit et publie la sélection du lundi, sous le verrou de la chaîne nocturne.

Appelé par delta-ia-selection.service depuis le dépôt principal après fusion.
Avant le 19/10/2026 : aucune production. Sans distant, commit local seulement.
Une erreur laisse les fichiers et commits en place, sans reset ni rebase automatique.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from deltalib import selection as sel
from deltalib import semaine as sem

RACINE = Path(__file__).resolve().parent.parent
PREMIER_JOUR = date(2026, 10, 19)


def commande(racine: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    res = subprocess.run(args, cwd=racine, env=env, capture_output=True, text=True, timeout=300)
    if res.returncode:
        raise RuntimeError(f"{' '.join(args)} : {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout.strip()


def git(racine: Path, *args: str) -> str:
    return commande(racine, "git", *args)


def valider(racine: Path) -> None:
    for perimetre in ("claude", "openai", "actu"):
        commande(racine, sys.executable, "-B", "scripts/valider.py", "--perimetre", perimetre)


def publier(racine: Path, jour: date) -> None:
    semaine = sem.semaine_de(jour)
    chemins = [str(sel.DOSSIER / f"{semaine}.{ext}") for ext in ("json", "md")]
    message = f"delta(selection): {semaine} — sélection hebdomadaire"
    dossier = racine / sel.DOSSIER
    if git(racine, "branch", "--show-current") != "main":
        raise RuntimeError("publication réservée à main après fusion")
    # Autorise seulement les sorties de cette semaine restées après un échec avant commit.
    modifies = set(git(racine, "diff", "--name-only").splitlines())
    modifies.update(git(racine, "diff", "--cached", "--name-only").splitlines())
    modifies.update(git(racine, "ls-files", "--others", "--exclude-standard").splitlines())
    if modifies - set(chemins):
        raise RuntimeError("arbre ou index modifié hors sélection ; aucune publication")
    distant = bool(git(racine, "remote"))
    if distant:
        if "origin" not in git(racine, "remote").splitlines():
            raise RuntimeError("distant origin absent")
        git(racine, "fetch", "origin", "main")
        if git(racine, "rev-list", "--count", "origin/main..HEAD") != "0":
            # Reprise après échec du push : jamais de commit étranger dans la publication.
            if (git(racine, "rev-parse", "HEAD^") != git(racine, "rev-parse", "origin/main")
                    or git(racine, "log", "-1", "--format=%s") != message
                    or set(git(racine, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) != set(chemins)
                    or modifies):
                raise RuntimeError("commit local non publié ou divergence ; intervention requise")
            doc = sel.lire_figee(dossier, semaine)
            if doc is None or (dossier / f"{semaine}.md").read_text(encoding="utf-8") != sel.rendre_markdown(doc):
                raise RuntimeError("commit de sélection incomplet ou bref incohérent")
            valider(racine)
            git(racine, "push", "origin", f"{git(racine, 'rev-parse', 'HEAD')}:refs/heads/main")
            return
        # --ff-only ne réécrit aucun historique ; les sorties locales sont préservées ou Git refuse.
        git(racine, "merge", "--ff-only", "origin/main")

    doc, _ = sel.obtenir(racine, dossier, jour, sel.TAILLE_DEFAUT, sel.REVOIR_APRES_DEFAUT)
    if doc["semaine"] != semaine:
        raise RuntimeError("semaine produite incohérente")
    valider(racine)
    git(racine, "add", "--", *chemins)
    stages = set(git(racine, "diff", "--cached", "--name-only").splitlines())
    if stages - set(chemins):
        raise RuntimeError("index modifié hors sélection ; aucun commit")
    if stages:
        git(racine, "commit", "-m", message, "--", *chemins)
        if distant:
            git(racine, "push", "origin", f"{git(racine, 'rev-parse', 'HEAD')}:refs/heads/main")
    print(f"selection-auto : {semaine}, {len(doc['entrees'])} essais, JSON et bref disponibles")


def executer(racine: Path, jour: date) -> None:
    if jour < PREMIER_JOUR:
        print("selection-auto : première production le 19/10/2026, rien à produire")
        return
    commun = Path(git(racine, "rev-parse", "--git-common-dir"))
    if not commun.is_absolute():
        commun = racine / commun
    # Même inode que .git/delta-passage.lock du dépôt principal, y compris depuis un worktree.
    # L'attente est bornée par TimeoutStartSec du service (4 h 15).
    with (commun / "delta-passage.lock").open("a") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        publier(racine, jour)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        executer(args.racine.resolve(), datetime.now(ZoneInfo("Europe/Paris")).date())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"selection-auto : {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
