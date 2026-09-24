#!/usr/bin/env python3
"""Delta — sections de CONTEXTE.md et leurs empreintes (D64).

Usage :
  contexte.py                      liste les sections : clé, sha1 (12 premiers), titre
  contexte.py --json               {clé: {titre, niveau, parent, sha1}}
  contexte.py --sections 2.2,3     {clé: sha1} des sections citées, à recopier dans `contexte_sections`
                                   (erreur si une clé est inconnue)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.contexte import resoudre, sections  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="contexte.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    p.add_argument("--sections", help="clés séparées par des virgules ; vide pour aucune")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.sections is not None:
        cles = [c.strip() for c in a.sections.split(",") if c.strip()]
        try:
            print(json.dumps(resoudre(a.racine, cles), ensure_ascii=False))
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    s = sections((a.racine / "CONTEXTE.md").read_text(encoding="utf-8"))
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return 0
    for k, v in s.items():
        print(f"{k:<45} {v['sha1'][:12]}  {'  ' if v['niveau'] == 3 else ''}{v['titre'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
