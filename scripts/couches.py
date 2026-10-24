#!/usr/bin/env python3
"""Delta-IA en deux couches, lots L1 et L2 : import privé, génération commune isolée, publication versionnée et miroir.

Usage :
  couches.py (--instance <profil.json> | --historique) importer [--depot <dépôt>] [--brut <dépôt>] [--traductions <fichier>]
             [--budget-traduction N] [--modele <alias>]
  couches.py (--instance <profil.json> | --historique) fiche <identité | id | nom> [--public] [--langue en|fr]
  couches.py (--instance <profil.json> | --historique) chercher <texte> [--limite N] [--public]
  couches.py (--instance <profil.json> | --historique) verifier [--depot <dépôt>]
  couches.py (--instance <profil.json> | --historique) publier --route <docs/commun/v1>
  couches.py (--instance <profil.json> | --historique) synchroniser [--url <route publiée>]
  couches.py surveiller (--route <dossier> | --url <route publiée>)

Dans une instance lancée par K1 (`DELTA_INSTANCE` posée), les racines viennent de l'environnement et l'option de
racines est inutile. `importer` lit `docs/data` et les journaux privés du dépôt sans les modifier, et écrit seulement sous
les racines de l'instance (jamais dans le dépôt). `--public` lit le commun seul, sans ouvrir la racine personnelle. `verifier --depot` ajoute le contrôle de
fidélité au dépôt (mêmes identités, avis et essais historiques retrouvés, empreintes des entrées inchangées).
`importer` traduit au plus `--budget-traduction` textes absents du cache (défaut : réglage `production.budget_traduction`,
0 = aucun appel de modèle), par le rédacteur isolé (`claude -p --safe-mode`, sans outil ni profil). `publier` copie la
génération active dans la route versionnée (instance productrice seulement, `mode: producteur` ou `--historique`).
`synchroniser` met le miroir local à jour depuis `reference_base_url` ; un échec garde la dernière génération valide.
`surveiller` signale un cycle de publication manqué ou un périmètre en retard (code 1).
Sorties JSON sur stdout ; aucun contenu personnel n'est imprimé par `importer` ni par `verifier`.
Codes : 0 succès, 1 refus, validation en échec, synchronisation en échec ou alerte, 2 usage, 75 magasin occupé.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.couches import config as mod_config  # noqa: E402
from deltalib.couches import publication  # noqa: E402
from deltalib.couches import racines as mod_racines  # noqa: E402
from deltalib.couches import schemas  # noqa: E402
from deltalib.couches.controle import fidelite  # noqa: E402
from deltalib.couches.lecteur import Lecteur  # noqa: E402
from deltalib.couches.projection import ImportImpossible, importer  # noqa: E402
from deltalib.couches.sentinelles import Detecteur  # noqa: E402
from deltalib.couches.stockage import MagasinOccupe  # noqa: E402
from deltalib.couches.traduction import CacheInvalide, RedacteurClaude  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def _sortir(doc) -> None:
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def verifier(racines: mod_racines.Racines) -> list[str]:
    """Génération active valide, magasin personnel lisible, droits privés sur les magasins."""
    erreurs = []
    lecteur = Lecteur(racines)
    if lecteur.commun_statut != "disponible":
        erreurs.append(f"commun : {lecteur.motif}")
    for nom in ("overlay", "en_attente", "import", "sources"):
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
    imp.add_argument("--brut", type=Path, help="dépôt dont raw/kb/ porte les pages de documentation (défaut : --depot)")
    imp.add_argument("--traductions", type=Path, help="cache de traductions (défaut : production/traductions-fr.json)")
    imp.add_argument("--budget-traduction", type=int, help="textes au plus envoyés au rédacteur (défaut : réglage)")
    imp.add_argument("--modele", help="modèle du rédacteur (défaut : réglage production.modele_traduction)")
    fi = sous.add_parser("fiche", help="fiche commune et bloc personnel d'une identité, d'un id ou d'un nom")
    fi.add_argument("ref")
    fi.add_argument("--public", action="store_true", help="commun seul, racine personnelle non ouverte")
    fi.add_argument("--langue", choices=("en", "fr"), help="langue des textes (défaut : réglage)")
    ch = sous.add_parser("chercher", help="recherche exacte puis plein texte dans le commun")
    ch.add_argument("texte")
    ch.add_argument("--limite", type=int, default=20)
    ch.add_argument("--public", action="store_true", help="commun seul, racine personnelle non ouverte")
    ve = sous.add_parser("verifier", help="valide la génération active et le magasin personnel")
    ve.add_argument("--depot", type=Path, help="contrôle aussi la fidélité de l'import à ce dépôt")
    pu = sous.add_parser("publier", help="copie la génération active dans la route versionnée et réécrit son index")
    pu.add_argument("--route", type=Path, required=True)
    sy = sous.add_parser("synchroniser", help="met le miroir commun à jour depuis la route publiée")
    sy.add_argument("--url", help="route publiée (défaut : reference_base_url)")
    su = sous.add_parser("surveiller", help="cycle de publication et couverture des périmètres du producteur")
    cible = su.add_mutually_exclusive_group(required=True)
    cible.add_argument("--route", type=Path)
    cible.add_argument("--url")
    args = p.parse_args(argv)
    if args.commande == "surveiller":
        if args.route is not None:
            try:
                index = json.loads((args.route / publication.INDEX).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"couches.py : index illisible : {e}", file=sys.stderr)
                return 1
        else:
            try:
                _, _, corps = publication.telecharger(args.url.rstrip("/") + "/" + publication.INDEX, {}, publication.TAILLE_INDEX)
                index = json.loads(corps.decode("utf-8"))
            except (publication.SynchroEchec, ValueError) as e:
                _sortir({"ok": False, "alertes": [f"index_indisponible: {e}"], "age_h": None})
                return 1
        res = publication.surveiller(index)
        _sortir(res)
        return 0 if res["ok"] else 1
    try:
        racines = mod_racines.resoudre(profil=args.instance, historique=args.historique)
    except mod_racines.RacinesInvalides as e:
        print(f"couches.py : {e}", file=sys.stderr)
        return 2
    try:
        conf = mod_config.charger(racines)
    except mod_config.ConfigInvalide as e:
        print(f"couches.py : {e}", file=sys.stderr)
        return 2
    if args.commande == "importer":
        budget = conf["production"]["budget_traduction"] if args.budget_traduction is None else args.budget_traduction
        redacteur = RedacteurClaude(args.modele or conf["production"]["modele_traduction"]) if budget > 0 else None
        try:
            res = importer(args.depot, racines, brut=args.brut, traductions=args.traductions, redacteur=redacteur,
                           budget=budget)
        except MagasinOccupe as e:
            print(f"couches.py : {e}", file=sys.stderr)
            return 75
        except (ImportImpossible, CacheInvalide) as e:
            print(f"couches.py : import refusé : {e}", file=sys.stderr)
            return 1
        motifs: dict[str, int] = {}
        for r in res.refus:
            motifs[r["motif"].split(":")[0]] = motifs.get(r["motif"].split(":")[0], 0) + 1
        _sortir({"generation": res.generation, "comptes": res.comptes, "refus_par_motif": motifs,
                 "changements": res.changements, "textes": res.textes, "traduction": res.traduction})
        return 0
    if args.commande == "publier":
        if conf["mode"] != "producteur" and racines.origine != "historique":
            print("couches.py : publication réservée à une instance productrice (mode producteur)", file=sys.stderr)
            return 1
        try:
            _sortir(publication.publier(racines, args.route, cycle_attendu_h=conf["production"]["cycle_attendu_h"]))
        except publication.PublicationImpossible as e:
            print(f"couches.py : {e}", file=sys.stderr)
            return 1
        return 0
    if args.commande == "synchroniser":
        try:
            res = publication.synchroniser(racines, args.url or conf["reference_base_url"])
        except MagasinOccupe as e:
            print(f"couches.py : {e}", file=sys.stderr)
            return 75
        _sortir(res)
        return 0 if res["statut"] != "echec" else 1
    if args.commande == "verifier":
        erreurs, comptes = verifier(racines), None
        if args.depot is not None and not erreurs:
            ecarts, comptes = fidelite(args.depot.resolve(), racines)
            erreurs += ecarts
        _sortir({"ok": not erreurs, "erreurs": erreurs, **({"fidelite": comptes} if comptes else {})})
        return 0 if not erreurs else 1
    langue = getattr(args, "langue", None) or conf["langue_utilisateur"] or conf["langue_commune_defaut"]
    lecteur = Lecteur(racines, personnel=not args.public, detecteur=Detecteur(), langue=langue, seuils=conf["fraicheur"])
    if args.commande == "fiche":
        _sortir(lecteur.fiche(args.ref))
    else:
        _sortir(lecteur.chercher(args.texte, args.limite))
    return 0


if __name__ == "__main__":
    sys.exit(main())
