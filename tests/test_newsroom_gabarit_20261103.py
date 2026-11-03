"""Newsroom : capture HTTP publique du 03/11/2026, rejouée sans réseau."""

import json

import pytest
from bs4 import BeautifulSoup

import fetch
from conftest import FIXTURES, RACINE, FauxClient
from deltalib.analyseurs.html_notes import analyser, parser_html_time_liens
from deltalib.modeles import FormatInattendu

CAPTURE = (FIXTURES / "anthropic_news_2026-11-03.html").read_text(encoding="utf-8")
BASE = "https://www.anthropic.com"


def test_capture_reelle_trois_zones_et_champs(sources):
    source = sources["anthropic-newsroom"]
    resultat = analyser(source, FauxClient({source.url: (CAPTURE, "text/html")}))
    elements = resultat.elements
    assert len(elements) == len({e.id for e in elements}) == 28  # 35 cartes, 7 répétitions
    assert all(e.id == e.url and e.titre and e.date_publication and e.contenu for e in elements)
    assert all(e.source_id == source.id and e.produit == source.produit and e.officielle for e in elements)
    par_url = {e.url: e for e in elements}
    # Une carte de la grille, du carrousel et de la table ; titre/date/résumé lus dans le DOM.
    for chemin, titre, date, extrait in [
        ("/news/public-benefit-fund", "Investing in the public benefit", "2026-10-18",
         "We’re committing a portion of Anthropic’s shares"),
        ("/features/ebola-response", "The Situation Report", "2026-09-21", "A rare Ebola strain"),
        ("/news/ai-for-science-expands-foundations-research-institutions",
         "AI for Science expands to foundations and research institutions", "2026-10-28",
         "We’re highlighting 20 scientific foundations"),
    ]:
        e = par_url[BASE + chemin]
        assert (e.titre, e.date_publication) == (titre, date)
        assert extrait in e.contenu
    opus = par_url[BASE + "/claude-opus-5-5"]
    assert (opus.titre, opus.date_publication) == ("Introducing Claude Opus 5.5", "2026-09-22")


def test_identifiants_deja_publies_inchanges(sources):
    # Lecture seule des ids_bruts historiques : aucune réécriture de docs/data ou state.
    publies = set()
    for chemin in (RACINE / "docs/data/claude").glob("????-??-??.json"):
        for element in json.loads(chemin.read_text(encoding="utf-8")).get("elements", []):
            publies.update(i for i in element.get("ids_bruts", []) if i.startswith(BASE + "/"))
    extraits = {e.id for e in parser_html_time_liens(CAPTURE, sources["anthropic-newsroom"])}
    assert len(publies) >= 7
    assert publies <= extraits


@pytest.mark.parametrize("nom, nombre", [("anthropic_news.html", 6), ("anthropic_news_current.html", 3)])
def test_anciens_gabarits_conserves(sources, nom, nombre):
    elements = parser_html_time_liens((FIXTURES / nom).read_text(encoding="utf-8"), sources["anthropic-newsroom"])
    assert len(elements) == nombre
    assert elements[0].id == BASE + "/claude-opus-5-5"
    assert (elements[0].titre, elements[0].date_publication) == ("Introducing Claude Opus 5.5", "2026-09-22")
    assert elements[0].contenu


@pytest.mark.parametrize("defaut", ["vide", "sans_time", "structure", "titre"])
def test_capture_modifiee_signalee_par_le_cli(tmp_path, monkeypatch, sources, defaut):
    soup = BeautifulSoup(CAPTURE, "html.parser")
    if defaut == "vide":
        html = ""
    elif defaut == "sans_time":
        for t in soup.find_all("time"):
            t.decompose()
        html = str(soup)
    elif defaut == "structure":
        # Les mêmes dates survivent, sans conteneur connu ni lien ancêtre.
        html = "<main>" + "".join(str(t) for t in soup.find_all("time")) + "</main>"
    else:
        carte = soup.select_one("article.W1FydW_featured")
        carte.find("h2").clear()
        html = str(soup)
    source = sources["anthropic-newsroom"]
    with pytest.raises(FormatInattendu):
        parser_html_time_liens(html, source)
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({source.url: (html, "text/html")}))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-01"]) == 0
    brut = json.loads((tmp_path / "raw/claude-nouveautes.json").read_text(encoding="utf-8"))
    echecs = [e for e in brut["sources_en_echec"] if e["id"] == source.id]
    assert len(echecs) == 1 and not echecs[0]["partiel"]
    assert echecs[0]["erreur"].startswith("FormatInattendu:")
    assert source.id not in brut["sources_traitees"]
    assert not any(e["source_id"] == source.id for e in brut["nouveautes"])
    assert brut["nouveautes"]  # Les autres sources continuent.
    assert not (tmp_path / "state/claude.json").exists()


def test_capture_reelle_jusqu_au_contenu_des_articles(tmp_path, monkeypatch, sources):
    source = sources["anthropic-newsroom"]
    client = FauxClient({source.url: (CAPTURE, "text/html")})
    monkeypatch.setattr(fetch, "Client", lambda: client)
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-01"]) == 0
    brut = json.loads((tmp_path / "raw/claude-nouveautes.json").read_text(encoding="utf-8"))
    news = [e for e in brut["nouveautes"] if e["source_id"] == source.id]
    assert len(news) == 25  # Trois articles du carrousel sont antérieurs à septembre.
    assert not any(e["id"] == source.id for e in brut["sources_en_echec"])
    assert all("rate limit reset" in e["contenu"] for e in news)
    assert all(client.appels.count(e["url"]) == 1 for e in news)
    assert not (tmp_path / "state/claude.json").exists()
