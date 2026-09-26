"""A1 (26/09) : le texte principal de chaque nouvel article de la newsroom Anthropic va dans `contenu`."""

import json

import pytest

import fetch
from conftest import FIXTURES, FauxClient
from deltalib.analyseurs.html_notes import TAILLE_MAX_ARTICLE, texte_article
from deltalib.modeles import ErreurReseau, FormatInattendu

ARTICLE = (FIXTURES / "anthropic_article_opus55.html").read_text(encoding="utf-8")


def test_texte_article_extrait_reel_opus55():
    t = texte_article(ARTICLE)
    assert t.startswith("We’re introducing Claude Opus 5.5")
    assert "providing subscription users a rate limit reset" in t, "la remise à zéro manquée le 23/09 est lue"
    assert "increasing five-hour usage limits" in t
    assert "News" not in t.splitlines()[0], "la navigation n'entre pas"
    assert len(t) < 8000, "seul le plus long <article> est retenu"


@pytest.mark.parametrize("html", [
    "<html><body><div>rien</div></body></html>",
    "<html><body><main><article><p>Court.</p></article></main></body></html>",
])
def test_texte_article_gabarit_change(html):
    with pytest.raises(FormatInattendu):
        texte_article(html)


def test_texte_article_tronque():
    long = "<main><article>" + "".join(f"<p>Paragraphe {i} " + "x" * 200 + "</p>" for i in range(200)) + "</article></main>"
    t = texte_article(long)
    assert len(t) <= TAILLE_MAX_ARTICLE + 30 and t.endswith("[… texte tronqué]")


def test_passage_lit_les_nouveaux_articles(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-01"]) == 0
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    news = [n for n in brut["nouveautes"] if n["source_id"] == "anthropic-newsroom"]
    assert news and all("rate limit reset" in n["contenu"] for n in news)
    assert not [e for e in brut["sources_en_echec"] if "article" in e["erreur"]]


def test_article_illisible_remonte_en_echec_sans_contenu_vide(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    client = FauxClient()
    fetch_brut = lambda c: (monkeypatch.setattr(fetch, "Client", lambda: c), fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-01"]))
    # premier appel pour connaître les URL d'articles
    fetch_brut(client)
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    urls = [n["url"] for n in brut["nouveautes"] if n["source_id"] == "anthropic-newsroom"]
    assert len(urls) >= 2
    pannes = {urls[0]: ErreurReseau("HTTP 403"), urls[1]: ("<html><body><p>vide</p></body></html>", "text/html")}
    fetch_brut(FauxClient(pannes))
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    par_url = {n["url"]: n for n in brut["nouveautes"]}
    echecs = {e["url"]: e for e in brut["sources_en_echec"]}
    for u in urls[:2]:
        assert u in echecs and echecs[u]["partiel"] is True and "article illisible" in echecs[u]["erreur"]
        assert par_url[u]["contenu"] is not None and "rate limit reset" not in par_url[u]["contenu"], "résumé de la liste gardé"
    assert "rate limit reset" in par_url[urls[2]]["contenu"] if len(urls) > 2 else True
