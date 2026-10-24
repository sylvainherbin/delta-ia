#!/usr/bin/env python3
"""Pages du site par langue (deux couches, lot L3 ; décision du 22/10 : anglais à la racine, français sous /fr/).

Un seul gabarit, les textes statiques tirés des dictionnaires (`docs/assets/textes.js`) et l'adresse publique du site tirée
du bootstrap (`scripts/deltalib/couches/bootstrap.json`, via `deltalib.couches.config`). Écrit :
- `docs/index.html` (anglais, x-default) et `docs/fr/index.html` (français) : hreflang, canonical, og:locale ;
- `docs/manifest.webmanifest` et `docs/fr/manifest.webmanifest` (nom de l'application dans la langue de la page) ;
- `docs/sitemap.xml` (alternates xhtml:link) et `docs/robots.txt` (adresse du sitemap).
Aucune redirection selon la langue du navigateur : chaque page est servie telle quelle.

    .venv/bin/python scripts/site_langues.py            # écrit les fichiers
    .venv/bin/python scripts/site_langues.py --verifier # rend 1 si un fichier diffère de ce que le gabarit produit
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

from deltalib.couches import config as mod_config  # noqa: E402

DOCS = RACINE / "docs"
TEXTES = DOCS / "assets" / "textes.js"
PREFIXE = "window.DELTA_TEXTES = "
# langue → (dossier relatif à docs/, racine du site vue de la page, autre langue)
LANGUES = {"en": ("", "", "fr"), "fr": ("fr/", "../", "en")}
ONGLETS = [("aujourdhui", "aujourdhui"), ("semaine", "semaine"), ("changelogs", "changelogs"), ("actu", "actu"),
           ("reference", "reference"), ("a-tester", "a_tester"), ("archives", "archives"), ("aide", "aide")]

GABARIT = """<!doctype html>
<html lang="{langue}" data-racine="{racine}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="light dark">
  <meta name="theme-color" content="#060a13" media="(prefers-color-scheme: dark)">
  <meta name="theme-color" content="#f4f7fb" media="(prefers-color-scheme: light)">
  <meta name="apple-mobile-web-app-title" content="Delta">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>{titre}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{url}">
  <link rel="alternate" hreflang="en" href="{url_en}">
  <link rel="alternate" hreflang="fr" href="{url_fr}">
  <link rel="alternate" hreflang="x-default" href="{url_en}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Delta">
  <meta property="og:title" content="{titre}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{url}">
  <meta property="og:locale" content="{og_locale}">
  <meta property="og:locale:alternate" content="{og_locale_autre}">
  <link rel="icon" href="{racine}assets/logo.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="{racine}assets/apple-touch-icon.png">
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="stylesheet" href="{racine}assets/style.css">
</head>
<body>
  <a class="saut" href="#contenu">{saut}</a>
  <header class="entete">
    <div class="entete-carte">
      <div class="entete-ligne">
        <a class="marque" href="#aujourdhui" aria-label="{marque_aria}">
          <svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="dl" x1="0" y1="1" x2="1" y2="0"><stop offset="0" style="stop-color: var(--a1)"/><stop offset="1" style="stop-color: var(--a2)"/></linearGradient></defs><path d="M32 6 L59 56 H5 Z" fill="none" stroke="url(#dl)" stroke-width="5" stroke-linejoin="round"/><path d="M32 24 L45 48 H19 Z" fill="url(#dl)" opacity=".85"/></svg>
          <span class="marque-texte"><span class="marque-nom">{marque_nom}</span><span class="marque-sous">{marque_sous}</span></span>
        </a>
        <div class="entete-droite">
          <div id="etat-agents" class="etat-agents" aria-live="polite"></div>
          <a id="choix-langue" class="choix-langue" href="{lien_langue}" data-base="{lien_langue}" hreflang="{autre}" lang="{autre}" aria-label="{langue_aria}">{langue_lien}</a>
        </div>
      </div>
      <nav class="onglets" aria-label="{nav_aria}">
{onglets}
      </nav>
    </div>
  </header>
  <main id="contenu" class="contenu" tabindex="-1">
    <p class="chargement">{chargement}</p>
  </main>
  <footer class="pied">
    <p>{pied} <a href="#aide">{aide}</a></p>
    <p id="couche-lue" class="couche-lue"></p>
  </footer>
  <script src="{racine}assets/config.js"></script>
  <script src="{racine}assets/textes.js"></script>
  <script src="{racine}assets/app.js"></script>
