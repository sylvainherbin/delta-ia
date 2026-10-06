#!/usr/bin/env python3
"""Delta — base de référence (phase 4) : catalogue extrait de la documentation, lots et commentaires.

Usage :
  catalogue.py maj --perimetre {claude,openai} [--dry-run]     ré-extrait depuis raw/kb/ (sans réseau, sans modèle)
  catalogue.py inventaire [--perimetre P]                      comptes par produit, catégorie et gabarit
  catalogue.py lots --perimetre P                              découpage en lots (catégorie ou demi-catégorie, D46)
  catalogue.py a-commenter --perimetre P --lot LOT [--tout]    entrées du lot à commenter (JSON sur la sortie)
  catalogue.py a-commenter --perimetre P --lot perimees        plafond effectif indiqué par lots (D64-bis/D78) :
                                                               a) section citée modifiée ou dépréciée ; adoption déclarée
                                                               d'un `ignorer` (D67) ; rejugement demandé (D78) ; `utiliser` et `tester` d'abord,
                                                               puis `ignorer` ; champ `motif`
  catalogue.py reevaluations --perimetre P [--depuis J]        réévaluations du journal et taux de verdicts changés
  catalogue.py rejugements [--perimetre P] [--json]            D78 : suivi du rattrapage, lecture seule, sans réseau ;
                                                               par demande et par périmètre : ids listés, dus, recommentés,
                                                               inconnus, active ; plafond effectif ; passages restants (estimation,
                                                               ceil(dues du lot perimees / plafond), sections D64-bis comprises)
  catalogue.py adoptions --perimetre P [--dry-run]            D67 : statut_usage `utilise` pour les id de la section
                                                               « Adoptions » de PROGRESSION.md, consigné dans historique
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
    p.add_argument("commande", choices=["maj", "inventaire", "lots", "a-commenter", "appliquer", "reevaluations", "adoptions", "rejugements"])
    p.add_argument("--depuis", help="avec reevaluations : AAAA-MM-JJ (défaut : aujourd'hui)")
    p.add_argument("--perimetre", choices=["claude", "openai"])
    p.add_argument("--lot")
    p.add_argument("--tout", action="store_true", help="avec a-commenter : inclure les entrées déjà commentées")
    p.add_argument("--fichier", type=Path)
    p.add_argument("--json", action="store_true", help="avec rejugements : sortie structurée")
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
    if a.commande == "rejugements":
        try:
            suivi = cat.suivi_rejugements(a.racine, perimetres, empreintes_sections(a.racine), deprecies_contexte(a.racine))
        except ValueError as err:
            print(f"! {err}", file=sys.stderr)
            return 1
        if a.json:
            json.dump(suivi, sys.stdout, ensure_ascii=False, indent=1)
            print()
        elif not any(v["demandes"] for v in suivi.values()):
            print("aucune demande")
        else:
            for per, v in suivi.items():
                for d in v["demandes"]:
                    print(f"{per} | {d['date']} | {'active' if d['active'] else 'éteinte'} | listés {len(d['ids_listes'])}, "
                          f"dus {len(d['ids_dus'])}, recommentés {len(d['ids_recommentes'])}, inconnus {len(d['ids_inconnus'])} | "
                          f"plafond demande {d['plafond']} | {d['motif']}")
                    if d["ids_inconnus"]:
                        print(f"   inconnus : {', '.join(d['ids_inconnus'])}")
                print(f"{per} | plafond effectif {v['plafond_effectif']} ; {v['dus_total_perimees']} dues (lot perimees) ; "
                      f"passages restants ≈ {v['passages_restants_estimes']} (estimation)")
        return 0
    if not a.perimetre:
        p.error("--perimetre est obligatoire pour cette commande")
    entrees = cat.charger(a.racine, a.perimetre)
    contexte = empreinte_contexte(a.racine)
    try:
        rejugements = cat.charger_rejugements(a.racine) if a.commande in ("lots", "a-commenter", "appliquer") else {}
    except ValueError as err:
        print(f"! {err}", file=sys.stderr)
        return 1
    if a.commande == "lots":
        dus = sum(cat.motif_rejugement(e, rejugements) is not None for e in entrees.values())
        print(f"{'rejugements':<22} {'(D78)':<8} {dus:>4} fiches dues")
        if cat.PERIMEES_SUSPENDU:
            print(f"{'perimees':<22} suspendu")
        else:
            tout = cat.perimees_detail(entrees, empreintes_sections(a.racine), deprecies_contexte(a.racine), maximum=None,
                                      rejugements=rejugements)
            if tout:
                n = {c: sum(1 for x in tout if x["categorie"] == c) for c in ("a", "adoption", "rejugement")}
                plafond = cat.plafond_perimees(entrees, rejugements)
                source = ", rattrapage D78" if plafond > cat.PERIMEES_MAX else ""
                print(f"{'perimees':<22} {'(D64bis/D78)':<8} {min(len(tout), plafond):>4} entrées ce lancement sur {len(tout)} dues "
                      f"(a section {n['a']}, adoption {n['adoption']}, rejugement {n['rejugement']}) ; plafond {plafond}{source}")
        for l in cat.lots(entrees, a.perimetre):
            print(f"{l['lot']:<22} {l['gabarit']:<8} {l['entrees']:>4} entrées, {l['a_commenter']:>4} à commenter")
        return 0
    if a.commande == "a-commenter":
        motifs = {}
        if a.lot == "perimees" and cat.PERIMEES_SUSPENDU:
            print("lot perimees suspendu (catalogue.PERIMEES_SUSPENDU)", file=sys.stderr)
            return 3
        if a.lot == "perimees":
            det = cat.perimees_detail(entrees, empreintes_sections(a.racine), deprecies_contexte(a.racine),
                                     rejugements=rejugements)
            lot = {"ids": [x["id"] for x in det]}
            motifs = {x["id"]: x["motif"] for x in det}
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
    if a.commande == "adoptions":
        from deltalib.kb.modeles import PRODUITS_PAR_PERIMETRE
        code = 0
        for per in perimetres:
            entrees = cat.charger(a.racine, per)
            # un id appartient à la base dont le produit le préfixe (claude-code-…, codex-…)
            miens = [k for k in cat.adoptions(a.racine)
                     if any(k.startswith(f"{pr}-") for pr in PRODUITS_PAR_PERIMETRE[per])]
            inconnus = [k for k in miens if k not in entrees]
            changees = cat.appliquer_adoptions(entrees, [k for k in miens if k in entrees])
            if changees and not a.dry_run:
                cat.ecrire(a.racine, per, entrees)
            print(f"{per} : {len(changees)} entrée(s) passée(s) en `utilise`" + (f" : {', '.join(changees)}" if changees else ""))
            if inconnus:
                print(f"! id d'adoption absents de la base {per} : {', '.join(inconnus)}", file=sys.stderr)
                code = 1
        return code
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

        def motif_de(e):
            c = cat.classer(e, courantes, dep, rejugements)
            return c[1] if c else None
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
