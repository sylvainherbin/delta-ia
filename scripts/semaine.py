#!/usr/bin/env python3
"""Delta — bilan de la semaine (D98) -> docs/data/semaine/AAAA-Www.json et index.json, sans modèle ni réseau.

Usage :
  semaine.py [--semaine AAAA-Www] [--dry-run]

Sans option, la semaine ISO en cours (jour local). Rassemble, par recopie de champs publiés (aucune phrase rédigée) :
les éléments D71 (en tête), les éléments `fort` et `moyen` des trois périmètres, les entrées de la base ajoutées pendant la
semaine et celles passées au verdict `utiliser` ou `tester`. Le fichier est écrit même pour une semaine vide ; une source
illisible donne `statut: echec` avec la raison, signalée par une ligne `! AVERTISSEMENT` (code de sortie 0 : le fichier est écrit).
Limite connue : le passage `actu` produit le bilan avant `codex-delta` ; les éléments `openai` du jour n'y entrent que la nuit
suivante, et ceux du dimanche n'entrent pas dans la semaine close (la rattraper à la main le lundi avec `--semaine <précédente>`).
Un contenu identique à l'existant (hors `genere_le`) n'est pas réécrit. Code 1 : écriture impossible ; code 2 : semaine invalide.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib import semaine as sem  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="semaine.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--semaine", metavar="AAAA-Www", help="semaine ISO à produire (défaut : la semaine en cours)")
    p.add_argument("--dry-run", action="store_true", help="affiche le document sans rien écrire")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    semaine = args.semaine or sem.semaine_de(date.today())
    try:
        doc = sem.construire(args.racine, semaine)
    except sem.SemaineInvalide as e:
        print(f"semaine.py : {e}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    try:
        ecrit = sem.ecrire(args.racine, doc)
    except OSError as e:
        print(f"semaine.py : écriture impossible ({e})", file=sys.stderr)
        return 1
    print(f"semaine.py : {semaine} ({doc['du']} au {doc['au']}) {'écrit' if ecrit else 'inchangé'} : "
          f"{len(doc['d71'])} D71, {len(doc['elements'])} éléments, {len(doc['base_ajoutees'])} entrées ajoutées, "
          f"{len(doc['base_verdicts'])} verdicts")
    if doc["statut"] != "ok":
        print(f"! AVERTISSEMENT semaine {semaine} : statut echec : {doc['raison']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
