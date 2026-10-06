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
    "https://learn.chatgpt.com/docs/pricing.md": ("oa_pricing.md", "text/markdown; charset=utf-8"),
    "https://learn.chatgpt.com/docs/changelog/codex-app.json": ("oa_codex_app.json", "application/json; charset=utf-8"),
    "https://learn.chatgpt.com/docs/changelog/ios.json": ("oa_ios.json", "application/json; charset=utf-8"),
    "https://openai.com/news/rss.xml": ("openai_news.xml", "text/xml; charset=utf-8"),
    "https://releasebot.io/updates/openai/chatgpt/__data.json": ("releasebot_data.json", "application/json"),
    "https://simonwillison.net/atom/everything/": ("simonw.atom", "application/xml; charset=utf-8"),
    "https://deepmind.google/blog/rss.xml": ("deepmind.xml", "text/xml"),
    "https://importai.substack.com/feed": ("deepmind.xml", "application/xml; charset=utf-8"),
    "https://arstechnica.com/ai/feed/": ("deepmind.xml", "application/rss+xml; charset=UTF-8"),
}

# Étape 2a : articles d'aide suivis (tous servis par l'extrait réel de l'article « What is a limit reset? »), index llms.txt
ARTICLES_AIDE = ("11647753-how-do-usage-and-length-limits-work", "9797557-usage-limit-best-practices", "17007452-what-is-a-limit-reset",
                 "14246112-buy-usage-bundles", "12429409-manage-usage-credits-for-paid-claude-plans",
                 "14552983-models-usage-and-limits-in-claude-code", "11145838-use-claude-code-with-your-pro-or-max-plan",
                 "15424964-claude-fable-models-on-your-plan", "15036540-use-the-claude-agent-sdk-with-your-claude-plan",
                 "11049741-what-is-the-max-plan")
for _slug in ARTICLES_AIDE:
    CORRESPONDANCES[f"https://support.claude.com/en/articles/{_slug}.md"] = ("aide_limit_reset.md", "text/markdown; charset=utf-8")
CORRESPONDANCES["https://support.claude.com/llms.txt"] = ("aide_llms_claude.txt", "text/plain; charset=utf-8")
CORRESPONDANCES["https://learn.chatgpt.com/llms.txt"] = ("oa_llms_index.txt", "text/plain; charset=utf-8")
CORRESPONDANCES["https://learn.chatgpt.com/docs/developer-commands.md?surface=cli"] = ("oa_devcmd_usage.md", "text/markdown; charset=utf-8")

# Étape 2b : blog claude.com (liste + deux articles réels), page d'état OpenAI (JSON Statuspage et repli RSS)
CORRESPONDANCES["https://claude.com/blog"] = ("claude_blog.html", "text/html; charset=utf-8")
CORRESPONDANCES["https://claude.com/blog/claude-marketplace"] = ("claude_blog_article_marketplace.html", "text/html; charset=utf-8")
CORRESPONDANCES["https://claude.com/blog/claude-tag-now-supports-personal-connectors-in-channels"] = (
    "claude_blog_article_tag.html", "text/html; charset=utf-8")
CORRESPONDANCES["https://status.openai.com/api/v2/incidents.json"] = ("status_openai_incidents.json", "application/json; charset=utf-8")
CORRESPONDANCES["https://status.claude.com/api/v2/incidents.json"] = ("status_claude_incidents.json", "application/json; charset=utf-8")
CORRESPONDANCES["https://status.openai.com/history.rss"] = ("status_openai_history.rss", "application/rss+xml")

# Étape 2c : pages officielles des dépréciations de modèles (échantillons réels du 2026-10-01)
CORRESPONDANCES["https://platform.claude.com/docs/en/about-claude/model-deprecations.md"] = ("deprec_anthropic.md", "text/markdown; charset=utf-8")
CORRESPONDANCES["https://developers.openai.com/api/docs/deprecations.md"] = ("deprec_openai.md", "text/markdown; charset=utf-8")


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
        if url not in CORRESPONDANCES and url.startswith("https://www.anthropic.com/") and url != "https://www.anthropic.com/news":
            # A1 : les articles de la newsroom sont lus ; tous servis par l'extrait réel de l'article Opus 5.5
            return Reponse(url, 200, "text/html; charset=utf-8",
                           (FIXTURES / "anthropic_article_opus55.html").read_text(encoding="utf-8"))
        if url not in CORRESPONDANCES and url.startswith("https://claude.com/blog/"):
            # étape 2b : les autres articles du blog sont servis par l'extrait réel du billet « Claude Marketplace »
            return Reponse(url, 200, "text/html; charset=utf-8",
                           (FIXTURES / "claude_blog_article_marketplace.html").read_text(encoding="utf-8"))
        if url not in CORRESPONDANCES:
            raise ErreurReseau(f"HTTP 404 pour {url} (aucun échantillon)")
        fichier, content_type = CORRESPONDANCES[url]
        return Reponse(url, 200, content_type, (FIXTURES / fichier).read_text(encoding="utf-8"))


def sockets_locaux_permis() -> bool:
    """Vrai si le bac à sable laisse ouvrir un socket local (PermissionError / EPERM / EACCES sinon)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
        return True
    except OSError:  # PermissionError en est une sous-classe
        return False


@pytest.fixture
def sockets_locaux():
    """À demander par tout test qui ouvre un socket local : ignoré quand le bac à sable l'interdit."""
    if not sockets_locaux_permis():
        pytest.skip("sockets locaux interdits par le bac à sable")


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
