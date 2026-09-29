#!/usr/bin/env python3
"""Delta — journal des passages (D63, amendée le 29/09/2026).

Ajoute une ligne à `rapports/passages.log`, fichier unique qui ne fait que grandir : ouverture en ajout,
jamais de réécriture ; il n'est pas commité (rapports/ est ignoré par git). Format, séparateur ` | ` :

    AAAA-MM-JJ_HHMM | agent | périmètre | <n> éléments (<n> fort) | <commit court ou aucun> | <code de garde>

La date et l'heure sont celles de l'écriture (équivalent de `date +%Y-%m-%d_%H%M`). Code 0 : ligne ajoutée et
affichée. Code 2 : argument invalide, rien n'est écrit.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SEP = " | "


def ligne(agent: str, perimetre: str, elements: int, forts: int, commit: str, garde: int,
          quand: datetime | None = None) -> str:
    for nom, v in (("agent", agent), ("périmètre", perimetre)):
        if not v.strip() or "|" in v or "\n" in v:
            raise ValueError(f"{nom} vide ou contenant « | » ou un saut de ligne : {v!r}")
    if elements < 0 or forts < 0 or forts > elements:
        raise ValueError(f"compteurs incohérents : {elements} éléments, {forts} forts")
    if commit != "aucun" and not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise ValueError(f"commit : hash court ou « aucun » attendu, pas {commit!r}")
    if garde < 0:
        raise ValueError(f"code de garde négatif : {garde}")
    quand = quand or datetime.now()
    return SEP.join((quand.strftime("%Y-%m-%d_%H%M"), agent.strip(), perimetre.strip(),
                     f"{elements} éléments ({forts} fort)", commit, str(garde)))


def ajouter(racine: Path, texte: str) -> Path:
    f = racine / "rapports" / "passages.log"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as h:
        h.write(texte + "\n")
    return f


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="passages.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", required=True, help="delta-ia, codex…")
    p.add_argument("--perimetre", required=True, help="claude, actu, openai, kb-claude, kb-openai…")
    p.add_argument("--elements", type=int, required=True)
    p.add_argument("--forts", type=int, required=True)
    p.add_argument("--commit", required=True, help="hash court du commit du périmètre, ou « aucun »")
    p.add_argument("--garde", type=int, default=0, help="code de scripts/garde.py (0 sans garde)")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        texte = ligne(a.agent, a.perimetre, a.elements, a.forts, a.commit, a.garde)
    except ValueError as e:
        print(f"passages.py : {e}", file=sys.stderr)
        return 2
    ajouter(a.racine, texte)
    print(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
