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
    "https://releasebot.io/updates/openai/chatgpt/__data.json": ("releasebot_data.json", "application/json"),
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


AGENTS = {"claude": "claude-code", "actu": "claude-code", "openai": "codex"}


def element_depuis_brut(n: dict, impact: str = "faible", ids_bruts=None) -> dict:
    """Un élément SPEC §7.2 minimal et valide construit à partir d'une nouveauté brute."""
    return {
        "id": (ids_bruts or [n["id"]])[0], "ids_bruts": ids_bruts or [n["id"]], "produit": n["produit"], "titre": n["titre"],
        "version": n.get("version"), "date_publication": n.get("date_publication"), "type": "nouveaute",
        "resume": "Résumé de test.", "sources": [{"url": n["url"], "libelle": "source", "officielle": bool(n.get("officielle"))}],
        "certitude": "officiel" if n.get("officielle") else "rapporte", "impact": impact,
        "pour_toi": None if impact == "nul" else "Pertinent pour trading-sim.", "projets_concernes": [] if impact == "nul" else ["trading-sim"],
        "action": None, "kb_refs": [], "contexte_sections": {},  # D64-bis : obligatoire après le 24/09/2026
    }


def ecrire_quotidien(racine: Path, perimetre: str, brut: dict, jour: str, couvrir=None, ecarter=(), extra_elements=()) -> Path:
    """Écrit docs/data/<p>/<jour>.json et index.json couvrant les nouveautés du brut (toutes par défaut)."""
    import json
    nouveautes = brut.get("nouveautes", [])
    couvrir = set(couvrir) if couvrir is not None else {n["id"] for n in nouveautes} - set(ecarter)
    elements = [element_depuis_brut(n) for n in nouveautes if n["id"] in couvrir] + list(extra_elements)
    q = {
        "date": jour, "perimetre": perimetre, "agent": AGENTS[perimetre], "genere_le": f"{jour}T12:00:00+00:00",
        "synthese": "Synthèse de test.", "sources_en_echec": brut.get("sources_en_echec", []), "elements": elements,
        "ecartes": [{"id": i, "raison": "hors sujet (test)"} for i in ecarter],
        "contexte_empreinte": "0" * 40,
    }
    dossier = racine / "docs" / "data" / perimetre
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{jour}.json").write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    jours = []
    for f in sorted(dossier.glob("????-??-??.json"), reverse=True):
        d = json.loads(f.read_text(encoding="utf-8"))
        impacts = {k: 0 for k in ("fort", "moyen", "faible", "nul")}
        for e in d["elements"]:
            impacts[e["impact"]] += 1
        jours.append({"date": d["date"], "genere_le": d["genere_le"], "elements": len(d["elements"]), "impact": impacts, "ecartes": len(d["ecartes"])})
    (dossier / "index.json").write_text(json.dumps({"perimetre": perimetre, "agent": AGENTS[perimetre], "maj_le": f"{jour}T12:00:00+00:00", "jours": jours}, ensure_ascii=False, indent=1), encoding="utf-8")
    return dossier / f"{jour}.json"
