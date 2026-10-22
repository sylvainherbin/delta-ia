"""Le widget X est l'unique script tiers admis, chargé à la première ouverture."""

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit


DOCS = Path(__file__).resolve().parents[1] / "docs"
WIDGET = "https://platform.x.com/widgets.js"


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
        # Même widgets.js doit attendre l'ouverture du bloc.
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


def test_widget_differe_reouverture_navigation_et_repli():
    app = (DOCS / "assets/app.js").read_text(encoding="utf-8")
    utils = app[app.index("  function el("):app.index("  function texte(")]
    bloc = app[app.index("  let widgetsX;"):app.index("  function pageAujourdhui(")]
    node = shutil.which("node")
    assert node, "Node est nécessaire au contrôle du chargement différé"
    recette = r'''
const assert = require("node:assert/strict");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.open = false; }
  append(...children) { this.children.push(...children); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(k, f) { this.events[k] = f; }
  toggle(open) { this.open = open; this.events.toggle(); }
}
const document = {
  head: new Element("head"),
  createElement: tag => new Element(tag),
  createTextNode: text => text,
};
const charges = [];
const window = { twttr: { widgets: { load: bloc => charges.push(bloc) } } };
'''
    recette += utils + bloc + r'''
(async () => {
  const premier = blocListeX();
  assert.equal(premier.open, false);
  assert.equal(document.head.children.length, 0);
  premier.toggle(false);
  assert.equal(document.head.children.length, 0);
  const ancre = premier.children[1];
  assert.equal(ancre.className, "twitter-timeline");
  assert.equal(ancre.attrs.href, "https://x.com/i/lists/2113336377958084762");
  assert.match(ancre.textContent, /Ouvrir la liste \/ Open list/);
  assert.equal(premier.children[3].children.length, 6);
  premier.toggle(true);
  assert.equal(document.head.children.length, 1);
  const script = document.head.children[0];
  assert.equal(script.src, "https://platform.x.com/widgets.js");
  assert.equal(script.async, true);
  premier.toggle(false);
  premier.toggle(true);
  assert.equal(document.head.children.length, 1);
  script.onload();
  await Promise.resolve();
  assert.deepEqual(charges, [premier]);
  const suivant = blocListeX();
  suivant.toggle(true);
  await Promise.resolve();
  assert.equal(document.head.children.length, 1);
  assert.deepEqual(charges, [premier, suivant]);
  // Nouveau chargement de page : erreur réseau X, sans rejet non géré.
  widgetsX = undefined;
  const repli = blocListeX();
  repli.toggle(true);
  document.head.children[1].onerror(new Error("X indisponible"));
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(repli.children[1].attrs.href, ancre.attrs.href);
  assert.equal(repli.children[3].children.length, 6);
})();
'''
    subprocess.run([node, "--unhandled-rejections=strict", "-e", recette], check=True, capture_output=True, text=True)
