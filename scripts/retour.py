#!/usr/bin/env python3
"""Delta — retour de Sylvain sur une entrée de la sélection hebdomadaire (S2) : écrit un retour, ou donne le bilan mensuel.

Usage :
  retour.py ID {utile|connu|sans_interet|a_revoir} [--json]     enregistre le retour d'aujourd'hui
  retour.py --bilan [AAAA-MM] [--json]                         bilan du mois (défaut : le mois en cours), lecture seule

ID est l'identifiant entre crochets du bref (`selection.py --bref`) ou le champ `id` de `selection.py --json`. Le retour est ajouté à
la fin de rapports/selection/retours.yaml (liste de {date, id, retour}, format lu par selection.py) : le dernier retour d'un id décide,
un autre retour le même jour le remplace, le même retour le même jour ne fait rien (code 0, « déjà enregistré »). L'identifiant doit
figurer dans une sélection déjà produite (rapports/selection/AAAA-Www.json). Rien n'est écrit dans docs/, dans kb-essais.yaml ni hors
de rapports/ : un retour `utile` et l'essai déclaré dans kb-essais.yaml (D119) restent deux gestes distincts. Le script se retrouve par
son propre chemin : il peut être lancé depuis n'importe quel répertoire (`<dépôt>/.venv/bin/python <dépôt>/scripts/retour.py …`).

Sortie : une ligne de texte, ou avec --json {"id", "retour", "date", "enregistre"} ({"mois", "semaines", "proposees", "avec_retour",
"repartition", "taux_utiles", "taux_utiles_sur_retours"} pour --bilan). Les erreurs vont sur stderr, une ligne.
Codes : 0 fait (ou déjà enregistré) ; 1 retours.yaml ou fichier de sélection illisible, écriture impossible ; 2 usage (retour hors
liste, mois mal formé) ; 3 identifiant absent de toute sélection.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib import selection as sel  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="retour.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("id", nargs="?", help="identifiant de l'entrée (entre crochets dans le bref)")
    p.add_argument("retour", nargs="?", help=" | ".join(sel.RETOURS))
    p.add_argument("--bilan", nargs="?", const="", metavar="AAAA-MM", help="bilan mensuel (lecture seule) au lieu d'écrire un retour")
    p.add_argument("--json", action="store_true", help="sortie JSON")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    p.add_argument("--jour", metavar="AAAA-MM-JJ", help=argparse.SUPPRESS)  # tests : date figée
    try:
        args = p.parse_args(argv)
    except SystemExit as e:  # argparse sort en 2 : même code que l'usage invalide, message déjà sur stderr
        return int(e.code or 0)
    dossier = args.racine / sel.DOSSIER
    try:
        jour = date.fromisoformat(args.jour) if args.jour else date.today()
    except ValueError:
        print(f"retour.py : --jour {args.jour!r} : AAAA-MM-JJ attendu", file=sys.stderr)
        return 2

    if args.bilan is not None:
        if args.id or args.retour:
            print("retour.py : --bilan ne prend ni identifiant ni retour", file=sys.stderr)
            return 2
        try:
            b = sel.bilan_mensuel(dossier, args.bilan or jour.strftime("%Y-%m"))
        except sel.SelectionInvalide as e:
            print(f"retour.py : {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"retour.py : {e}", file=sys.stderr)
            return 2
        print(json.dumps(b, ensure_ascii=False, indent=1) if args.json else sel.rendre_bilan(b))
        return 0

    if not args.id or not args.retour:
        print(f"retour.py : identifiant et retour attendus : retour.py ID {{{'|'.join(sel.RETOURS)}}}", file=sys.stderr)
        return 2
    if args.retour not in sel.RETOURS:
        print(f"retour.py : retour {args.retour!r} inconnu, attendu : {', '.join(sel.RETOURS)}", file=sys.stderr)
        return 2
    try:
        ligne, ajoutee = sel.enregistrer_retour(dossier, args.id, args.retour, jour)
    except sel.IdInconnu as e:
        courants = _ids_semaine(dossier, jour)
        suite = f" ; identifiants de la semaine : {', '.join(courants)}" if courants else " ; aucune sélection produite cette semaine (selection.py)"
        print(f"retour.py : {e}{suite}", file=sys.stderr)
        return 3
    except (sel.SelectionInvalide, OSError, ValueError) as e:
        print(f"retour.py : {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({**ligne, "enregistre": ajoutee}, ensure_ascii=False))
    else:
        print(f"Retour {'enregistré' if ajoutee else 'déjà enregistré'} : {ligne['id']} -> {ligne['retour']} ({ligne['date']})")
    return 0


def _ids_semaine(dossier: Path, jour: date) -> list[str]:
    from deltalib import semaine as sem
    try:
        doc = sel.lire_figee(dossier, sem.semaine_de(jour))
    except sel.SelectionInvalide:
        return []
    return [e["id"] for e in doc["entrees"]] if doc else []


if __name__ == "__main__":
    sys.exit(main())
