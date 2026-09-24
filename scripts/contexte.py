#!/usr/bin/env python3
"""Delta — sections de CONTEXTE.md par ctx-id et leurs empreintes (D64-bis).

Usage :
  contexte.py                        liste les sections : ctx-id, sha1 (12 premiers), titre ; puis les ctx-id dépréciés
  contexte.py --json                 {sections: {ctx-id: {titre, niveau, parent, sha1}}, deprecies: [...]}
  contexte.py --sections a,b         modèle {ctx-id: {"sha1": …, "pourquoi": ""}} pour un élément quotidien ; remplir
                                     chaque `pourquoi` (une ligne, 160 caractères au plus)
Un titre sans ctx-id ou un ctx-id en double rend CONTEXTE.md invalide (code 2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.contexte import SHA1_VIDE, ContexteInvalide, analyser  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="contexte.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    p.add_argument("--sections", help="ctx-id séparés par des virgules")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        s, dep = analyser((a.racine / "CONTEXTE.md").read_text(encoding="utf-8"))
    except ContexteInvalide as e:
        print(f"CONTEXTE.md invalide : {e}", file=sys.stderr)
        return 2
    if a.sections is not None:
        cles = [c.strip() for c in a.sections.split(",") if c.strip()]
        inconnues = [c for c in cles if c not in s]
        if inconnues:
            print(f"ctx-id inconnus ou dépréciés : {inconnues} (connus : {', '.join(s)})", file=sys.stderr)
            return 1
        vides = [c for c in cles if s[c]["sha1"] == SHA1_VIDE]
        if vides:
            print(f"sections au corps vide, cite une sous-section : {vides}", file=sys.stderr)
            return 1
        print(json.dumps({c: {"sha1": s[c]["sha1"], "pourquoi": ""} for c in cles}, ensure_ascii=False))
        return 0
    if a.json:
        print(json.dumps({"sections": s, "deprecies": sorted(dep)}, ensure_ascii=False, indent=1))
        return 0
    for k, v in s.items():
        sha = "(corps vide)" if v["sha1"] == SHA1_VIDE else v["sha1"][:12]
        print(f"{k:<40} {sha:<12}  {'  ' * (v['niveau'] - 1)}{v['titre'][:70]}")
    for k in sorted(dep):
        print(f"{k:<40} (déprécié)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
