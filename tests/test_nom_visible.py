"""Décision du 26/10/2026 (DECISIONS.md « DELTA-IA DEVIENT « ORQYRA AI » ») : le nom visible du site est ORQYRA AI, en français
comme en anglais. Aucun « Delta » ne reste dans les pages servies sous docs/ (HTML, manifestes, plan du site, dictionnaires
d'interface) ni dans les gabarits de scripts dont le texte atterrit sur le site (versions.json, pages et manifestes).
Les identifiants techniques (dépôt, connecteur `delta-ia`, commandes, clés JSON, variables d'environnement) ne sont pas du texte visible."""

import ast
import re
from pathlib import Path

from textes_site import EN, FR

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"

# Liste blanche : seules occurrences de « Delta » tolérées dans le texte visible.
BLANCHE = re.compile("|".join([
    r"Delta Lab",                       # produit d'ORQYRA distinct du site (essais et qualification), nom propre conservé
    r"Relier Delta-IA",                 # libellé littéral du bouton de la console du Bureau, hors de ce dépôt
    r"http delta-ia",                   # commande `claude mcp add --transport http delta-ia <url>` : nom du connecteur MCP
]))
DELTA = re.compile(r"delta", re.IGNORECASE)


def reste(texte: str) -> list[str]:
    return [m.group(0) for m in DELTA.finditer(BLANCHE.sub("", texte))]


def test_pages_servies_sans_delta_visible():
    pages = [DOCS / "index.html", DOCS / "fr" / "index.html", DOCS / "manifest.webmanifest",
             DOCS / "fr" / "manifest.webmanifest", DOCS / "sitemap.xml", DOCS / "robots.txt"]
    for page in pages:
        assert not reste(page.read_text(encoding="utf-8")), page


def test_dictionnaires_sans_delta_visible():
    for langue, dico in (("en", EN), ("fr", FR)):
        for cle, valeur in dico.items():
            assert not reste(valeur), (langue, cle, valeur)


def test_nom_dans_titres_et_metadonnees():
    for chemin, titre in (("index.html", "ORQYRA AI — AI watch"), ("fr/index.html", "ORQYRA AI — veille IA")):
        page = (DOCS / chemin).read_text(encoding="utf-8")
        assert f"<title>{titre}</title>" in page
        assert f'<meta property="og:title" content="{titre}">' in page
        assert '<meta property="og:site_name" content="ORQYRA AI">' in page
        assert '<meta name="apple-mobile-web-app-title" content="ORQYRA AI">' in page
        assert '<span class="marque-nom">ORQYRA AI</span>' in page
    for chemin, nom in (("manifest.webmanifest", "ORQYRA AI — AI watch"), ("fr/manifest.webmanifest", "ORQYRA AI — veille IA")):
        manifeste = (DOCS / chemin).read_text(encoding="utf-8")
        assert f'"name": "{nom}"' in manifeste and '"short_name": "ORQYRA AI"' in manifeste


def chaines_hors_docstrings(chemin: Path) -> list[tuple[int, str]]:
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and noeud.body:
            premier = noeud.body[0]
            if isinstance(premier, ast.Expr) and isinstance(premier.value, ast.Constant) and isinstance(premier.value.value, str):
                docstrings.add(id(premier.value))
    return [(n.lineno, n.value) for n in ast.walk(arbre)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_gabarits_de_scripts_sans_delta_visible():
    # Gabarits dont le texte est publié : pages et manifestes (site_langues.py), notes de docs/data/versions.json (versions.py).
    for script in ("site_langues.py", "versions.py"):
        for ligne, chaine in chaines_hors_docstrings(RACINE / "scripts" / script):
            if script == "site_langues.py" and ("window.DELTA_TEXTES" in chaine or "deltalib" in chaine):
                continue   # identifiants techniques (variable JS, module)
            assert not reste(chaine), (script, ligne, chaine[:80])
