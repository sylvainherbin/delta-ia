"""Chaque analyseur sur un échantillon réel enregistré, plus les erreurs de format attendues."""

import json

import pytest

from deltalib.analyseurs import ANALYSEURS, github_changelog, github_releases, html_notes, json_changelog, rss
from deltalib.modeles import ErreurReseau, FormatInattendu

CHAMPS = {"id", "produit", "titre", "version", "date_publication", "url", "contenu", "source_id", "officielle",
          "empreinte", "revision"}


def test_tous_les_types_ont_un_analyseur():
    assert set(ANALYSEURS) == {"github_changelog", "github_releases", "html", "rss", "json"}


def test_format_brut_commun(sources, client):
    for sid in ("claude-code-changelog", "codex-cli-releases", "claude-apps-notes", "anthropic-newsroom",
                "openai-changelog-ios", "openai-news", "simon-willison"):
        s = sources[sid]
        for e in ANALYSEURS[s.type](s, client).elements:
            d = e.en_dict()
            assert set(d) == CHAMPS, sid
            assert d["produit"] == s.produit and d["source_id"] == sid and d["officielle"] == s.officielle
            assert d["url"].startswith("https://") and d["titre"]


# --- github_changelog -------------------------------------------------------------------------------------

def test_changelog_claude_code_versions_et_dates(sources, client):
    r = github_changelog.analyser(sources["claude-code-changelog"], client)
    assert r.partiel is None
    versions = [e.version for e in r.elements]
    assert versions == ["2.1.280", "2.1.278", "2.1.277"]
    e = r.elements[0]
    assert e.date_publication == "2026-09-22"  # published_at de la release v2.1.280
    assert e.titre == "Claude Code 2.1.280"
    assert e.url == "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#21280"
    assert "claude-opus-5-5" in e.contenu and e.produit == "claude-code"
    assert e.id == "claude-code-2.1.280"  # D1 : clé native, sans le titre


def test_changelog_api_releases_en_panne_est_un_echec_partiel(sources):
    from conftest import FauxClient
    url_api = sources["claude-code-changelog"].options["releases_url"]
    r = github_changelog.analyser(sources["claude-code-changelog"], FauxClient({url_api: ErreurReseau("HTTP 503")}))
    assert len(r.elements) == 3
    assert all(e.date_publication is None for e in r.elements)  # jamais devinées
    assert r.partiel and "dates indisponibles" in r.partiel


def test_changelog_sans_section_est_un_format_inattendu(sources):
    with pytest.raises(FormatInattendu):
        github_changelog.parser_changelog("# Changelog\n\nrien ici\n", sources["claude-code-changelog"])


def test_changelog_page_html_refusee(sources):
    from conftest import FauxClient
    s = sources["claude-code-changelog"]
    with pytest.raises(FormatInattendu):
        github_changelog.analyser(s, FauxClient({s.url: ("<html><body>404</body></html>", "text/html")}))


# --- github_releases --------------------------------------------------------------------------------------

def test_releases_codex_exclut_les_prereleases(sources, client):
    r = github_releases.analyser(sources["codex-cli-releases"], client)
    assert [e.version for e in r.elements] == ["0.156.1", "0.156.0"]  # 3 alphas exclues
    e = r.elements[0]
    assert e.titre == "Codex CLI 0.156.1" and e.date_publication == "2026-09-23"
    assert e.url == "https://github.com/openai/codex/releases/tag/rust-v0.156.1"
    assert "GPT-6 Sol" in e.contenu


def test_releases_option_inclure_prereleases(sources, client):
    s = sources["codex-cli-releases"]
    s.options = dict(s.options, inclure_prereleases=True)
    r = github_releases.analyser(s, client)
    assert len(r.elements) == 5 and "0.157.0-alpha.11" in [e.version for e in r.elements]
    assert r.elements[1].id == "rust-v0.158.0-alpha.2"  # D1 : le tag


