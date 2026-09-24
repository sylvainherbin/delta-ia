#!/usr/bin/env python3
"""Delta — base de référence (phase 4) : catalogue extrait de la documentation, lots et commentaires.

Usage :
  catalogue.py maj --perimetre {claude,openai} [--dry-run]     ré-extrait depuis raw/kb/ (sans réseau, sans modèle)
  catalogue.py inventaire [--perimetre P]                      comptes par produit, catégorie et gabarit
  catalogue.py lots --perimetre P                              découpage en lots (catégorie ou demi-catégorie, D46)
  catalogue.py a-commenter --perimetre P --lot LOT [--tout]    entrées du lot à commenter (JSON sur la sortie)
  catalogue.py a-commenter --perimetre P --lot perimees        30 entrées au plus (D64-bis) : a) section citée modifiée ou
                                                               dépréciée ; b) antérieures à D64 en utiliser/tester ;
                                                               c) filet par âge (90 j + sha1(id) mod 90) ; champ `motif`
  catalogue.py reevaluations --perimetre P [--depuis J]        réévaluations du journal et taux de verdicts changés
  catalogue.py a-commenter --perimetre P --lot nouveau-projet:2.6   « ignorer » des fonctionnalités et commandes à relire
                                                               pour un nouveau projet de CONTEXTE §2 (D64)
  catalogue.py appliquer --perimetre P --fichier commentaires.json
      commentaires = {id: {description, statut_usage, recommandation: {verdict, pourquoi},
                           contexte_sections: {ctx-id: "pourquoi, une ligne, 160 car. max"}, exemple?, disponibilite?}}
      (ctx-id : `scripts/contexte.py` ; {} si le jugement ne dépend d'aucune section ; D64-bis)
      `usage` n'est jamais modifiable par un commentaire.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.kb import catalogue as cat  # noqa: E402
from deltalib.kb.documentation import charger_documentation  # noqa: E402
from deltalib.kb.modeles import CATEGORIES, gabarit_de  # noqa: E402
from deltalib.contexte import deprecies as deprecies_contexte, empreintes as empreintes_sections, resoudre as resoudre_sections  # noqa: E402
from deltalib.modeles import empreinte_contexte  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="catalogue.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("commande", choices=["maj", "inventaire", "lots", "a-commenter", "appliquer", "reevaluations"])
    p.add_argument("--depuis", help="avec reevaluations : AAAA-MM-JJ (défaut : aujourd'hui)")
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
        if cat.PERIMEES_SUSPENDU:
            print(f"{'perimees':<22} suspendu")
        else:
            tout = cat.perimees_detail(entrees, empreintes_sections(a.racine), deprecies_contexte(a.racine), maximum=None)
            if tout:
                n = {c: sum(1 for x in tout if x["categorie"] == c) for c in "abc"}
                print(f"{'perimees':<22} {'(D64bis)':<8} {min(len(tout), cat.PERIMEES_MAX):>4} entrées ce lancement sur {len(tout)} dues "
                      f"(a section {n['a']}, b antérieures {n['b']}, c âge {n['c']})")
        for k in cat.nouveaux_projets(a.racine, a.perimetre):
            n = len(cat.repasse_projet(entrees, k))
            print(f"{'nouveau-projet:' + k:<22} {'court':<8} {n:>4} entrées « ignorer » à relire (D64)")
        for l in cat.lots(entrees, a.perimetre):
            print(f"{l['lot']:<22} {l['gabarit']:<8} {l['entrees']:>4} entrées, {l['a_commenter']:>4} à commenter")
        return 0
    if a.commande == "a-commenter":
        motifs = {}
        if a.lot == "perimees" and cat.PERIMEES_SUSPENDU:
            print("lot perimees suspendu (catalogue.PERIMEES_SUSPENDU)", file=sys.stderr)
            return 3
        if a.lot == "perimees":
            det = cat.perimees_detail(entrees, empreintes_sections(a.racine), deprecies_contexte(a.racine))
            lot = {"ids": [x["id"] for x in det]}
            motifs = {x["id"]: x["motif"] for x in det}
            a.tout = True
        elif a.lot and a.lot.startswith("nouveau-projet:"):
            lot = {"ids": cat.repasse_projet(entrees, a.lot.split(":", 1)[1])}
            a.tout = True
        else:
            lot = next((l for l in cat.lots(entrees, a.perimetre) if l["lot"] == a.lot), None)
        if lot is None:
            p.error(f"lot inconnu : {a.lot!r} (voir `catalogue.py lots`)")
        champs = ["id", "produit", "categorie", "nom", "gabarit", "usage", "usage_nature", "description_source", "sources", "groupe",
                  "description", "statut_usage", "recommandation", "exemple", "contexte_empreinte", "contexte_sections"]
        sortie = [{**{k: entrees[i].get(k) for k in champs}, **({"motif": motifs[i]} if i in motifs else {})}
                  for i in lot["ids"] if a.tout or not entrees[i].get("commentee")]
        json.dump(sortie, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    if a.commande == "reevaluations":
        depuis = a.depuis or date.today().isoformat()
        f = cat.dossier(a.racine, a.perimetre) / "reevaluations.jsonl"
        lignes = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
        lignes = [l for l in lignes if l["date"] >= depuis]
        changes = [l for l in lignes if l["verdict_avant"] != l["verdict_apres"]]
        taux = f"{100 * len(changes) / len(lignes):.0f} %" if lignes else "sans objet"
        print(f"réévaluations depuis le {depuis} : {len(lignes)}, verdicts changés : {len(changes)} ({taux})")
        for m, n in Counter(l["motif"].split(":")[0] for l in lignes).most_common():
            print(f"  {m} : {n}")
        return 0
    if a.commande == "appliquer":
        if not a.fichier:
            p.error("--fichier requis")
        courantes, dep = empreintes_sections(a.racine), deprecies_contexte(a.racine)
        nouveaux = cat.nouveaux_projets(a.racine, a.perimetre)

        def motif_de(e):
            c = cat.classer(e, courantes, dep, date.today())
            if c:
                return c[1]
            for k in nouveaux:
                if e["id"] in cat.repasse_projet(entrees, k):
                    return f"nouveau-projet:{k}"
            return None
        journal = []
        erreurs = cat.appliquer_commentaires(entrees, json.loads(a.fichier.read_text(encoding="utf-8")), contexte=contexte,
                                             resoudre=lambda cites: resoudre_sections(a.racine, cites),
                                             journal=journal, motif_de=motif_de)
        for e in erreurs:
            print(f"  ! {e}", file=sys.stderr)
        if erreurs:
            print(f"{len(erreurs)} erreur(s) : rien n'est écrit", file=sys.stderr)
            return 1
        if not a.dry_run:
            cat.ecrire(a.racine, a.perimetre, entrees)
            if journal:  # B3 : une ligne par réévaluation
                with open(cat.dossier(a.racine, a.perimetre) / "reevaluations.jsonl", "a", encoding="utf-8") as f:
                    for l in journal:
                        f.write(json.dumps(l, ensure_ascii=False) + "\n")
        if journal:
            changes = sum(1 for l in journal if l["verdict_avant"] != l["verdict_apres"])
            print(f"réévaluations : {len(journal)}, verdicts changés : {changes} ({100 * changes / len(journal):.0f} %)")
        print(f"commentaires appliqués ; {sum(1 for e in entrees.values() if e.get('commentee'))}/{len(entrees)} commentées")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
