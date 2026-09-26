#!/usr/bin/env python3
"""Delta — récupération déterministe des sources et détection des nouveautés.

Usage :
  fetch.py --perimetre {claude,openai,actu} [--depuis AAAA-MM-JJ] [--dry-run] [--sources sources.yaml]
  fetch.py --perimetre <p> --valider [--date AAAA-MM-JJ] [--dry-run]
  fetch.py --kb PRODUIT [PRODUIT…] [--dry-run]   (documentation de référence, D44)

Sans `--valider`, l'état `state/<p>.json` n'est jamais modifié : les nouveautés vont dans
`raw/<p>-nouveautes.json`. `--valider` lit le fichier quotidien docs/data/<p>/<date>.json et n'inscrit
dans l'état que ce qu'il comptabilise (ids_bruts, ecartes, web-*) plus les ignorés du brut ; les
nouveautés absentes restent en attente (code de sortie 4).
`--kb` : code 3 = échec partiel (des pages ou des documentations en échec, les autres traitées normalement) ;
code 5 = échec total (aucune page lue, ou toutes les documentations d'un périmètre en échec) ; D68.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.etat import DOSSIERS, charger_etat, ecrire_json, valider  # noqa: E402
from deltalib.http import Client  # noqa: E402
from deltalib.modeles import PERIMETRES  # noqa: E402
from deltalib.passage import executer  # noqa: E402
from deltalib.sources import ErreurConfiguration, charger_sources, sources_du_perimetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"date attendue au format AAAA-MM-JJ : {s!r}") from e


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fetch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--perimetre", choices=PERIMETRES, help="périmètre à traiter (obligatoire sauf avec --kb)")
    p.add_argument("--kb", nargs="+", metavar="PRODUIT", choices=["claude", "claude-code", "chatgpt", "codex"],
                   help="récupère les pages de documentation de ces produits (raw/kb/) et met à jour le catalogue")
    p.add_argument("--kb-sans-reseau", action="store_true", help=argparse.SUPPRESS)  # tests : extraction depuis raw/kb seul
    p.add_argument("--valider", action="store_true", help="faire avancer l'état à partir des nouveautés en attente")
    p.add_argument("--depuis", type=_date, metavar="AAAA-MM-JJ", help="ne retenir que les éléments datés à partir de ce jour")
    p.add_argument("--date", type=_date, metavar="AAAA-MM-JJ", help="avec --valider : date du fichier quotidien (défaut : aujourd'hui)")
    p.add_argument("--dry-run", action="store_true", help="n'écrire aucun fichier")
    p.add_argument("--sources", default=str(RACINE / "sources.yaml"), help="fichier des sources (défaut : sources.yaml)")
    p.add_argument("--racine", default=str(RACINE), help=argparse.SUPPRESS)  # pour les tests
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def commande_valider(perimetre: str, racine: Path, dry_run: bool, jour: date | None) -> int:
    """D5, D13 : l'état n'avance que pour ce que le fichier quotidien de l'agent comptabilise."""
    chemin_brut = racine / "raw" / f"{perimetre}-nouveautes.json"
    chemin_etat = racine / "state" / f"{perimetre}.json"
    jour = jour or date.today()
    chemin_quotidien = racine / "docs" / "data" / DOSSIERS[perimetre] / f"{jour.isoformat()}.json"
    if not chemin_brut.exists():
        print(f"aucun fichier de nouveautés en attente : {chemin_brut}", file=sys.stderr)
        return 2
    if not chemin_quotidien.exists():
        print(f"fichier quotidien absent : {chemin_quotidien} (écrire la synthèse avant --valider, ou passer --date)", file=sys.stderr)
        return 2
    with open(chemin_brut, encoding="utf-8") as f:
        brut = json.load(f)
    with open(chemin_quotidien, encoding="utf-8") as f:
        quotidien = json.load(f)
    if brut.get("perimetre") != perimetre:
        print(f"le fichier {chemin_brut} concerne le périmètre {brut.get('perimetre')!r}, pas {perimetre!r}", file=sys.stderr)
        return 2
    if quotidien.get("perimetre") != perimetre or quotidien.get("date") != jour.isoformat():
        print(f"le fichier {chemin_quotidien} n'est pas celui du périmètre {perimetre!r} au {jour}", file=sys.stderr)
        return 2
    etat = charger_etat(chemin_etat)
    etat, bilan = valider(etat, brut, quotidien)
    prefixe = "[dry-run] " if dry_run else ""
    print(f"{prefixe}état {chemin_etat} : {bilan['inscrits']} inscrit(s), {bilan['revises']} révisé(s), "
          f"{len(etat['vus'])} au total ; {len(bilan['en_attente'])} nouveauté(s) en attente")
    titres = {e["id"]: e.get("titre", "") for e in brut.get("nouveautes", [])}
    for i in bilan["en_attente"]:
        print(f"  ? en attente  {i}  {titres.get(i, '')[:70]}")
    for i in bilan["inconnus"]:
        print(f"  ! inconnu     {i}  (présent dans le fichier quotidien, absent du brut et de l'état)")
    if not bilan["borne_avancee"]:
        print(f"  borne (maj_le) inchangée : {etat.get('maj_le')} — couverture incomplète")
    if not dry_run:
        ecrire_json(chemin_etat, etat)
    return 4 if bilan["en_attente"] or bilan["inconnus"] else 0


