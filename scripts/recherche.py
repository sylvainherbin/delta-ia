#!/usr/bin/env python3
"""Delta — index de recherche de la veille (D113) -> docs/data/recherche.json, sans modèle ni réseau.

Usage :
  recherche.py [--dry-run]

Recopie, pour chaque élément des fichiers quotidiens des trois périmètres (claude, actu, openai), son identifiant, sa date,
son périmètre, son titre, son impact et un texte court (`resume`, `pour_toi`, `action`, coupés à 600, 400 et 300 caractères) :
le site cherche dedans sans charger les jours. Aucune phrase n'est rédigée. Une source illisible donne `statut: echec` avec la
raison, signalée par une ligne `! AVERTISSEMENT` (code de sortie 0 : le fichier est écrit). Un contenu identique à l'existant
(hors `genere_le`) n'est pas réécrit. Code 1 : écriture impossible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib import recherche as rech  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="recherche.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="affiche un résumé de l'index sans rien écrire")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    doc = rech.construire(args.racine)
    if args.dry_run:
        print(json.dumps({**doc, "elements": doc["elements"][:3], "elements_affiches": min(3, doc["total"])}, ensure_ascii=False, indent=2))
        return 0
    try:
        ecrit = rech.ecrire(args.racine, doc)
    except OSError as e:
        print(f"recherche.py : écriture impossible ({e})", file=sys.stderr)
        return 1
    octets = (args.racine / rech.FICHIER).stat().st_size
    jours = " ".join(f"{nom} {len(s['jours'])}" for nom, s in doc["sources"].items())
    print(f"recherche.py : {'écrit' if ecrit else 'inchangé'} : {doc['total']} éléments (jours : {jours}), {octets} octets")
    if doc["statut"] != "ok":
        print(f"! AVERTISSEMENT recherche : statut echec : {doc['raison']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
