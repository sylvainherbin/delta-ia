#!/usr/bin/env python3
"""Copies publiques des adresses de Delta-IA (deux couches, lot L3).

La seule source est `scripts/deltalib/couches/bootstrap.json`. Le site (GitHub Pages, `docs/`) et le MCP public
(Vercel, `mcp/`) sont déployés séparément et ne lisent pas `scripts/` : ce script leur écrit une copie des seules
adresses et de la langue commune. `--verifier` rend 1 si une copie diffère de la source (test et CI).

    .venv/bin/python scripts/urls.py            # écrit les copies
    .venv/bin/python scripts/urls.py --verifier # contrôle sans écrire
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

from deltalib.couches import config as mod_config  # noqa: E402

CLES = ("site_public_url", "site_anciennes_urls", "reference_base_url", "donnees_compat_url", "mcp_public_url",
        "langue_commune_defaut", "fraicheur")
SITE = RACINE / "docs" / "assets" / "config.js"
MCP = RACINE / "mcp" / "lib" / "config.js"
ENTETE_SITE = "/* Généré par scripts/urls.py depuis scripts/deltalib/couches/bootstrap.json : ne pas modifier à la main. */\n"


def publiques(conf: dict | None = None) -> dict:
    conf = conf or mod_config.charger()
    return {cle: conf[cle] for cle in CLES}


def copies(conf: dict | None = None) -> dict[Path, str]:
    donnees = json.dumps(publiques(conf), ensure_ascii=False, indent=1)
    return {SITE: f"{ENTETE_SITE}window.DELTA_CONFIG = Object.freeze({donnees});\n",
            MCP: f"{ENTETE_SITE.replace('/* ', '// ').replace(' */', '')}export default Object.freeze({donnees});\n"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verifier", action="store_true", help="contrôler les copies sans écrire")
    a = p.parse_args(argv)
    ecarts = []
    nom = lambda c: str(c.relative_to(RACINE)) if c.is_relative_to(RACINE) else str(c)  # noqa: E731
    for chemin, contenu in copies().items():
        actuel = chemin.read_text(encoding="utf-8") if chemin.is_file() else None
        if actuel == contenu:
            continue
        if a.verifier:
            ecarts.append(nom(chemin))
        else:
            chemin.write_text(contenu, encoding="utf-8")
            print(f"écrit : {nom(chemin)}")
    if ecarts:
        print("copies d'adresses périmées (lancer scripts/urls.py) : " + ", ".join(ecarts), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
