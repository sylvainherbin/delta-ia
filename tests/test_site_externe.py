"""Le repli X reste un ensemble de liens, sans chargement de script tiers."""

from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit


DOCS = Path(__file__).resolve().parents[1] / "docs"


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.urls.extend(v for k, v in attrs if k == "src")


def test_repli_x_sans_script_externe():
    # Aucun script tiers admis tant que le widget X n'a pas passé le test sans compte.
    for page in DOCS.glob("*.html"):
        scripts = Scripts()
        scripts.feed(page.read_text(encoding="utf-8"))
        assert all(not urlsplit(url).scheme and not urlsplit(url).netloc for url in scripts.urls), page
    for fichier in (DOCS / "assets").glob("*.js"):
        code = fichier.read_text(encoding="utf-8")
        assert "widgets.js" not in code, fichier
        assert not re.search(r'(?:createElement|el)\(\s*[\"\']script[\"\']', code), fichier