def test_releases_reponse_inattendue(sources):
    s = sources["codex-cli-releases"]
    with pytest.raises(FormatInattendu):
        github_releases.parser_releases({"message": "Not Found"}, s)
    with pytest.raises(FormatInattendu):
        github_releases.parser_releases([], s)
    with pytest.raises(FormatInattendu):
        github_releases.parser_releases([{"tag_name": "v1"}], s)  # champs manquants


# --- html (Markdown daté, HTML daté, liens <time>) --------------------------------------------------------

def test_notes_apps_markdown(sources, client):
    r = html_notes.analyser(sources["claude-apps-notes"], client)
    assert [(e.date_publication, e.titre) for e in r.elements] == [
        ("2026-09-22", "Claude Opus 5.5 launch"),
        ("2026-09-15", "Launching Salesforce in Claude (beta)"),
        ("2026-09-10", "Smart reports (beta)"),
    ]
    assert all(e.version is None and e.produit == "claude" for e in r.elements)
    assert "40% less" in r.elements[0].contenu
    assert r.elements[0].id == "claude-apps-notes-2026-09-22"  # D1 : une entrée par date


def test_notes_apps_html_de_repli_donne_les_memes_identifiants(sources, client, fixture_texte):
    """Le repli HTML doit produire les mêmes identifiants que la variante Markdown."""
    s = sources["claude-apps-notes"]
    md = html_notes.parser_markdown_date(fixture_texte("claude_apps.md"), s)
    html = html_notes.parser_html_date(fixture_texte("claude_apps.html"), s)
    assert [e.id for e in html] == [e.id for e in md]


def test_notes_platform_une_entree_par_date(sources, client):
    r = html_notes.analyser(sources["claude-platform-notes"], client)
    assert [e.date_publication for e in r.elements] == ["2026-09-22", "2026-09-18", "2026-09-14"]
    assert r.elements[0].titre == "Claude Platform — 2026-09-22"
    assert "Claude Opus 5.5" in r.elements[0].contenu


def test_newsroom_anthropic(sources, client):
    r = html_notes.analyser(sources["anthropic-newsroom"], client)
    assert len(r.elements) == 6
    e = r.elements[0]
    assert e.titre == "Introducing Claude Opus 5.5" and e.date_publication == "2026-09-22"
    assert e.url == "https://www.anthropic.com/claude-opus-5-5"  # lien relatif résolu
    assert len({e.url for e in r.elements}) == 6
    assert e.id == e.url  # D1 : la newsroom est identifiée par l'URL de l'article


@pytest.mark.parametrize("fmt, texte", [
    ("markdown_date", "# Notes\n\nPas de titre daté.\n"),
    ("markdown_date", "### Titre sans date\n\ncontenu\n"),
    ("html_date", "<html><body><article><h2>Rien</h2></article></body></html>"),
    ("html_time_liens", "<html><body><a href='/x'><h2>Sans time</h2></a></body></html>"),
    ("html_time_liens", "<html><body><time>Sep 1, 2026</time><p>time hors lien</p></body></html>"),
])
def test_html_gabarit_change_est_un_format_inattendu(sources, fmt, texte):
    with pytest.raises(FormatInattendu):
        html_notes.PARSEURS[fmt](texte, sources["anthropic-newsroom"])


def test_html_markdown_attendu_mais_html_recu(sources):
    from conftest import FauxClient
    s = sources["claude-apps-notes"]
    with pytest.raises(FormatInattendu):
        html_notes.analyser(s, FauxClient({s.url: ("<html><body><h3>September 1, 2026</h3></body></html>", "text/html")}))


# --- json ---------------------------------------------------------------------------------------------------

def test_json_general(sources, client):
    r = json_changelog.analyser(sources["openai-changelog-general"], client)
    assert len(r.elements) == 5
    e = r.elements[0]
    assert e.titre == "GPT-6 Sol and Luna in Codex and ChatGPT Work" and e.date_publication == "2026-09-22"
    assert e.version is None and e.produit == "codex" and e.id == "oa-codex/2026-09-22-gpt-6-sol-luna"
    assert e.url == "https://developers.openai.com/codex/changelog#codex-2026-09-22-gpt-6-sol-luna"
    assert "codex --model gpt-6-sol" in e.contenu


