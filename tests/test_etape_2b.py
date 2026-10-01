"""Étape 2b (01/10/2026) : blog claude.com, pages d'état. Échantillons réels du 2026-10-01, client simulé.

`anthropic-status` (status.claude.com) n'a pas d'échantillon : la connexion est refusée par l'egress du conteneur de
développement. Son format n'est donc testé que sur la page d'état d'OpenAI, de même schéma Statuspage.
"""

import json

import pytest

import fetch
from conftest import FIXTURES, FauxClient
from deltalib.analyseurs import ANALYSEURS, html_notes, rss, statuspage
from deltalib.modeles import FormatInattendu, empreinte_contenu
from deltalib.sources import Source, sources_du_perimetre

BLOG = (FIXTURES / "claude_blog.html").read_text(encoding="utf-8")
INCIDENTS = json.loads((FIXTURES / "status_openai_incidents.json").read_text(encoding="utf-8"))


# --- claude.com/blog ----------------------------------------------------------------------------------------

def test_blog_liste_reelle(sources, client):
    s = sources["claude-blog"]
    r = ANALYSEURS[s.type](s, client)
    assert len(r.elements) == 15 and len({e.id for e in r.elements}) == 15
    assert r.plus_ancienne == "2026-09-15"
    premier = r.elements[0]
    assert premier.titre == "Claude for Government is now generally available"
    assert premier.date_publication == "2026-09-30" and premier.produit == "claude" and premier.officielle is True
    assert premier.url == premier.id == "https://claude.com/blog/claude-for-government-is-now-generally-available"
    assert premier.contenu == "Catégorie : Product announcements"
    dates = {e.id: e.date_publication for e in r.elements}
    assert dates["https://claude.com/blog/claude-marketplace"] == "2026-09-23"
    assert dates["https://claude.com/blog/claude-tag-now-supports-personal-connectors-in-channels"] == "2026-09-24"
    assert all(e.date_publication and e.titre and e.url.startswith("https://claude.com/blog/") for e in r.elements)


@pytest.mark.parametrize("html", [
    "<html><body><h1>Just a moment...</h1></body></html>",  # défi anti-bot
    '<html><body><div class="blog_cms_list"></div></body></html>',  # liste vide
])
def test_blog_gabarit_change_est_un_echec_explicite(sources, html):
    with pytest.raises(FormatInattendu):
        html_notes.parser_blog_liste(html, sources["claude-blog"])


def test_blog_carte_sans_date_ou_date_illisible(sources):
    sans_date = BLOG.replace('fs-list-field="date"', 'fs-list-field="autre"', 1)
    with pytest.raises(FormatInattendu, match="titre, lien ou date"):
        html_notes.parser_blog_liste(sans_date, sources["claude-blog"])
    illisible = BLOG.replace("September 30, 2026", "Soon", 1)
    with pytest.raises(FormatInattendu, match="date illisible"):
        html_notes.parser_blog_liste(illisible, sources["claude-blog"])


def test_blog_passage_lit_marketplace_et_tag(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-23"]) == 0
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    blog = {n["url"]: n for n in brut["nouveautes"] if n["source_id"] == "claude-blog"}
    mkt = blog["https://claude.com/blog/claude-marketplace"]
    tag = blog["https://claude.com/blog/claude-tag-now-supports-personal-connectors-in-channels"]
    assert mkt["date_publication"] == "2026-09-23" and "Claude Marketplace" in mkt["contenu"] and len(mkt["contenu"]) > 1000
    assert tag["date_publication"] == "2026-09-24" and "personal connectors" in tag["contenu"].lower()
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "claude-blog" and not e["partiel"]]


# --- pages d'état (Statuspage / incident.io) ----------------------------------------------------------------

def test_statuspage_openai_reel(sources, client):
    s = sources["openai-status"]
    r = ANALYSEURS[s.type](s, client)
    assert len(r.elements) == 25 and r.plus_ancienne == "2026-09-13"
    par_titre = {e.titre: e for e in r.elements}
    codex = par_titre["Issues with Codex"]  # panne du 25/09, 22:58 à 23:54 UTC
    assert codex.produit == "codex" and codex.date_publication == "2026-09-25" and codex.officielle is True
    brut_id = next(i["id"] for i in INCIDENTS["incidents"] if i["name"].strip() == "Issues with Codex")
    assert codex.id == f"openai-status-{brut_id}" and codex.url == f"https://status.openai.com/incidents/{brut_id}"
    assert "Impact : critical ; statut : resolved ; ouvert le 2026-09-25T22:58:48Z ; résolu le 2026-09-25T23:54:41Z" in codex.contenu
    assert par_titre["Elevated errors across ChatGPT, Codex, and the API including the Agents API"].produit == "codex"
    assert par_titre["Elevated Error Rates for ChatGPT across Plus and Pro plans."].produit == "chatgpt"
    assert par_titre["Elevated latency for some API requests"].produit == "chatgpt"  # produit de la source par défaut
    assert [e.date_publication for e in r.elements][0] == "2026-09-30"


