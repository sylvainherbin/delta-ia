"""Deux couches, lot L3 : adresses publiques centralisées dans le bootstrap neutre et ses copies générées."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

import urls  # noqa: E402
from deltalib.couches import config as mod_config  # noqa: E402

BOOTSTRAP = json.loads(mod_config.BOOTSTRAP.read_text(encoding="utf-8"))
HOTES = {re.sub(r"^https://([^/]+).*$", r"\1", u) for u in
         (BOOTSTRAP["site_public_url"], BOOTSTRAP["mcp_public_url"], *BOOTSTRAP["site_anciennes_urls"])}


def test_copies_du_site_et_du_mcp_a_jour():
    r = subprocess.run([sys.executable, str(RACINE / "scripts" / "urls.py"), "--verifier"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for chemin, contenu in urls.copies().items():
        assert chemin.read_text(encoding="utf-8") == contenu


def test_copie_perimee_detectee(tmp_path, monkeypatch):
    for nom in ("SITE", "MCP"):
        f = tmp_path / f"{nom}.js"
        f.write_text("window.DELTA_CONFIG = {};\n", encoding="utf-8")
        monkeypatch.setattr(urls, nom, f)
    assert urls.main(["--verifier"]) == 1
    assert urls.main([]) == 0 and urls.main(["--verifier"]) == 0


def test_copies_ne_portent_que_les_adresses_et_la_langue():
    js = (RACINE / "docs" / "assets" / "config.js").read_text(encoding="utf-8")
    donnees = json.loads(js[js.index("(") + 1: js.rindex(")")])
    assert set(donnees) == set(urls.CLES)
    assert "mode" not in donnees and "production" not in donnees


def test_origines_du_site_et_relais():
    import relais_reference as rr
    assert mod_config.origines_site() == ("https://ai.orqyra.io", "https://sylvainherbin.github.io")
    assert rr.SITES == mod_config.origines_site()


@pytest.mark.parametrize("valeur", ["https://x", ["http://ancienne.exemple.test/"], [3]])
def test_anciennes_adresses_validees(valeur, tmp_path):
    from deltalib.couches.racines import Racines
    racines = Racines(*(tmp_path / r for r in ("configuration", "etat", "cache", "runtime")), "instance")
    racines.config.parent.mkdir(parents=True, exist_ok=True)
    racines.config.write_text(json.dumps({"site_anciennes_urls": valeur}), encoding="utf-8")
    with pytest.raises(mod_config.ConfigInvalide):
        mod_config.charger(racines)


def test_aucune_adresse_de_delta_en_dur_dans_le_code():
    """Le code lit la configuration commune : aucun hôte du site, de l'ancienne adresse ni du MCP écrit en dur."""
    fichiers = [p for p in (RACINE / "scripts").rglob("*.py")] + list((RACINE / "mcp" / "api").glob("*.js")) \
        + [p for p in (RACINE / "mcp" / "lib").glob("*.js") if p.name != "config.js"] \
        + [p for p in (RACINE / "docs" / "assets").glob("*.js") if p.name != "config.js"] \
        + list((RACINE / "docs" / "assets").glob("*.mjs"))
    fautes = [f"{p.relative_to(RACINE)} : {h}" for p in fichiers for h in HOTES if h in p.read_text(encoding="utf-8")]
    assert fautes == []
