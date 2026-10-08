"""Phase 5c : icône d'écran d'accueil iOS, manifeste, zone sûre de l'encoche."""

import json
import struct
from pathlib import Path

import fetch

DOCS = Path(fetch.RACINE) / "docs"


def dimensions_png(p: Path):
    b = p.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    largeur, hauteur = struct.unpack(">II", b[16:24])
    return largeur, hauteur, b[25]  # type de couleur : 2 = RVB sans alpha


def test_icones_opaques_aux_bonnes_tailles():
    assert dimensions_png(DOCS / "assets" / "apple-touch-icon.png") == (180, 180, 2)
    assert dimensions_png(DOCS / "assets" / "icon-512.png") == (512, 512, 2)


def test_index_declare_icone_manifeste_et_zone_sure():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    for attendu in ('<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">', '<link rel="manifest" href="manifest.webmanifest">',
                    '<meta name="apple-mobile-web-app-title" content="Delta">', '<meta name="apple-mobile-web-app-capable" content="yes">',
                    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">', "viewport-fit=cover",
                    '<meta name="theme-color" content="#060a13" media="(prefers-color-scheme: dark)">',
                    '<meta name="theme-color" content="#f4f7fb" media="(prefers-color-scheme: light)">'):
        assert attendu in html, attendu
    assert "env(safe-area-inset-top" in (DOCS / "assets" / "style.css").read_text(encoding="utf-8")


def test_manifeste_relatif():
    m = json.loads((DOCS / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["name"] == "Delta — veille IA" and m["short_name"] == "Delta" and m["display"] == "standalone"
    assert m["start_url"] == "./" and m["scope"] == "./" and m["background_color"] == "#060a13"
    assert {i["sizes"] for i in m["icons"]} == {"180x180", "512x512"}
    for i in m["icons"]:
        assert not i["src"].startswith("/") and (DOCS / i["src"]).exists()


def test_voyant_agent_prend_le_passage_le_plus_ancien():
    """Audit du 25/09, point 4 : Claude Code (claude + actu) prend le maj_le le plus ancien de ses périmètres."""
    from pathlib import Path
    app = (Path(__file__).resolve().parent.parent / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    debut = app.index("function rendreEtatAgents")
    corps = app[debut:app.index("return alertes", debut)]
    assert "t < parAgent[idx.agent]" in corps and "t > parAgent[idx.agent]" not in corps


def test_a_tester_ouvertes_puis_faites_repliees():
    """Audit du 25/09, point 5 : actions ouvertes d'abord avec leur nombre, faites dans une section repliée."""
    from pathlib import Path
    app = (Path(__file__).resolve().parent.parent / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    corps = app[app.index("function pageATester"):app.index("function pageArchives")]
    assert "Actions ouvertes (${ouvertes.length})" in corps and "Actions faites (${faites.length})" in corps
    assert 'el("details", { class: "actions-faites" }' in corps and corps.index("ouvertes.length") < corps.index("faites.length")
    assert "surFait" in app[app.index("function carte"):app.index("function listeCartes")]


def test_date_ajout_extraction():
    """N1 (08/10) : date d'ajout = ligne « ajoutée à l'inventaire », à défaut la plus ancienne date, à défaut None."""
    import sys
    sys.path.insert(0, str(DOCS.parent / "scripts"))
    from deltalib.kb.catalogue import date_ajout
    ajout = {"date": "2026-10-02", "changement": "ajoutée à l'inventaire"}
    assert date_ajout({"historique": [{"date": "2026-10-05", "changement": "commentée"}, ajout]}) == "2026-10-02"
    assert date_ajout({"historique": [ajout, {"date": "2026-10-01", "changement": "ajoutée à l'inventaire"}]}) == "2026-10-01"
    # sans la ligne attendue : la plus ancienne date de l'historique
    assert date_ajout({"historique": [{"date": "2026-10-05", "changement": "commentée"}, {"date": "2026-09-30", "changement": "x"}]}) == "2026-09-30"
    # historique absent, vide, mal formé : None
    for e in ({}, {"historique": None}, {"historique": []}, {"historique": "x"},
              {"historique": [{"date": "hier", "changement": "ajoutée à l'inventaire"}, None, {"changement": "x"}]}):
        assert date_ajout(e) is None
    # toutes les entrées publiées ont une date d'ajout
    for f in (DOCS / "data" / "kb").glob("*/*.json"):
        for e in json.loads(f.read_text(encoding="utf-8"))["entrees"]:
            assert date_ajout(e), (f.name, e["id"])


def test_vue_recente_de_la_reference():
    """N1 : tri « ajoutées récemment », filtre 7/30 jours, lien #reference?recent=7 et encart sur Aujourd'hui."""
    app = (DOCS / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'const LIGNE_AJOUT = "ajoutée à l\'inventaire"' in app
    f = app[app.index("function dateAjout"):app.index("function jourLocalIso")]
    assert "lignes.map((l) => l.date).sort()[0] || null" in f
    corps = app[app.index("function filtrerKb"):app.index("function carteKb")]
    assert 'kbFiltre.tri !== "recent"' in corps and "ajouteeDepuis(e, kbFiltre.depuis, ref)" in corps and "String(a.nom).localeCompare(String(b.nom)" in corps
    assert 'choix("Tri", "tri"' in app and "Ajoutées depuis 7 jours" in app and "Ajoutées depuis 30 jours" in app
    assert 'new URLSearchParams(requete || "").get("recent")' in app and "#reference?recent=7" in app
    assert 'id: "encart-kb"' in app and "Nouveau dans la base (7 jours) : " in app
    # la carte montre syntaxe, exemple et pourquoi
    carte = app[app.index("function carteKb"):app.index("function badgeContexte")]
    assert "e.usage" in carte and "e.exemple" in carte and "recommandation.pourquoi" in carte and "ajoutée le" in carte