def test_statuspage_un_incident_ouvert_est_lu_avec_son_statut(sources, client):
    s = sources["openai-status"]
    r = ANALYSEURS[s.type](s, client)
    ouvert = next(e for e in r.elements if e.titre == "Elevated errors in ChatGPT Space Pages")
    assert "statut : monitoring" in ouvert.contenu and "résolu le" not in ouvert.contenu


def test_statuspage_une_mise_a_jour_change_l_empreinte(sources):
    s = sources["openai-status"]
    avant, _ = statuspage.parser_statuspage(INCIDENTS, s)
    modifie = json.loads(json.dumps(INCIDENTS))
    cible = next(i for i in modifie["incidents"] if i["name"] == "Elevated errors in ChatGPT Space Pages")
    cible["status"] = "resolved"
    cible["resolved_at"] = "2026-10-01T03:00:00Z"
    cible["incident_updates"].insert(0, {"id": "x", "body": "Recovered.", "created_at": "2026-10-01T03:00:00Z",
                                         "status": "resolved"})
    apres, _ = statuspage.parser_statuspage(modifie, s)
    a = next(e for e in avant if e.titre == cible["name"])
    b = next(e for e in apres if e.titre == cible["name"])
    assert a.id == b.id and empreinte_contenu(a.contenu) != empreinte_contenu(b.contenu)
    assert [empreinte_contenu(e.contenu) for e in avant if e.id != a.id] == [empreinte_contenu(e.contenu) for e in apres if e.id != a.id]


def test_statuspage_composants_et_produits_par_mot_synthetique(sources):
    """Échantillon SYNTHÉTIQUE (pas de relevé de status.claude.com) : champ `components` de Statuspage, s'il existe."""
    s = sources["anthropic-status"]
    donnees = {"page": {"url": "https://status.claude.com"}, "incidents": [
        {"id": "abc123", "name": "Elevated errors on Claude Code", "status": "investigating", "impact": "major",
         "created_at": "2026-09-29T10:00:00.000Z", "incident_updates": [], "components": [{"name": "Claude Code"}]}]}
    (e,), plus_ancienne = statuspage.parser_statuspage(donnees, s)
    assert e.produit == "claude-code" and e.url == "https://status.claude.com/incidents/abc123"
    assert e.date_publication == plus_ancienne == "2026-09-29" and "Composants : Claude Code" in e.contenu


@pytest.mark.parametrize("donnees, motif", [
    ([], "pas un objet"),
    ({"page": {}}, "incidents"),
    ({"incidents": []}, "vide"),
    ({"incidents": ["x"]}, "pas un objet"),
    ({"incidents": [{"id": "1", "name": "n", "status": "resolved"}]}, "champs manquants"),
    ({"incidents": [{"id": "1", "name": "n", "status": "resolved", "created_at": "hier"}]}, "illisible"),
    ({"incidents": [{"id": "1", "name": "n", "status": "resolved", "created_at": "2026-09-29T10:00:00Z",
                     "incident_updates": "oups"}]}, "incident_updates"),
])
def test_statuspage_derive_de_format_est_une_erreur(sources, donnees, motif):
    with pytest.raises(FormatInattendu, match=motif):
        statuspage.parser_statuspage(donnees, sources["openai-status"])


def test_statuspage_page_html_a_la_place_du_json(sources):
    s = sources["openai-status"]
    with pytest.raises(FormatInattendu, match="JSON invalide"):
        ANALYSEURS[s.type](s, FauxClient({s.url: ("<html><body>Just a moment...</body></html>", "text/html")}))


def test_statuspage_repli_rss_openai(sources):
    """Le flux `history.rss` (repli documenté) est lu tel quel par l'analyseur RSS existant."""
    base = sources["openai-status"]
    flux = Source(id="openai-status-rss", perimetre="openai", produit="chatgpt", type="rss",
                  url="https://status.openai.com/history.rss", statut="desactive", officielle=True)
    r = rss.analyser(flux, FauxClient())
    assert len(r.elements) == 96 and r.plus_ancienne == "2026-07-07"
    codex = next(e for e in r.elements if e.titre.strip() == "Issues with Codex")
    assert codex.date_publication == "2026-09-25" and "CLI (Operational)" in codex.contenu and "Resolved" in codex.contenu
    assert base.url != flux.url


# --- sources.yaml -------------------------------------------------------------------------------------------

def test_sources_2b_declarees(sources):
    for sid, statut, perimetre in (("claude-blog", "a_valider", "claude"), ("openai-status", "a_valider", "openai"),
                                   ("anthropic-status", "bloque", "claude")):
        s = sources[sid]
        assert (s.statut, s.perimetre, s.officielle) == (statut, perimetre, True) and "Testé le 2026-10-01" in s.note
    actives = {s.id for s in sources_du_perimetre(list(sources.values()), "claude")}
    assert "claude-blog" in actives and "anthropic-status" not in actives, "une source bloquée n'est pas traitée"


def test_passage_openai_lit_les_incidents(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--depuis", "2026-09-24"]) == 0
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    inc = [n for n in brut["nouveautes"] if n["source_id"] == "openai-status"]
    assert {n["titre"] for n in inc} >= {"Issues with Codex", "Elevated Error Rates on GPT-6 Astra Pro"}
    assert all(n["empreinte"] for n in inc), "suivre_revisions : chaque incident porte son empreinte"
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "openai-status"]
