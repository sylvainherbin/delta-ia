"""Le widget X est l'unique script tiers admis, chargé seulement dans Actu IA."""

from html.parser import HTMLParser
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import pytest

from test_relais_reference import trouver_node


DOCS = Path(__file__).resolve().parents[1] / "docs"
WIDGET = "https://platform.twitter.com/widgets.js"


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.urls.extend(v for k, v in attrs if k == "src")


def test_seul_script_tiers_admis_et_aucun_chargement_statique():
    for page in DOCS.glob("*.html"):
        scripts = Scripts()
        scripts.feed(page.read_text(encoding="utf-8"))
        # Même widgets.js doit attendre l'affichage d'Actu IA.
        assert all(not urlsplit(url).scheme and not urlsplit(url).netloc for url in scripts.urls), page
    for fichier in (DOCS / "assets").glob("*.js"):
        code = fichier.read_text(encoding="utf-8")
        creations = re.findall(r'(?:createElement|el)\(\s*[\"\']script[\"\']', code)
        if fichier.name == "app.js":
            assert len(creations) == 1
            assert re.findall(r'script\.src\s*=\s*"([^"]+)"', code) == [WIDGET]
        else:
            assert not creations, fichier
        urls = re.findall(r'[\"\'](https?://[^\"\']+\.js(?:\?[^\"\']*)?)[\"\']', code)
        assert all(url == WIDGET for url in urls), fichier


def test_mur_posts_navigation_theme_repli_et_script_unique():
    app = (DOCS / "assets/app.js").read_text(encoding="utf-8")
    utils = app[app.index("  function el("):app.index("  function texte(")]
    bloc = app[app.index("  let widgetsX;"):app.index("  function pageAujourdhui(")]
    aujourd_hui = app[app.index("  function pageAujourdhui("):app.index("  // D99 :")]
    actu = app[app.index("  function pageActu("):app.index("  /* ---------- Référence")]
    assert "blocMurX()" not in aujourd_hui and "blocMurX()" in actu
    assert "twitter-timeline" not in app and "blocListeX" not in app
    assert not re.search(r"\.innerHTML\s*=", app)
    assert 'case "actu": main.append(pageActu()); completerMurX(); break;' in app
    assert 'if (etat.page === "actu") rendre()' in app
    node = trouver_node()
    if not node:
        assert not os.environ.get("CI"), "Node est nécessaire au contrôle du mur X"
        pytest.skip("Node introuvable")
    recette = r'''
const assert = require("node:assert/strict");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; }
  append(...children) { this.children.push(...children); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() { throw new Error("aucun clic nécessaire"); }
  querySelector(q) { return this.children.find(c => c.className === q.slice(1)); }
}
let courant;
let sombre = false;
const etat = {page: "actu"};
const document = {
  head: new Element("head"),
  createElement: tag => new Element(tag),
  createTextNode: text => text,
  getElementById: () => courant,
};
const charges = [];
const window = { twttr: { widgets: { load: bloc => charges.push(bloc) } } };
const matchMedia = () => ({matches: sombre});
const vider = e => { e.children = []; };
let donnees = { ids: ["123456789", "987654321", "abc", "12<script>", 123, "1".repeat(26), "", "１２", "123456789"] };
let indisponible = false;
let casse = false;
let reseau = false;
let recuperations = 0;
const fetch = async (url, options) => {
  recuperations++;
  assert.equal(url, "data/actu/x-ids.json");
  assert.equal(options.cache, "no-cache");
  if (reseau) throw Error("hors ligne");
  return {ok: !indisponible, json: async () => { if (casse) throw Error("JSON"); return donnees; }};
};
'''
    recette += utils + bloc + r'''
(async () => {
  courant = blocMurX();
  assert.equal(document.head.children.length, 0);
  assert.equal(courant.tag, "section");
  assert.equal(courant.children[1].children[0].attrs.href, "https://x.com/i/lists/2113336377958084762");
  assert.equal(courant.children[2].children.length, 6);
  const chargement = completerMurX();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(document.head.children.length, 1);
  const script = document.head.children[0];
  assert.equal(script.src, "https://platform.twitter.com/widgets.js");
  assert.equal(script.async, true);
  script.onload();
  await chargement;
  const posts = courant.children[3];
  assert.equal(posts.children.length, 2);
  for (const [n, id] of ["123456789", "987654321"].entries()) {
    const b = posts.children[n].children[0];
    assert.equal(b.tag, "blockquote");
    assert.equal(b.className, "twitter-tweet");
    assert.deepEqual(b.attrs, {"data-theme":"light", "data-dnt":"true", "data-conversation":"none"});
    assert.equal(b.children.length, 1);
    assert.equal(b.children[0].attrs.href, `https://x.com/i/status/${id}`);
    assert.equal(b.children[0].textContent, "Voir le post sur X / View on X");
  }
  assert.deepEqual(charges, [posts]);
  // Retour dans Actu et changement de thème : nouvelles citations et load sur le nouveau conteneur.
  sombre = true;
  courant = blocMurX();
  await completerMurX();
  assert.equal(courant.children[3].children[0].children[0].attrs["data-theme"], "dark");
  assert.equal(charges.length, 2);
  assert.equal(document.head.children.length, 1);
  // Une autre page ne lit ni fichier ni script X.
  etat.page = "aujourdhui";
  const avant = recuperations;
  await completerMurX();
  assert.equal(recuperations, avant);
  etat.page = "actu";
  for (const mode of ["absent", "casse", "reseau", "vide", "null", "mauvais"]) {
    indisponible = mode === "absent"; casse = mode === "casse"; reseau = mode === "reseau";
    donnees = mode === "null" ? null : mode === "mauvais" ? {ids:"123"} : {ids:[]};
    courant = blocMurX();
    await completerMurX();
    assert.equal(courant.children[3].children[0].tag, "p");
    assert.match(courant.children[3].children[0].textContent, /Aucun post/);
    assert.equal(courant.children[1].children[0].tag, "a");
  }
  indisponible = casse = reseau = false;
  donnees = {ids:Array.from({length:40}, (_,i) => String(i+1))};
  courant = blocMurX();
  await completerMurX();
  assert.equal(courant.children[3].children.length, 30);
  // Échec réseau du script : citations de repli conservées, pas de seconde injection.
  widgetsX = undefined;
  courant = blocMurX();
  const echec = completerMurX();
  await new Promise(resolve => setImmediate(resolve));
  document.head.children[1].onerror(new Error("X indisponible"));
  await echec;
  courant = blocMurX();
  await completerMurX();
  assert.equal(document.head.children.length, 2);
  assert.equal(courant.children[3].children.length, 30);
  // Réponse tardive d'une page quittée : aucun script ni mutation du nouveau mur.
  let resoudre;
  fetch = () => new Promise(resolve => { resoudre = resolve; });
  const tardif = completerMurX();
  courant = blocMurX();
  resoudre({ok:true, json:async () => ({ids:["111"]})});
  await tardif;
  assert.match(courant.children[3].children[0].textContent, /Chargement/);
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
    # fetch est remplacé dans le dernier scénario.
    recette = recette.replace("const fetch = async", "let fetch = async")
    subprocess.run([node, "--unhandled-rejections=strict", "-e", recette], check=True, capture_output=True, text=True)