</body>
</html>
"""


def charger_textes() -> dict:
    s = TEXTES.read_text(encoding="utf-8")
    return json.loads(s[s.index(PREFIXE) + len(PREFIXE):s.rindex(";")])


def url_page(base: str, langue: str) -> str:
    return base + LANGUES[langue][0]


def page(langue: str, textes: dict, base: str) -> str:
    dossier, racine, autre = LANGUES[langue]
    d = textes[langue]
    # attributs entre guillemets doubles : seuls &, <, > et " sont échappés (l'apostrophe reste lisible dans le source)
    e = lambda cle: html.escape(d[cle], quote=False).replace('"', "&quot;")  # noqa: E731
    onglets = "\n".join(f'        <a href="#{route}" data-page="{route}">{e("onglet." + cle)}</a>' for route, cle in ONGLETS)
    # lien vers l'autre langue, relatif : /fr/ depuis la racine, ../ depuis /fr/ ; app.js y ajoute ?couche et l'ancre courantes
    lien = "fr/" if langue == "en" else "../"
    return GABARIT.format(
        langue=langue, racine=racine, autre=autre, titre=e("html.titre"), description=e("html.description"),
        url=url_page(base, langue), url_en=url_page(base, "en"), url_fr=url_page(base, "fr"),
        og_locale=d["html.og_locale"], og_locale_autre=textes[autre]["html.og_locale"],
        saut=e("html.saut"), marque_aria=e("html.marque_aria"), marque_nom=e("html.marque_nom"), marque_sous=e("html.marque_sous"),
        lien_langue=lien, langue_aria=e("html.langue_aria"), langue_lien=e("html.langue_lien"), nav_aria=e("html.nav_aria"),
        onglets=onglets, chargement=e("html.chargement"), pied=e("html.pied"), aide=e("onglet.aide"))


def manifeste(langue: str, textes: dict) -> str:
    racine = LANGUES[langue][1]
    m = {
        "name": textes[langue]["manifeste.nom"], "short_name": "Delta", "lang": langue,
        "start_url": "./", "scope": "./", "display": "standalone", "background_color": "#060a13", "theme_color": "#060a13",
        "icons": [
            {"src": f"{racine}assets/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
            {"src": f"{racine}assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
    }
    return json.dumps(m, ensure_ascii=False, indent=2) + "\n"


def sitemap(base: str) -> str:
    liens = "".join(f'\n    <xhtml:link rel="alternate" hreflang="{l}" href="{url_page(base, l)}"/>' for l in LANGUES) + \
        f'\n    <xhtml:link rel="alternate" hreflang="x-default" href="{url_page(base, "en")}"/>'
    urls = "".join(f"\n  <url>\n    <loc>{url_page(base, l)}</loc>{liens}\n  </url>" for l in LANGUES)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
            f"{urls}\n</urlset>\n")


def fichiers(conf: dict | None = None) -> dict[Path, str]:
    conf = conf or mod_config.charger()
    base = conf["site_public_url"]
    if not base.endswith("/"):
        base += "/"
    textes = charger_textes()
    sortie = {}
    for langue, (dossier, _, _) in LANGUES.items():
        sortie[DOCS / dossier / "index.html"] = page(langue, textes, base)
        sortie[DOCS / dossier / "manifest.webmanifest"] = manifeste(langue, textes)
    sortie[DOCS / "sitemap.xml"] = sitemap(base)
    sortie[DOCS / "robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n"
    return sortie


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verifier", action="store_true", help="contrôler les fichiers sans écrire")
    a = p.parse_args(argv)
    ecarts = []
    for chemin, contenu in fichiers().items():
        actuel = chemin.read_text(encoding="utf-8") if chemin.is_file() else None
        if actuel == contenu:
            continue
        if a.verifier:
            ecarts.append(str(chemin.relative_to(RACINE)))
        else:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(contenu, encoding="utf-8")
            print(f"écrit : {chemin.relative_to(RACINE)}")
    if ecarts:
        print("pages par langue périmées (lancer scripts/site_langues.py) : " + ", ".join(ecarts), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
