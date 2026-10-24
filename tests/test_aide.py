"""D112 : onglet « Aide » du site. Depuis L3, ses textes vivent dans les dictionnaires (docs/assets/textes.js, clés
aide.<id>.titre|sert|geste|limite et aide.mcp.liste.<n>) ; app.js ne garde que la liste des sections (AIDE)."""

import re
from pathlib import Path

from textes_site import EN, FR, TEXTES

RACINE = Path(__file__).resolve().parent.parent
APP = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
INDEX = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
INDEX_FR = (RACINE / "docs" / "fr" / "index.html").read_text(encoding="utf-8")
MCP = (RACINE / "mcp" / "api" / "mcp.js").read_text(encoding="utf-8")


def bloc_aide() -> str:
    debut = APP.index("const AIDE = [")
    return APP[debut:APP.index("function pageAide", debut)]


def sections() -> list[dict]:
    """Une entrée par section de AIDE : son id et ses champs présents dans le dictionnaire français."""
    out = []
    for ident, liste in re.findall(r'\{ id: "([a-z-]+)"(?:, liste: (\d+))? \}', bloc_aide()):
        champs = [c for c in ("sert", "geste", "limite") if f"aide.{ident}.{c}" in FR]
        out.append({"id": ident, "champs": champs + (["liste"] if liste else []), "liste": int(liste or 0)})
    return out


def texte_section(ident: str, langue: str = "fr") -> str:
    d = TEXTES[langue]
    return " ".join(v for k, v in d.items() if k.startswith(f"aide.{ident}."))


def test_route_onglet_et_lien_de_pied():
    for index, d in ((INDEX, EN), (INDEX_FR, FR)):
        assert f'<a href="#aide" data-page="aide">{d["onglet.aide"]}</a>' in index
        assert index.index('data-page="archives"') < index.index('data-page="aide"')
        assert index.count('href="#aide"') == 2  # onglet, et lien de pied de page si la barre défile sur 360 px
    assert FR["onglet.aide"] == "Aide" and EN["onglet.aide"] == "Help"
    assert '"archives", "aide"].includes(page)' in APP and 'case "aide"' not in APP and 'etat.page === "aide"' in APP


def test_une_section_par_onglet():
    ids = {s["id"] for s in sections()}
    onglets = set(re.findall(r'data-page="([^"]+)"', INDEX)) - {"aide"}
    assert onglets <= ids, onglets - ids
    for fonction in ("etat", "quotas", "outils", "nouveau", "liens", "envoi", "mcp", "iphone", "couches", "langue"):
        assert fonction in ids, fonction


def test_trois_lignes_au_plus_par_section():
    for s in sections():
        assert [c for c in s["champs"] if c != "liste"] == ["sert", "geste", "limite"], s["id"]
        for langue, d in TEXTES.items():
            assert f"aide.{s['id']}.titre" in d, (langue, s["id"])
    assert [s["id"] for s in sections() if "liste" in s["champs"]] == ["mcp"]
    # pas de clé d'aide orpheline : chaque clé aide.<id>.… appartient à une section déclarée
    ids = {s["id"] for s in sections()}
    for cle in FR:
        if cle.startswith("aide.") and cle not in ("aide.sous_titre",) and not cle.startswith("aide.etiquette."):
            assert cle.split(".")[1] in ids, cle


def test_geste_brave_du_bouton():
    assert "brave://settings/content/localhostAccess" not in APP + texte_section("envoi") + texte_section("envoi", "en")
    envoi = texte_section("envoi")
    assert "Facultatif — Brave : Paramètres → rechercher localhost (Brave le propose selon la version)" in envoi
    assert "Bureau : relais local d'abord (sonde de 3 s), puis console" in envoi
    assert "iPhone/iPad : console reliée, sinon copie" in envoi
    assert "Relier Delta-IA » une fois par navigateur, sur chaque appareil" in envoi
    assert "envoi à valider" in envoi and "ouverture de console" in envoi
    assert "Optional — Brave: Settings → search localhost" in texte_section("envoi", "en")


def test_connecteur_mcp_decrit_ses_six_outils():
    outils = re.findall(r'^  (\w+): \{ f: ', MCP, re.M)
    assert len(outils) == 6
    for langue in ("fr", "en"):
        section = texte_section("mcp", langue)
        for o in outils:
            assert f"`{o}`" in section, (langue, o)
    assert "Qu'y a-t-il de nouveau" in texte_section("mcp")
    # L3 : l'adresse du serveur vient de la configuration (copie du bootstrap), interpolée à l'affichage, jamais écrite en dur
    for d in (FR, EN):
        assert "`{mcp_url}`" in d["aide.mcp.geste"] and "claude mcp add --transport http delta-ia {mcp_url}" in d["aide.mcp.geste"]
        assert "vercel.app" not in d["aide.mcp.geste"]
    assert "mcp_url: CONFIG.mcp_public_url" in APP and "t(`aide.${a.id}.${champ}`, ADRESSES_AIDE)" in APP


def test_aucune_donnee_personnelle_ni_adresse_de_console():
    for langue in ("fr", "en"):
        corps = " ".join(v for k, v in TEXTES[langue].items() if k.startswith("aide."))
        for interdit in (".ts.net", "100.64.", "100.100.", "127.0.0.1", "localhost:", "@gmail", "token", "jeton="):
            assert interdit not in corps, (langue, interdit)
        # seule adresse de console admise : le gabarit du geste d'enregistrement, sur l'adresse du site de la configuration
        assert re.findall(r"#console=([^`]*)`", corps) == ["<adresse>"]
        assert "`{site_url}#console=<adresse>`" in corps


def test_garde_fous_app_js():
    corps = bloc_aide() + APP[APP.index("function pageAide"):APP.index("/* ---------- routage par ancre")]
    assert "innerHTML" not in corps and "insertAdjacentHTML" not in corps and ".innerHTML" not in APP
    # les liens internes de l'aide ne mènent qu'à une ancre du site (motif `(#…)`)
    assert 'm[2] ? el("a", { href: m[2] }' in corps and r"(#[^)\s]+)" in corps
    # le texte de l'aide ne dépend d'aucune donnée : la page s'affiche même sans index
    assert "etat." not in APP[APP.index("function pageAide"):APP.index("/* ---------- routage par ancre")]
