#!/usr/bin/env python3
"""Delta — base de référence (phase 4) : catalogue extrait de la documentation, lots et commentaires.

Usage :
  catalogue.py maj --perimetre {claude,openai} [--dry-run]     ré-extrait depuis raw/kb/ (sans réseau, sans modèle)
  catalogue.py inventaire [--perimetre P]                      comptes par produit, catégorie et gabarit
  catalogue.py lots --perimetre P                              découpage en lots (catégorie ou demi-catégorie, D46)
  catalogue.py a-commenter --perimetre P --lot LOT [--tout]    entrées du lot à commenter (JSON sur la sortie)
  catalogue.py a-commenter --perimetre P --lot perimees        30 entrées `utiliser` ou `tester` au plus, commentées avec
                                                               un autre CONTEXTE.md (D60), à réévaluer en priorité
  catalogue.py appliquer --perimetre P --fichier commentaires.json
      commentaires = {id: {description, statut_usage, recommandation: {verdict, pourquoi}, exemple?, disponibilite?}}
      `usage` n'est jamais modifiable par un commentaire.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.kb import catalogue as cat  # noqa: E402
from deltalib.kb.documentation import charger_documentation  # noqa: E402
from deltalib.kb.modeles import CATEGORIES, gabarit_de  # noqa: E402
from deltalib.modeles import empreinte_contexte  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="catalogue.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("commande", choices=["maj", "inventaire", "lots", "a-commenter", "appliquer"])
    p.add_argument("--perimetre", choices=["claude", "openai"])
    p.add_argument("--lot")
    p.add_argument("--tout", action="store_true", help="avec a-commenter : inclure les entrées déjà commentées")
    p.add_argument("--fichier", type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    p.add_argument("--sources", type=Path, default=None, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    perimetres = [a.perimetre] if a.perimetre else ["claude", "openai"]
    if a.commande == "maj":
        docs = charger_documentation(a.sources or a.racine / "sources.yaml")
        code = 0
        for per in perimetres:
            r = cat.mettre_a_jour(a.racine, per, docs, ecrire_fichiers=not a.dry_run)
            print(f"{per} : {r['total']} entrées, {len(r['ajoutees'])} ajoutées, {len(r['usage_modifie'])} usages modifiés, "
                  f"{len(r['retirees'])} retirées, {len(r['a_commenter'])} à commenter")
            for e in r["echecs"]:
                print(f"  ! {e['doc']} : {e['erreur']}")
                code = 3
        return code
    if a.commande == "inventaire":
        for per in perimetres:
            ent = [e for e in cat.charger(a.racine, per).values() if not e.get("retiree")]
            c = Counter((e["produit"], e["categorie"]) for e in ent)
            print(f"== {per} : {len(ent)} entrées ({sum(1 for e in ent if e['gabarit'] == 'complet')} complet, "
                  f"{sum(1 for e in ent if e['gabarit'] == 'court')} court), {sum(1 for e in ent if e.get('commentee'))} commentées")
            produits = sorted({e["produit"] for e in ent})
            print("   " + "".join(f"{x:>16}" for x in ["catégorie", *produits, "total"]))
            for k in CATEGORIES:
                ligne = [c[(pr, k)] for pr in produits]
                print("   " + f"{k:>16}" + "".join(f"{n:>16}" for n in ligne) + f"{sum(ligne):>16}")
        return 0
    if not a.perimetre:
        p.error("--perimetre est obligatoire pour cette commande")
    entrees = cat.charger(a.racine, a.perimetre)
    contexte = empreinte_contexte(a.racine)
    if a.commande == "lots":
        per = cat.perimees(entrees, contexte)
        if per:
            print(f"{'perimees':<22} {'(D60)':<8} {len(per):>4} entrées, {len(per):>4} à réévaluer en priorité")
        for l in cat.lots(entrees, a.perimetre):
            print(f"{l['lot']:<22} {l['gabarit']:<8} {l['entrees']:>4} entrées, {l['a_commenter']:>4} à commenter")
        return 0
    if a.commande == "a-commenter":
        if a.lot == "perimees":
            lot = {"ids": cat.perimees(entrees, contexte)}
            a.tout = True
        else:
            lot = next((l for l in cat.lots(entrees, a.perimetre) if l["lot"] == a.lot), None)
        if lot is None:
            p.error(f"lot inconnu : {a.lot!r} (voir `catalogue.py lots`)")
        champs = ["id", "produit", "categorie", "nom", "gabarit", "usage", "usage_nature", "description_source", "sources", "groupe",
                  "description", "statut_usage", "recommandation", "exemple", "contexte_empreinte"]
        sortie = [{k: entrees[i].get(k) for k in champs} for i in lot["ids"] if a.tout or not entrees[i].get("commentee")]
        json.dump(sortie, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    if a.commande == "appliquer":
        if not a.fichier:
            p.error("--fichier requis")
        erreurs = cat.appliquer_commentaires(entrees, json.loads(a.fichier.read_text(encoding="utf-8")), contexte=contexte)
        for e in erreurs:
            print(f"  ! {e}", file=sys.stderr)
        if erreurs:
            print(f"{len(erreurs)} erreur(s) : rien n'est écrit", file=sys.stderr)
            return 1
        if not a.dry_run:
            cat.ecrire(a.racine, a.perimetre, entrees)
        print(f"commentaires appliqués ; {sum(1 for e in entrees.values() if e.get('commentee'))}/{len(entrees)} commentées")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
