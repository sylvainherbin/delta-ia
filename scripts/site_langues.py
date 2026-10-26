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
  <meta name="theme-color" content="#050506" media="(prefers-color-scheme: dark)">
  <meta name="theme-color" content="#f4f3ef" media="(prefers-color-scheme: light)">
  <meta name="apple-mobile-web-app-title" content="ORQYRA AI">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>{titre}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{url}">
  <link rel="alternate" hreflang="en" href="{url_en}">
  <link rel="alternate" hreflang="fr" href="{url_fr}">
  <link rel="alternate" hreflang="x-default" href="{url_en}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="ORQYRA AI">
  <meta property="og:title" content="{titre}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{url}">
  <meta property="og:locale" content="{og_locale}">
  <meta property="og:locale:alternate" content="{og_locale_autre}">
  <link rel="icon" href="{racine}assets/favicon.ico" sizes="32x32">
  <link rel="icon" href="{racine}assets/favicon.svg" type="image/svg+xml">
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
          <svg class="logotype" viewBox="-14 -16 866 132" aria-hidden="true"><g class="logotype-signe" transform="translate(0,-3.92)"><path d="M0,103.92 L60,0 L120,103.92 Z" fill="none" stroke="currentColor" stroke-width="10" stroke-linejoin="miter" stroke-miterlimit="12"/><circle cx="60" cy="69.28" r="9" fill="currentColor"/></g><g transform="translate(176,0)" fill="none" stroke="currentColor" stroke-width="10"><circle cx="53" cy="50" r="48"/><path d="M139.8,100 L139.8,5 L166,5 A22.6,22.6 0 0 1 166,50.2 L139.8,50.2"/><line x1="164" y1="50.2" x2="202" y2="100"/><circle cx="287" cy="50" r="48"/><line x1="295" y1="58" x2="344" y2="112"/><path d="M375,0 L413,50 L451,0 M413,50 L413,100"/><path d="M485.8,100 L485.8,5 L512,5 A22.6,22.6 0 0 1 512,50.2 L485.8,50.2"/><line x1="510" y1="50.2" x2="548" y2="100"/><path d="M580,100 L622,8 L664,100" stroke-miterlimit="12"/></g></svg>
          <span class="marque-texte"><span class="marque-nom">{marque_nom}</span><span class="marque-ai" aria-hidden="true">{marque_ai}</span><span class="marque-sous">{marque_sous}</span></span>
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
    <svg class="pied-signe" viewBox="-11.5 -13.8 143 129.22" aria-hidden="true"><path d="M0,103.92 L60,0 L120,103.92 Z" fill="none" stroke="currentColor" stroke-width="10" stroke-linejoin="miter" stroke-miterlimit="12"/><circle cx="60" cy="69.28" r="9" fill="currentColor"/></svg>
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
        saut=e("html.saut"), marque_aria=e("html.marque_aria"), marque_nom=e("html.marque_nom"), marque_ai=e("html.marque_ai"),
        marque_sous=e("html.marque_sous"),
        lien_langue=lien, langue_aria=e("html.langue_aria"), langue_lien=e("html.langue_lien"), nav_aria=e("html.nav_aria"),
        onglets=onglets, chargement=e("html.chargement"), pied=e("html.pied"), aide=e("onglet.aide"))


def manifeste(langue: str, textes: dict) -> str:
    racine = LANGUES[langue][1]
    m = {
        "name": textes[langue]["manifeste.nom"], "short_name": "ORQYRA AI", "lang": langue,
        "start_url": "./", "scope": "./", "display": "standalone", "background_color": "#050506", "theme_color": "#050506",
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
