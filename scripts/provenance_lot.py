#!/usr/bin/env python3
"""Delta — provenance des fiches qui recommandent (D127) en masse, mode Batch, sur les crédits API (D128).

Usage :
  provenance_lot.py etat                                       lots, fiches dues par périmètre, autorisation de la suite
  provenance_lot.py preparer --perimetre P [--max N] [--modele M] [--effort E]
                                                               requêtes Batch des fiches dues (raw/provenance-lots/<lot>/) ;
                                                               premier lot : 10 fiches au plus ; suite refusée sans `autoriser`
  provenance_lot.py soumettre                                  soumet le lot en cours par A1 (`soumettre_lot`, usage
                                                               delta-ia-provenance) ; relevé de coût A1 avant soumission
  provenance_lot.py relever                                    résultats par A1 (`relever_lot`) ; code 3 si le lot tourne encore ;
                                                               coût du lot = relevé A1 après moins relevé avant
  provenance_lot.py appliquer [--resultats F] [--dry-run]      pose les provenances valides dans docs/data/kb/<P>/ (historique
                                                               « provenance ajoutée ») ; refusé pendant la chaîne de nuit (D70)
  provenance_lot.py autoriser --par "…"                        suite autorisée après présentation du coût du premier lot
  provenance_lot.py abandonner                                 marque le lot en cours abandonné (lot expiré, erreur A1)

Codes : 0 succès, 1 refus ou erreur, 3 lot encore en traitement, 5 crédits épuisés (code de A1, repli sans coût).
La clé « delta » n'est jamais lue ici : A1 (`delta.operer.credits_api`, dépôt discipline) fait les appels et les compte.
Après `appliquer` : `valider.py --kb`, puis commit `delta-kb(<P>): provenance — <n> entrées` des chemins de la base.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import garde  # noqa: E402
from deltalib.kb import catalogue as cat  # noqa: E402
from deltalib.kb import provenance_lot as pl  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
CODE_EN_COURS, CODE_CREDITS = 3, 5


# ----------------------------------------------------------------------------------------------- pont vers A1
# Contrat supposé de A1 (m-2e53852c7060, fonctions `soumettre_lot` et `relever_lot` de `delta.operer.credits_api`) :
#   soumettre_lot(usage, requetes) -> identifiant du lot (str, ou objet/dict portant `id`) ;
#   relever_lot(identifiant) -> None tant que le lot tourne, sinon les résultats au format Message Batches
#   ({custom_id, result: {type, message}}), comptés par A1 au relevé ;
#   solde nul ou cycle échu : SystemExit(5) ou exception portant `code == 5`.
# Le dépôt discipline n'était pas lisible pendant la mission : à vérifier contre A1 à la fusion (rapport m-21ed065f3dc5).

def module_a1(racine: Path):
    src = Path(os.environ.get("DELTA_DISCIPLINE_SRC") or racine.parent / "discipline" / "src")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return importlib.import_module("delta.operer.credits_api")


def _identifiant(r) -> str:
    if isinstance(r, str):
        return r
    v = r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
    if not isinstance(v, str) or not v:
        raise pl.LotRefuse(f"A1 n'a pas rendu d'identifiant de lot ({type(r).__name__})")
    return v


def cout_usage(usage: str = pl.USAGE_A1) -> float | None:
    """Dépense cumulée de l'usage selon `operer credits releve --json` (`par_usage`) ; None si le relevé est indisponible."""
    try:
        sortie = subprocess.run(["operer", "credits", "releve", "--json"], capture_output=True, text=True, timeout=60, check=True).stdout
        v = (json.loads(sortie).get("par_usage") or {}).get(usage)
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    if v is None:
        return 0.0
    if isinstance(v, dict):
        v = next((v[c] for c in ("cout_usd", "usd", "cout", "montant") if isinstance(v.get(c), (int, float))), None)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _credits_epuises(err: BaseException) -> bool:
    return (isinstance(err, SystemExit) and err.code == CODE_CREDITS) or getattr(err, "code", None) == CODE_CREDITS


# ----------------------------------------------------------------------------------------------- commandes

