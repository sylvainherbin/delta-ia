#!/usr/bin/env python3
"""Entrée du lanceur de missions : vérification ciblée, ou suite complète avec --fusion."""

import os
from pathlib import Path
import subprocess
import sys


def main():
    racine = Path(__file__).resolve().parents[2]
    commun = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=racine, text=True, timeout=10,
    ).strip())
    # Les worktrees partagent les dépendances du dépôt principal si leur .venv est absent.
    candidats = [racine / ".venv/bin/python", commun.parent / ".venv/bin/python", Path(sys.executable)]
    python = next(p for p in candidats if p.is_file() and os.access(p, os.X_OK))
    args = sys.argv[1:]
    if "--fusion" in args:
        args = [a for a in args if a != "--fusion"] + ["--sans-cache"]
    elif not args:
        args = ["--cible"]
    os.chdir(racine)
    os.execv(str(python), [str(python), "-B", str(racine / "scripts/verifier.py"), *args])


if __name__ == "__main__":
    main()
