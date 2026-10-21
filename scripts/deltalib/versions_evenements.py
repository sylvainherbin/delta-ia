"""Journal local des changements constatés, partagé par les relevés et le catalogue."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def lire_precedent(chemin: Path):
    """Un relevé absent ou illisible ne permet pas de déduire des changements."""
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        print(f"Avertissement : précédent illisible {chemin} : {err}", file=sys.stderr)
        return None


def ajouter_evenements(racine: Path, changements: list[dict]) -> None:
    """Crée le journal si besoin ; ajoute chaque ligne complète en un seul write.

    L'ouverture en ajout ne tronque jamais un journal existant, même sans changement.
    Une panne du journal reste sans effet sur le relevé principal.
    """
    chemin = racine / "rapports" / "versions-evenements.jsonl"
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as journal:
            for changement in changements:
                evenement = {"ts": datetime.now(timezone.utc).isoformat(),
                             "type": "version_changee", **changement}
                empreinte = json.dumps(evenement, ensure_ascii=False, sort_keys=True)
                ident = hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:24]
                journal.write(json.dumps({"id": ident, **evenement}, ensure_ascii=False) + "\n")
    except OSError as err:
        print(f"Avertissement : écriture du journal {chemin} impossible : {err}", file=sys.stderr)
