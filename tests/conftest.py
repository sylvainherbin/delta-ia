"""Outils communs : chemin de la bibliothèque, faux client HTTP, sources réelles, date figée."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

from deltalib.http import Reponse  # noqa: E402
from deltalib.modeles import ErreurReseau  # noqa: E402
from deltalib.sources import charger_sources  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
AUJOURD_HUI = date(2026, 9, 23)  # date d'enregistrement des échantillons : la fenêtre de 30 jours en dépend

# URL réelle (telle que dans sources.yaml) -> (fichier d'échantillon, Content-Type)
CORRESPONDANCES = {
    "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md": ("cc_changelog.md", "text/plain; charset=utf-8"),
    "https://api.github.com/repos/anthropics/claude-code/releases?per_page=100": ("cc_releases.json", "application/json; charset=utf-8"),
    "https://support.claude.com/en/articles/12138966-release-notes.md": ("claude_apps.md", "text/markdown; charset=utf-8"),
    "https://support.claude.com/en/articles/12138966-release-notes": ("claude_apps.html", "text/html; charset=utf-8"),
    "https://platform.claude.com/docs/en/release-notes/overview.md": ("claude_platform.md", "text/markdown; charset=utf-8"),
    "https://www.anthropic.com/news": ("anthropic_news.html", "text/html; charset=utf-8"),
    "https://api.github.com/repos/openai/codex/releases?per_page=10": ("codex_releases.json", "application/json; charset=utf-8"),
    "https://api.github.com/repos/openai/codex/releases?per_page=10&page=2": ("codex_releases_p2.json", "application/json; charset=utf-8"),
    "https://api.github.com/repos/openai/codex/releases?per_page=10&page=3": ("codex_releases_p3.json", "application/json; charset=utf-8"),
    "https://api.github.com/repos/openai/codex/releases?per_page=10&page=4": ("page_vide.json", "application/json; charset=utf-8"),
    "https://api.github.com/repos/openai/codex/releases/latest": ("codex_latest.json", "application/json; charset=utf-8"),
    "https://learn.chatgpt.com/docs/changelog/general.json": ("oa_general.json", "application/json; charset=utf-8"),
    "https://learn.chatgpt.com/docs/changelog/codex-app.json": ("oa_codex_app.json", "application/json; charset=utf-8"),
    "https://learn.chatgpt.com/docs/changelog/ios.json": ("oa_ios.json", "application/json; charset=utf-8"),
    "https://openai.com/news/rss.xml": ("openai_news.xml", "text/xml; charset=utf-8"),
    "https://simonwillison.net/atom/everything/": ("simonw.atom", "application/xml; charset=utf-8"),
    "https://deepmind.google/blog/rss.xml": ("deepmind.xml", "text/xml"),
    "https://importai.substack.com/feed": ("deepmind.xml", "application/xml; charset=utf-8"),
    "https://arstechnica.com/ai/feed/": ("deepmind.xml", "application/rss+xml; charset=UTF-8"),
}


class FauxClient:
    """Sert les échantillons enregistrés à la place du réseau. `pannes` : url -> exception ou (texte, type)."""

    def __init__(self, pannes: dict | None = None) -> None:
        self.pannes = pannes or {}
        self.appels: list[str] = []

    def get(self, url: str, accept: str | None = None) -> Reponse:
        self.appels.append(url)
        if url in self.pannes:
            p = self.pannes[url]
            if isinstance(p, Exception):
                raise p
            texte, content_type = p
            return Reponse(url, 200, content_type, texte)
        if url not in CORRESPONDANCES:
            raise ErreurReseau(f"HTTP 404 pour {url} (aucun échantillon)")
        fichier, content_type = CORRESPONDANCES[url]
        return Reponse(url, 200, content_type, (FIXTURES / fichier).read_text(encoding="utf-8"))


@pytest.fixture
def sources():
    return {s.id: s for s in charger_sources(RACINE / "sources.yaml")}


@pytest.fixture
def client():
    return FauxClient()


@pytest.fixture
def fixture_texte():
    def _lire(nom: str) -> str:
        return (FIXTURES / nom).read_text(encoding="utf-8")
    return _lire


@pytest.fixture
def date_figee(monkeypatch):
    import deltalib.passage as passage
    monkeypatch.setattr(passage, "aujourd_hui", lambda: AUJOURD_HUI)
    return AUJOURD_HUI
