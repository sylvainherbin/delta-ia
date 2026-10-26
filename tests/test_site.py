"""Phase 5c : icône d'écran d'accueil iOS, manifeste, zone sûre de l'encoche."""

import json
import struct
from pathlib import Path

import fetch
from textes_site import EN, FR

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
                    '<meta name="apple-mobile-web-app-title" content="ORQYRA AI">', '<meta name="apple-mobile-web-app-capable" content="yes">',
                    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">', "viewport-fit=cover",
                    '<meta name="theme-color" content="#060a13" media="(prefers-color-scheme: dark)">',
                    '<meta name="theme-color" content="#f4f7fb" media="(prefers-color-scheme: light)">'):
        assert attendu in html, attendu
    assert "env(safe-area-inset-top" in (DOCS / "assets" / "style.css").read_text(encoding="utf-8")


def test_manifeste_relatif():
    # L3 : un manifeste par langue (racine anglaise, /fr/ française), icônes partagées par chemin relatif
    for dossier, nom in ((DOCS, EN["manifeste.nom"]), (DOCS / "fr", FR["manifeste.nom"])):
        m = json.loads((dossier / "manifest.webmanifest").read_text(encoding="utf-8"))
        assert m["name"] == nom and m["short_name"] == "ORQYRA AI" and m["display"] == "standalone"
        assert m["start_url"] == "./" and m["scope"] == "./" and m["background_color"] == "#060a13"
        assert {i["sizes"] for i in m["icons"]} == {"180x180", "512x512"}
        for i in m["icons"]:
            assert not i["src"].startswith("/") and (dossier / i["src"]).resolve().exists()
    assert FR["manifeste.nom"] == "ORQYRA AI — veille IA"


def test_voyant_agent_prend_le_passage_le_plus_ancien():
    """Audit du 25/09, point 4 : Claude Code (claude + actu) prend le maj_le le plus ancien de ses périmètres."""
    from pathlib import Path
    app = (Path(__file__).resolve().parent.parent / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    debut = app.index("function rendreEtatAgents")
    corps = app[debut:app.index("return alertes", debut)]
    assert "t0 < parAgent[idx.agent]" in corps and "t0 > parAgent[idx.agent]" not in corps


def test_a_tester_ouvertes_puis_faites_repliees():
    """Audit du 25/09, point 5 : actions ouvertes d'abord avec leur nombre, faites dans une section repliée."""
    from pathlib import Path
    app = (Path(__file__).resolve().parent.parent / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    corps = app[app.index("function pageATester"):app.index("function pageArchives")]
    assert 't("atester.ouvertes", { n: ouvertes.length })' in corps and 't("atester.faites", { n: faites.length })' in corps
    assert FR["atester.ouvertes"] == "Actions ouvertes ({n})" and FR["atester.faites"] == "Actions faites ({n})"
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
    assert 'kbFiltre.tri !== "recent"' in corps and "ajouteeDepuis(e, depuis, ref)" in corps and "String(a.nom).localeCompare(String(b.nom)" in corps
    assert 'const depuis = enCommun() ? "" : kbFiltre.depuis;' in corps   # L3 : dates d'ajout non publiées en commun
    assert 'choix(t("filtre.tri"), "tri"' in app and FR["filtre.depuis_7"] == "Ajoutées depuis 7 jours" and FR["filtre.depuis_30"] == "Ajoutées depuis 30 jours"
    assert 'new URLSearchParams(requete || "").get("recent")' in app and "#reference?recent=7" in app
    assert 'id: "encart-kb"' in app and FR["encart.titre"] == "Nouveau dans la base (7 jours) : " and 't("encart.titre")' in app
    # la carte montre syntaxe, exemple et pourquoi
    carte = app[app.index("function carteKb"):app.index("function badgeContexte")]
    assert "e.usage" in carte and "e.exemple" in carte and "recommandation.pourquoi" in carte and 't("kb.ajoutee_le"' in carte


def test_encart_compte_et_quotas():
    """D93 (D71) : encart « Compte et quotas » en tête de l'onglet Aujourd'hui, lu dans etat.json > comptes."""
    app = (DOCS / "assets" / "app.js").read_text(encoding="utf-8")
    page = app[app.index("function pageAujourdhui"):app.index("function completerEncartKb")]
    assert page.index("blocComptes(Date.now())") < page.index("blocOutils()") < page.index('id: "encart-kb"')
    assert 'lireJson(chemin("etat.json"))' in app and "etat.comptes = e && typeof e.comptes" in app
    assert "Promise.all([chargerDernierJour(), chargerVersions(), chargerComptes()])" in app
    corps = app[app.index("function blocComptes"):app.index("/* ---------- Tes outils")]
    # bloc absent si `comptes` manque ; quatre quotas ; barre, pourcentage, remise à zéro, relevé et âge
    assert "if (enCommun() || !c || typeof c !== \"object\") return null;" in corps   # L3 : jamais lu sur la référence commune
    for cle in ("claude_session_5h", "claude_semaine", "claude_semaine_fable", "chatgpt_semaine"):
        assert cle in app
    assert 'role: "progressbar"' in corps and 't("quota.rz", { rz })' in corps and 't("comptes.releve", { quand: releve' in corps and "age(c.releve_le" in corps
    assert FR["quota.rz"] == "remise à zéro le {rz}" and FR["comptes.releve"] == "Relevé du {quand} ({age})."
    # alerte D71 : seuls les quotas hebdomadaires, au-delà de 80 %, phrase exacte
    assert "const SEUIL_ALERTE_PCT = 80;" in app and "hebdo && q.pct > SEUIL_ALERTE_PCT" in corps
    assert "vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser" in FR["quota.alerte_d71"]
    assert '["claude_session_5h", "quota.claude_session_5h", false]' in app and FR["quota.claude_session_5h"] == "Claude, session 5 h"
    # D120 : le relevé de chaque quota est affiché ; plus de 30 min (ou date inconnue) : « ancien »
    assert "const ANCIEN_MIN = 30;" in app and "maintenant - tRel > ANCIEN_MIN * 60000" in corps and '` · ${t("quota.ancien")}`' in corps
    assert 't("quota.releve_inconnu")' in corps and FR["quota.releve_inconnu"] == "date du relevé inconnue"
    # une valeur inconnue ou périmée n'est jamais présentée comme actuelle
    assert 't("quota.inconnu")' in corps and "valeur périmée" in FR["quota.rz_passee"]
    # jamais d'injection de HTML, heure locale
    assert "innerHTML" not in corps and "getHours()" in app[app.index("function jjmmHhmm"):app.index("function age(")]
    css = (DOCS / "assets" / "style.css").read_text(encoding="utf-8")
    for sel in (".comptes", ".quota.alerte", ".barre span", ".alerte-d71"):
        assert sel in css


def test_site_ne_presente_plus_de_credit_cloud():
    """Le crédit fictif ne doit réapparaître ni dans l'aide ni dans les pages publiques."""
    for fichier in [DOCS / "assets" / "app.js", DOCS / "assets" / "textes.js", *sorted(DOCS.glob("**/*.html"))]:
        texte = fichier.read_text(encoding="utf-8").casefold()
        assert "crédit sessions cloud" not in texte, fichier
        assert not ("crédit" in texte and "échéance" in texte), fichier