def test_json_ios_versions(sources, client):
    r = json_changelog.analyser(sources["openai-changelog-ios"], client)
    assert [e.version for e in r.elements] == ["1.2026.251", "1.2026.244", "1.2026.237"]
    assert r.elements[0].titre == "ChatGPT for iOS 1.2026.251" and r.elements[0].produit == "chatgpt"


@pytest.mark.parametrize("donnees", [
    [],                                              # liste au lieu d'objet
    {"schemaVersion": 2, "items": [{"id": "a", "title": "t", "date": "2026-09-01"}]},
    {"feeds": []},                                   # index au lieu d'un flux
    {"items": []},                                   # vide
    {"items": [{"id": "a", "title": "t"}]},          # date manquante
    {"items": ["chaîne"]},
])
def test_json_derive_de_format(sources, donnees):
    with pytest.raises(FormatInattendu):
        json_changelog.parser_json(donnees, sources["openai-changelog-ios"])


def test_json_html_recu(sources):
    from conftest import FauxClient
    s = sources["openai-changelog-ios"]
    with pytest.raises(FormatInattendu):
        json_changelog.analyser(s, FauxClient({s.url: ("<!doctype html><html></html>", "text/html")}))


# --- rss ----------------------------------------------------------------------------------------------------

def test_rss_openai_news_filtre_par_categorie(sources, client, fixture_texte):
    s = sources["openai-news"]
    filtres = rss.analyser(s, client).elements
    sans_filtre = rss.parser_flux(fixture_texte("openai_news.xml"), type(s)(**{**s.__dict__, "options": {}}))[0]
    assert len(sans_filtre) == 8 and 0 < len(filtres) < 8
    assert all(e.produit == "chatgpt" and e.version is None for e in filtres)
    assert filtres[0].url.startswith("https://openai.com/") and filtres[0].date_publication is not None


def test_atom_simon_willison(sources, client):
    r = rss.analyser(sources["simon-willison"], client)
    assert len(r.elements) == 3
    e = r.elements[0]
    assert e.url.startswith("https://simonwillison.net/2026/") and e.date_publication == "2026-09-23"
    assert "<" not in e.contenu[:200]  # HTML converti en texte


def test_rss_deepmind(sources, client):
    r = rss.analyser(sources["google-deepmind"], client)
    assert [e.date_publication for e in r.elements] == ["2026-09-15", "2026-09-08", "2026-09-03"]


@pytest.mark.parametrize("texte", [
    "<html><body>Just a moment...</body></html>",
    "<rss version='2.0'><channel><title>vide</title></channel></rss>",
    "<feed xmlns='http://www.w3.org/2005/Atom'><title>vide</title></feed>",
    "<rss><channel><item><title>sans lien</title></item></channel></rss>",
    "pas du xml",
])
def test_rss_format_inattendu(sources, texte):
    with pytest.raises(FormatInattendu):
        rss.parser_flux(texte, sources["simon-willison"])


def test_releases_latest_complete_la_liste(sources, client):
    """`releases/latest` ajoute la dernière stable si la liste courte ne la contient pas (fixture : 0.156.0 absente de la liste)."""
    s = sources["codex-cli-releases"]
    r = github_releases.analyser(s, client)
    assert [e.version for e in r.elements] == ["0.156.1", "0.156.0"] and r.partiel is None
    assert s.options["url_latest"] in client.appels


def test_releases_latest_indisponible_est_partiel(sources):
    from conftest import FauxClient
    s = sources["codex-cli-releases"]
    r = github_releases.analyser(s, FauxClient({s.options["url_latest"]: ErreurReseau("HTTP 500")}))
    assert [e.version for e in r.elements] == ["0.156.1"] and "latest" in r.partiel
