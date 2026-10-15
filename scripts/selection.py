#!/usr/bin/env python3
"""Delta — sélection hebdomadaire de 3 à 5 essais -> rapports/selection/AAAA-Www.json, sans modèle ni réseau.

Usage :
  selection.py [--semaine AAAA-Www] [--refaire] [--dry-run] [--taille N] [--revoir-apres JOURS]
               [--json | --bref | --expliquer]

Sans option, la sélection de la semaine ISO en cours : produite au premier appel de la semaine (le lundi si la commande y est
lancée), puis relue à l'identique (budget d'attention : jamais plus de 5 entrées distinctes par semaine). Candidats : les
entrées « À tester » de la base et les nouveautés de la veille des 7 derniers jours. Classement selon les priorités de
profil.yaml et les retours de Sylvain (rapports/selection/retours.yaml : liste de {date, id, retour}, retour = utile | connu |
sans_interet | a_revoir). « connu », « sans_interet » et « utile » ne reviennent pas ; « a_revoir » revient après
--revoir-apres jours (28 par défaut). Chaque entrée : quoi essayer, pourquoi pour toi, ce qui la rendrait caduque (tiré de
la fiche seule ; sinon l'entrée le dit). Le JSON et un bref Markdown de cinq lignes au plus sont écrits côte à côte.
Le minuteur hebdomadaire publie ces deux fichiers ; les retours restent locaux, rien n'entre dans docs/.

Sorties : texte (défaut), --json (contrat lu par le bref de Delta-pilote et par la console : entrées avec `rang`, `id`, `quoi`,
`pourquoi`, `caduque_si`, `classement`, `retour`, `retour_le`), --bref (une ligne par entrée), --expliquer (texte avec le
détail du barème). --dry-run calcule sans lire ni écrire le fichier de la semaine. --refaire recalcule la semaine (à n'utiliser
qu'en connaissance de cause : la liste proposée change).
Code 1 : base, retours ou fichier de la semaine illisibles, écriture impossible ; code 2 : option invalide.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib import selection as sel  # noqa: E402
from deltalib import semaine as sem  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="selection.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--semaine", metavar="AAAA-Www", help="semaine ISO à produire ou relire (défaut : la semaine en cours)")
    p.add_argument("--refaire", action="store_true", help="recalcule et réécrit la sélection de la semaine")
    p.add_argument("--dry-run", action="store_true", help="calcule sans lire ni écrire le fichier de la semaine")
    p.add_argument("--taille", type=int, default=sel.TAILLE_DEFAUT, help=f"entrées proposées, de {sel.TAILLE_MIN} à {sel.TAILLE_MAX} (défaut {sel.TAILLE_DEFAUT})")
    p.add_argument("--revoir-apres", type=int, default=sel.REVOIR_APRES_DEFAUT, metavar="JOURS",
                   help=f"délai avant qu'une entrée « a_revoir » revienne (défaut {sel.REVOIR_APRES_DEFAUT})")
    sortie = p.add_mutually_exclusive_group()
    sortie.add_argument("--json", action="store_true", help="document complet en JSON")
    sortie.add_argument("--bref", action="store_true", help="une ligne par entrée, pour le bref")
    sortie.add_argument("--expliquer", action="store_true", help="texte avec le détail du classement")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    p.add_argument("--jour", metavar="AAAA-MM-JJ", help=argparse.SUPPRESS)  # tests : date figée
    args = p.parse_args(argv)

    try:
        jour = date.fromisoformat(args.jour) if args.jour else date.today()
        if args.semaine:
            jour = sem.bornes(args.semaine)[0] if not args.jour else jour
            if args.jour and sem.semaine_de(jour) != args.semaine:
                raise ValueError("--jour n'est pas dans la semaine demandée")
    except (ValueError, sem.SemaineInvalide) as e:
        print(f"selection.py : {e}", file=sys.stderr)
        return 2
    if not sel.TAILLE_MIN <= args.taille <= sel.TAILLE_MAX or args.revoir_apres < 0:
        print(f"selection.py : --taille de {sel.TAILLE_MIN} à {sel.TAILLE_MAX} (budget d'attention) et --revoir-apres positif ou nul", file=sys.stderr)
        return 2
    dossier = args.racine / sel.DOSSIER
    try:
        if args.dry_run:
            doc = sel.annoter_retours(sel.classer(args.racine, dossier, jour, args.taille, args.revoir_apres), dossier)
            neuf = False
        else:
            doc, neuf = sel.obtenir(args.racine, dossier, jour, args.taille, args.revoir_apres, args.refaire)
    except sel.SelectionInvalide as e:
        print(f"selection.py : {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"selection.py : {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    elif args.bref:
        print(sel.rendre_bref(doc))
    else:
        print(sel.rendre_texte(doc, args.expliquer))
    if neuf and not (args.json or args.bref):
        print(f"(sélection {doc['semaine']} écrite : {dossier.relative_to(args.racine) / (doc['semaine'] + '.json')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
