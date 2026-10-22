#!/usr/bin/env python3
"""Delta-IA en deux couches, lot L1 : import privé, projection commune et lecture locale.

Usage :
  couches.py (--instance <profil.json> | --historique) importer [--depot <dépôt>]
  couches.py (--instance <profil.json> | --historique) fiche <identité | id | nom> [--public]
  couches.py (--instance <profil.json> | --historique) chercher <texte> [--limite N] [--public]
  couches.py (--instance <profil.json> | --historique) verifier [--depot <dépôt>]

Dans une instance lancée par K1 (`DELTA_INSTANCE` posée), les racines viennent de l'environnement et l'option de
racines est inutile. `importer` lit `docs/data` et les journaux privés du dépôt sans les modifier, et écrit seulement sous
les racines de l'instance (jamais dans le dépôt). `--public` lit le commun seul, sans ouvrir la racine personnelle. `verifier --depot` ajoute le contrôle de
fidélité au dépôt (mêmes identités, avis et essais historiques retrouvés, empreintes des entrées inchangées).
Sorties JSON sur stdout ; aucun contenu personnel n'est imprimé par `importer` ni par `verifier`.
Codes : 0 succès, 1 refus ou validation en échec, 2 usage, 75 magasin occupé.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.couches import racines as mod_racines  # noqa: E402
from deltalib.couches import schemas  # noqa: E402
from deltalib.couches.controle import fidelite  # noqa: E402
from deltalib.couches.lecteur import Lecteur  # noqa: E402
from deltalib.couches.projection import ImportImpossible, importer  # noqa: E402
from deltalib.couches.sentinelles import Detecteur  # noqa: E402
from deltalib.couches.stockage import MagasinOccupe  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def _sortir(doc) -> None:
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def verifier(racines: mod_racines.Racines) -> list[str]:
    """Génération active valide, magasin personnel lisible, droits privés sur les magasins."""
    erreurs = []
    lecteur = Lecteur(racines)
    if lecteur.commun_statut != "disponible":
        erreurs.append(f"commun : {lecteur.motif}")
    for nom in ("overlay", "en_attente", "import"):
        chemin = racines.personnel / f"{nom}.json"
        try:
            doc = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            erreurs.append(f"personnel/{nom}.json illisible : {e}")
            continue
        erreurs += schemas.valider_personnel(doc, nom, f"personnel/{nom}.json")
        if not schemas.permissions_privees(chemin):
            erreurs.append(f"personnel/{nom}.json : droits ouverts au groupe ou aux autres")
        if doc.get("commun_generation") != lecteur.generation:
            erreurs.append(f"personnel/{nom}.json : génération {doc.get('commun_generation')} ≠ active {lecteur.generation}")
    if racines.personnel.is_dir() and not schemas.permissions_privees(racines.personnel):
        erreurs.append("personnel/ : droits ouverts au groupe ou aux autres")
    return erreurs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="couches.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = p.add_mutually_exclusive_group()
    source.add_argument("--instance", type=Path, help="profil d'instance K1 (delta.instance v1)")
    source.add_argument("--historique", action="store_true", help="racines XDG de l'installation historique (…/delta)")
    sous = p.add_subparsers(dest="commande", required=True)
    imp = sous.add_parser("importer", help="import privé et génération commune depuis le dépôt producteur")
    imp.add_argument("--depot", type=Path, default=RACINE, help="dépôt delta-ia lu (défaut : celui de ce script)")
    fi = sous.add_parser("fiche", help="fiche commune et bloc personnel d'une identité, d'un id ou d'un nom")
    fi.add_argument("ref")
    fi.add_argument("--public", action="store_true", help="commun seul, racine personnelle non ouverte")
    ch = sous.add_parser("chercher", help="recherche exacte puis plein texte dans le commun")
    ch.add_argument("texte")
    ch.add_argument("--limite", type=int, default=20)
    ch.add_argument("--public", action="store_true", help="commun seul, racine personnelle non ouverte")
    ve = sous.add_parser("verifier", help="valide la génération active et le magasin personnel")
    ve.add_argument("--depot", type=Path, help="contrôle aussi la fidélité de l'import à ce dépôt")
    args = p.parse_args(argv)
    try:
        racines = mod_racines.resoudre(profil=args.instance, historique=args.historique)
    except mod_racines.RacinesInvalides as e:
        print(f"couches.py : {e}", file=sys.stderr)
        return 2
    if args.commande == "importer":
        try:
            res = importer(args.depot, racines)
        except MagasinOccupe as e:
            print(f"couches.py : {e}", file=sys.stderr)
            return 75
        except ImportImpossible as e:
            print(f"couches.py : import refusé : {e}", file=sys.stderr)
            return 1
        motifs: dict[str, int] = {}
        for r in res.refus:
            motifs[r["motif"].split(":")[0]] = motifs.get(r["motif"].split(":")[0], 0) + 1
        _sortir({"generation": res.generation, "comptes": res.comptes, "refus_par_motif": motifs,
                 "changements": res.changements})
        return 0
    if args.commande == "verifier":
        erreurs, comptes = verifier(racines), None
        if args.depot is not None and not erreurs:
            ecarts, comptes = fidelite(args.depot.resolve(), racines)
            erreurs += ecarts
        _sortir({"ok": not erreurs, "erreurs": erreurs, **({"fidelite": comptes} if comptes else {})})
        return 0 if not erreurs else 1
    lecteur = Lecteur(racines, personnel=not args.public, detecteur=Detecteur())
    if args.commande == "fiche":
        _sortir(lecteur.fiche(args.ref))
    else:
        _sortir(lecteur.chercher(args.texte, args.limite))
    return 0


if __name__ == "__main__":
    sys.exit(main())
