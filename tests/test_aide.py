"""D112 : onglet « Aide » du site (texte statique de docs/assets/app.js)."""

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
APP = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
INDEX = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
MCP = (RACINE / "mcp" / "api" / "mcp.js").read_text(encoding="utf-8")


def bloc_aide() -> str:
    debut = APP.index("const AIDE = [")
    return APP[debut:APP.index("function pageAide", debut)]


def sections() -> list[dict]:
    """Une entrée par section de AIDE : son id et ses champs (une ligne `      champ:` par champ)."""
    morceaux = bloc_aide().split('\n    { id: "')[1:]
    return [{"id": m.split('"', 1)[0], "champs": re.findall(r"^      (sert|geste|limite|liste):", m, re.M)} for m in morceaux]


def test_route_onglet_et_lien_de_pied():
    assert '<a href="#aide" data-page="aide">Aide</a>' in INDEX
    assert INDEX.index('data-page="archives"') < INDEX.index('data-page="aide"')
    assert INDEX.count('href="#aide"') == 2  # onglet, et lien de pied de page si la barre défile sur 360 px
    assert '"archives", "aide"].includes(page)' in APP and 'case "aide"' not in APP and 'etat.page === "aide"' in APP


def test_une_section_par_onglet():
    ids = {s["id"] for s in sections()}
    onglets = set(re.findall(r'data-page="([^"]+)"', INDEX)) - {"aide"}
    assert onglets <= ids, onglets - ids
    for fonction in ("etat", "quotas", "outils", "nouveau", "liens", "envoi", "mcp", "iphone"):
        assert fonction in ids, fonction


def test_trois_lignes_au_plus_par_section():
    for s in sections():
        assert [c for c in s["champs"] if c != "liste"] == ["sert", "geste", "limite"], s["id"]
    assert [s["id"] for s in sections() if "liste" in s["champs"]] == ["mcp"]


def test_geste_brave_du_bouton():
    corps = bloc_aide()
    assert "brave://settings/content/localhostAccess" in corps and "https://sylvainherbin.github.io" in corps
    assert "iPhone" in corps[corps.index('id: "envoi"'):corps.index('id: "a-tester"')]


def test_connecteur_mcp_decrit_ses_six_outils():
    outils = re.findall(r'^  (\w+): \{ f: ', MCP, re.M)
    assert len(outils) == 6
    section = bloc_aide()
    section = section[section.index('id: "mcp"'):section.index('id: "iphone"')]
    for o in outils:
        assert f"`{o}` :" in section, o
    assert "Qu'y a-t-il de nouveau" in section and "https://delta-mcp-ruddy.vercel.app/mcp" in section


def test_aucune_donnee_personnelle_ni_adresse_de_console():
    corps = bloc_aide()
    for interdit in (".ts.net", "100.64.", "100.100.", "127.0.0.1", "localhost:", "@gmail", "token", "jeton="):
        assert interdit not in corps, interdit
    # seule adresse de console admise : le gabarit du geste d'enregistrement
    assert re.findall(r"#console=([^`]*)`", corps) == ["<adresse>"]


def test_garde_fous_app_js():
    corps = bloc_aide() + APP[APP.index("function pageAide"):APP.index("/* ---------- routage par ancre")]
    assert "innerHTML" not in corps and "insertAdjacentHTML" not in corps and ".innerHTML" not in APP
    # les liens internes de l'aide ne mènent qu'à une ancre du site (motif `(#…)`)
    assert 'm[2] ? el("a", { href: m[2] }' in corps and r"(#[^)\s]+)" in corps
    # le texte de l'aide ne dépend d'aucune donnée : la page s'affiche même sans index
    assert "etat." not in APP[APP.index("function pageAide"):APP.index("/* ---------- routage par ancre")]