def commande_recuperer(args, racine: Path) -> int:
    try:
        sources = sources_du_perimetre(charger_sources(args.sources), args.perimetre)
    except (ErreurConfiguration, OSError) as e:
        print(f"sources.yaml : {e}", file=sys.stderr)
        return 2
    if not sources:
        print(f"aucune source active pour le périmètre {args.perimetre!r}", file=sys.stderr)
        return 2
    chemin_etat = racine / "state" / f"{args.perimetre}.json"
    bilan = executer(args.perimetre, sources, chemin_etat, Client(), depuis=args.depuis)
    brut = bilan.en_dict()
    chemin_brut = racine / "raw" / f"{args.perimetre}-nouveautes.json"
    if args.dry_run:
        print(f"[dry-run] rien n'est écrit ({chemin_brut})")
    else:
        ecrire_json(chemin_brut, brut)
    print(f"périmètre {args.perimetre} : {len(bilan.sources_traitees)}/{len(sources)} source(s) traitée(s), "
          f"{bilan.elements_total} élément(s) lus, {len(bilan.nouveautes)} nouveauté(s), "
          f"{len(bilan.ignores)} ignoré(s)" + (f" (fenêtre depuis {bilan.fenetre_depuis})" if bilan.fenetre_depuis else "")
          + (f", borne {bilan.borne}" if bilan.borne else ""))
    for s in bilan.sources_amorcees:
        print(f"  ~ amorçage   {s} : aucune trace dans l'état, fenêtre limitée (D30)")
    for e in bilan.nouveautes[:20]:
        print(f"  {'~' if e.revision else '+'} {e.date_publication or '????-??-??'}  {e.produit:<11} {e.titre[:80]}")
    if len(bilan.nouveautes) > 20:
        print(f"  … et {len(bilan.nouveautes) - 20} autre(s)")
    for ec in bilan.echecs:
        print(f"  ! {'partiel ' if ec.partiel else 'ÉCHEC   '}{ec.id} : {ec.erreur}")
    if not args.dry_run:
        print(f"nouveautés écrites dans {chemin_brut} ; l'état {chemin_etat} n'a pas été modifié")
    if len(bilan.sources_traitees) == 0:
        return 3
    return 0