def etat(racine: Path) -> int:
    for per in ("claude", "openai"):
        dues = cat.provenance_detail(cat.charger(racine, per), maximum=None)
        print(f"{per:<8} {len(dues):>4} fiches utiliser/tester sans provenance")
    a = pl.autorisation(racine)
    print("suite : " + (f"autorisée le {a['date']} par {a['par']}" if a else "non autorisée (premier lot limité à "
                         f"{pl.PREMIER_LOT_MAX} fiches, puis coût présenté à Sylvain)"))
    for m in pl.lots(racine):
        print(f"  {m['statut']:<10} " + (pl.ligne_bilan(m) if m.get("bilan") else f"{m['lot']} : {len(m['fiches'])} fiches, {m['modele']}"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="provenance_lot.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("commande", choices=["etat", "preparer", "soumettre", "relever", "appliquer", "autoriser", "abandonner"])
    p.add_argument("--perimetre", choices=["claude", "openai"])
    p.add_argument("--max", type=int)
    p.add_argument("--modele", default=pl.MODELE_DEFAUT)
    p.add_argument("--effort", default=pl.EFFORT_DEFAUT, choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--resultats", type=Path, help="résultats Batch (JSONL) relevés autrement qu'avec `relever`")
    p.add_argument("--par")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    r = a.racine
    try:
        if a.commande == "etat":
            return etat(r)
        if a.commande == "autoriser":
            x = pl.autoriser(r, a.par or "")
            print(f"suite autorisée le {x['date']} par {x['par']} (premier lot {x['premier_lot']})")
            return 0
        if a.commande == "preparer":
            if not a.perimetre:
                p.error("--perimetre requis")
            m = pl.preparer(r, a.perimetre, a.max, a.modele, a.effort)
            print(f"lot {m['lot']} préparé : {len(m['fiches'])} fiches, {len(m['ecartees'])} écartées, modèle {m['modele']} "
                  f"(effort {m['effort']}){' — premier lot' if m['premier'] else ''}")
            for k, motif in list(m["ecartees"].items())[:10]:
                print(f"  écartée {k} : {motif}")
            return 0
        m = pl.lot_courant(r)
        if a.commande == "abandonner":
            m["statut"] = "abandonne"
            pl.ecrire_manifeste(r, m)
            print(f"lot {m['lot']} abandonné ; ses fiches restent dues")
            return 0
        if a.commande == "soumettre":
            if m["statut"] != "prepare":
                raise pl.LotRefuse(f"lot {m['lot']} déjà {m['statut']}")
            avant = cout_usage()
            try:
                ident = _identifiant(module_a1(r).soumettre_lot(pl.USAGE_A1, pl.charger_requetes(r, m)))
            except (SystemExit, Exception) as err:  # noqa: BLE001 : A1 décide, on rapporte
                if _credits_epuises(err):
                    print("crédits API épuisés ou cycle échu (A1, code 5) : rien n'est soumis", file=sys.stderr)
                    return CODE_CREDITS
                if isinstance(err, pl.LotRefuse):
                    raise
                print(f"A1 : soumission impossible ({type(err).__name__}: {err})", file=sys.stderr)
                return 1
            m.update({"statut": "soumis", "id_lot_api": ident, "soumis_le": date.today().isoformat(), "cout_avant": avant})
            pl.ecrire_manifeste(r, m)
            print(f"lot {m['lot']} soumis par A1 : {ident} ({len(m['fiches'])} requêtes)")
            return 0
        if a.commande == "relever":
            if m["statut"] != "soumis":
                raise pl.LotRefuse(f"lot {m['lot']} : {m['statut']}, pas soumis")
            try:
                res = module_a1(r).relever_lot(m["id_lot_api"])
            except (SystemExit, Exception) as err:  # noqa: BLE001
                if _credits_epuises(err):
                    print("crédits API épuisés (A1, code 5)", file=sys.stderr)
                    return CODE_CREDITS
                print(f"A1 : relevé impossible ({type(err).__name__}: {err})", file=sys.stderr)
                return 1
            if res is None:
                print(f"lot {m['lot']} encore en traitement")
                return CODE_EN_COURS
            pl.ecrire_resultats(r, m, list(res))
            apres = cout_usage()
            avant = m.get("cout_avant")
            m["cout"] = ({"usd": round(apres - avant, 8), "source": "relevé par usage avant soumission et après relevé"}
                         if isinstance(apres, float) and isinstance(avant, float) else None)
            m["statut"] = "releve"
            pl.ecrire_manifeste(r, m)
            print(f"lot {m['lot']} relevé ; coût " + (f"{m['cout']['usd']:.4f} $" if m["cout"] else "non mesuré (relevé A1 indisponible)"))
            return 0
        if a.commande == "appliquer":
            tenu, pid = garde.verrou_chaine(r)
            if tenu:
                raise pl.LotRefuse(f"chaîne de nuit en cours (.git/delta-passage.lock, pid {pid}) : appliquer après 08 h 00")
            f = a.resultats or (pl.dossier(r) / m["lot"] / "resultats.jsonl")
            if not f.exists():
                raise pl.LotRefuse(f"résultats absents : {f} (`relever` d'abord)")
            res = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            if a.resultats:
                pl.ecrire_resultats(r, m, res)
            b = pl.appliquer(r, m, res, ecrire=not a.dry_run)
            m["bilan"] = b
            print(pl.ligne_bilan(m))
            for titre, d in (("à revoir (recommandation non fondée)", b["a_revoir"]), ("rejetée", b["rejets"]), ("sautée", b["sautees"])):
                for k, motif in d.items():
                    print(f"  {titre} {k} : {motif}")
            if not a.dry_run and b["posees"]:
                print(f"ensuite : .venv/bin/python scripts/valider.py --perimetre {m['perimetre']} --kb, puis "
                      f"git add docs/data/kb/{m['perimetre']} docs/data/kb/recent.json docs/data/kb/a-tester.json docs/data/kb/noms.json "
                      f"&& git commit -m \"delta-kb({m['perimetre']}): provenance — {len(b['posees'])} entrées\"")
            if m.get("premier") and not a.dry_run:
                print("premier lot : coût à présenter à Sylvain par Delta-pilote avant la suite (`autoriser --par …`)")
            return 0
    except pl.LotRefuse as err:
        print(f"refusé : {err}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
