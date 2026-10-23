#!/usr/bin/env python3
"""Delta — capteur de la liste X officielle (relevé par l'API X et publication des seuls identifiants).

  capteur_x.py                relève la liste et écrit raw/x-liste.json (ignoré par git) + une ligne de comptes dans raw/x-cout.jsonl ;
                              écrit aussi docs/data/actu/x-ids.json (maj + ids, aucun texte) si le relevé réussit ;
                              code 0 même en échec du relevé (le statut est dans le brut : l'analyseur `x_liste` le remonte dans
                              sources_en_echec)
  capteur_x.py --purger       fin de passage : supprime le brut et vide le texte des posts dans raw/ (D72 compris)

Jeton : trousseau (`secret-tool lookup service x compte delta`), jamais sur disque ni affiché.
Avec --ids-en-attente, prépare raw/x-ids.json : l’orchestrateur publie par commit dédié avant les étapes.
Lancé par l'orchestrateur avant la première étape et après la dernière (clé `capteur_x` de scripts/orchestrateur.toml).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib import capteur_x  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="capteur_x.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    p.add_argument("--purger", action="store_true", help="supprime le brut du capteur et le texte des posts dans raw/")
    p.add_argument("--ids-en-attente", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.purger:
        for t in capteur_x.purger(a.racine):
            print(f"purgé : {t}")
        return 0
    b = capteur_x.lancer(a.racine, fichier_ids=capteur_x.FICHIER_IDS_ATTENTE if a.ids_en_attente else capteur_x.FICHIER_IDS)
    l = b["lectures"]
    print(f"capteur X : {b['statut']} — {len(b['posts'])} posts"
          + (f" — {b['message']}" if b["message"] else "") + (f" — {b['partiel']}" if b.get("partiel") else "")
          + (f" — {l['pages']} page(s), {l['posts']} posts + {l['utilisateurs']} utilisateurs lus, ≈ {l['cout_estime_usd']} $" if l else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