def commande_kb(args, racine: Path) -> int:
    """D44 : pages de référence -> raw/kb/ (empreintes) -> catalogue docs/data/kb/<p>/ -> raw/kb/<p>-modifications.json."""
    from deltalib.kb import catalogue
    from deltalib.kb.documentation import ErreurDocumentation, charger_documentation, recuperer
    try:
        docs = [d for d in charger_documentation(args.sources) if d.produit in args.kb and d.active]
    except (ErreurDocumentation, OSError) as e:
        print(f"sources.yaml (documentation) : {e}", file=sys.stderr)
        return 2
    if not docs:
        print(f"aucune documentation active pour {args.kb}", file=sys.stderr)
        return 2
    bilan_pages = {"pages": 0, "modifiees": [], "nouvelles": [], "echecs": [], "redirections": []}
    if not args.kb_sans_reseau:
        bilan_pages = recuperer(racine, docs, Client, ecrire=not args.dry_run)  # D47 : dry-run n'écrit rien
    print(f"documentation {' '.join(args.kb)} : {bilan_pages['pages']} page(s) lue(s), "
          f"{len(bilan_pages['nouvelles'])} nouvelle(s), {len(bilan_pages['modifiees'])} modifiée(s), "
          f"{len(bilan_pages['echecs'])} en échec, {len(bilan_pages.get('redirections', []))} redirection(s)")
    for e in bilan_pages["echecs"]:
        print(f"  ! ÉCHEC   {e['doc']}/{e['fichier']} : {e['erreur']}")
    code = 3 if bilan_pages["echecs"] else 0  # page illisible : sa copie précédente reste en place, les autres avancent
    if not args.kb_sans_reseau and bilan_pages["pages"] == 0:
        print("  ! ÉCHEC TOTAL : aucune page de documentation lue")
        code = 5
    for r in bilan_pages.get("redirections", []):  # jamais suivie en silence, même si la page reste lisible
        page = r["fichier"].removeprefix("page:")
        print(f"  → REDIRECTION {r['doc']}/{page} : {r['ancienne']} → {r['nouvelle']} "
              f"({', '.join(map(str, r['statuts']))})")
    for perimetre in sorted({d.perimetre for d in docs}):
        res = catalogue.mettre_a_jour(racine, perimetre, docs, ecrire_fichiers=not args.dry_run,
                                      surcharge=bilan_pages.get("textes"))
        res["pages"] = {k: v for k, v in bilan_pages.items() if k not in ("pages", "textes")}
        chemin = racine / "raw" / "kb" / f"{perimetre}-modifications.json"
        if not args.dry_run:
            ecrire_json(chemin, res)
        print(f"catalogue {perimetre} : {res['total']} entrée(s), {len(res['ajoutees'])} ajoutée(s), "
              f"{len(res['usage_modifie'])} usage(s) modifié(s), {len(res['description_source_modifiee'])} description(s) "
              f"d'origine modifiée(s), {len(res['retirees'])} retirée(s), "
              f"{len(res['a_commenter'])} à commenter" + ("" if args.dry_run else f" -> {chemin}"))
        for e in res["echecs"]:
            print(f"  ! ÉCHEC   {e['doc']}" + (f" / {e['page']}" if e.get("page") else "") + f" : {e['erreur']}")
            code = max(code, 3)
        docs_per = {d.id for d in docs if d.perimetre == perimetre}
        # une documentation est en échec total quand elle ne produit rien (échec sans « page ») ; si toutes le sont : code 5
        totales = {e["doc"] for e in res["echecs"] if not e.get("page")}
        if docs_per and docs_per <= totales:
            print(f"  ! ÉCHEC TOTAL : toutes les documentations du périmètre {perimetre} sont en échec")
            code = 5
        for e in res.get("avertissements", []):
            print(f"  ~ REPLI   {e['doc']} / {e['page']} : {e['avertissement']}")
    return code


def main(argv: list[str] | None = None) -> int:
    args = construire_parseur().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    racine = Path(args.racine)
    if args.kb:
        return commande_kb(args, racine)
    if not args.perimetre:
        construire_parseur().error("--perimetre est obligatoire (sauf avec --kb)")
    if args.valider:
        return commande_valider(args.perimetre, racine, args.dry_run, args.date)
    return commande_recuperer(args, racine)


if __name__ == "__main__":
    sys.exit(main())
