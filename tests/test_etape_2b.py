"""Étape 2b (01/10/2026) : blog claude.com, pages d'état. Échantillons réels du 2026-10-01, client simulé.

`anthropic-status` (status.claude.com) : la session cloud n'avait pas pu l'atteindre (egress du conteneur) ; l'échantillon
réel du 2026-10-01 (extrait de 3 incidents, dont la panne du 29/09) a été relevé depuis la machine de Sylvain.
"""

import json

import pytest

import fetch
from conftest import FIXTURES, FauxClient
from deltalib.analyseurs import ANALYSEURS, html_notes, rss, statuspage
from deltalib.modeles import FormatInattendu, empreinte_contenu
from deltalib.sources import Source, sources_du_perimetre

BLOG = (FIXTURES / "claude_resources_articles.html").read_text(encoding="utf-8")
INCIDENTS = json.loads((FIXTURES / "status_openai_incidents.json").read_text(encoding="utf-8"))
INCIDENTS_CLAUDE = json.loads((FIXTURES / "status_claude_incidents.json").read_text(encoding="utf-8"))
ID_PANNE_29_09 = "4xvtc2gnq73l"


# --- claude.com/resources/articles (ex-blog, déplacé le 2026-10-07) ----------------------------------------

def test_blog_liste_reelle(sources, client):
    s = sources["claude-blog"]
    r = ANALYSEURS[s.type](s, client)
    assert len(r.elements) == 8 and len({e.id for e in r.elements}) == 8  # 11 cartes : 3 externes ignorées, carrousel dédoublonné
    assert r.plus_ancienne == "2026-09-29"
    premier = r.elements[0]
    assert premier.titre == "Claude now works with Google Docs, Sheets, and Slides"  # carte du carrousel, en tête
    assert premier.date_publication == "2026-10-06" and premier.produit == "claude" and premier.officielle is True
    # l'identifiant garde l'ancienne forme /blog/<slug> (articles déjà vus), l'URL lue est l'adresse finale
    slug = "claude-now-works-in-google-docs-sheets-and-slides"
    assert premier.id == f"https://claude.com/blog/{slug}" and premier.url == f"https://claude.com/resources/articles/{slug}"
    google = next(e for e in r.elements if "Google Docs" in e.titre)
    assert google.date_publication == "2026-10-06" and google.contenu.endswith("Produits : Claude Enterprise")
    dates = {e.id: e.date_publication for e in r.elements}
    assert dates["https://claude.com/blog/claude-code-mods"] == "2026-10-01"
    assert dates["https://claude.com/blog/claude-for-government-is-now-generally-available"] == "2026-09-30"
    assert all(e.date_publication and e.titre and e.url.startswith("https://claude.com/resources/articles/")
               and e.id.startswith("https://claude.com/blog/") for e in r.elements)
    assert not any("anthropic.com" in e.url or "claude.dev" in e.url for e in r.elements)


def test_blog_sans_prefixe_id_l_url_sert_d_identifiant(sources):
    s = Source(**{**sources["claude-blog"].__dict__, "options": {"format": "html_resources_liste"}})
    elements, _ = html_notes.parser_resources_liste(BLOG, s)
    assert all(e.id == e.url for e in elements)


@pytest.mark.parametrize("html", [
    "<html><body><h1>Just a moment...</h1></body></html>",  # défi anti-bot
    '<html><body><a class="x__ResourceCard" href="https://www.anthropic.com/news/x"><h3>T</h3></a></body></html>',  # aucune carte du site
    '<html><body><div class="blog_cms_list"></div></body></html>',  # ancien gabarit Webflow
])
def test_blog_gabarit_change_est_un_echec_explicite(sources, html):
    with pytest.raises(FormatInattendu):
        html_notes.parser_resources_liste(html, sources["claude-blog"])


def test_blog_carte_sans_date_ou_date_illisible(sources):
    sans_titre = BLOG.replace("<h3", "<div", 1).replace("</h3>", "</div>", 1)
    with pytest.raises(FormatInattendu, match="sans titre ou sans date"):
        html_notes.parser_resources_liste(sans_titre, sources["claude-blog"])
    illisible = BLOG.replace("Oct 6, 2026", "Soon", 1)
    with pytest.raises(FormatInattendu, match="date illisible"):
        html_notes.parser_resources_liste(illisible, sources["claude-blog"])


def test_blog_article_reel_texte_principal():
    texte = html_notes.texte_article((FIXTURES / "claude_resources_article_google.html").read_text(encoding="utf-8"))
    assert texte.startswith("Claude now works with Google Docs, Sheets, and Slides") and len(texte) > 1000


def test_blog_passage_lit_le_texte_des_nouveaux_articles(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-30"]) == 0
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    blog = {n["id"]: n for n in brut["nouveautes"] if n["source_id"] == "claude-blog"}
    google = blog["https://claude.com/blog/claude-now-works-in-google-docs-sheets-and-slides"]
    assert google["url"] == "https://claude.com/resources/articles/claude-now-works-in-google-docs-sheets-and-slides"
    assert google["date_publication"] == "2026-10-06" and "Google Workspace" in google["contenu"] and len(google["contenu"]) > 1000
    mods = blog["https://claude.com/blog/claude-code-mods"]  # servi par l'article de repli : le texte est lu, pas le résumé
    assert mods["date_publication"] == "2026-10-01" and len(mods["contenu"]) > 1000
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "claude-blog" and not e["partiel"]]


# --- pages d'état (Statuspage / incident.io) ----------------------------------------------------------------

def test_statuspage_openai_reel(sources, client):
    s = sources["openai-status"]
    r = ANALYSEURS[s.type](s, client)
    assert len(r.elements) == 18 and r.plus_ancienne == "2026-09-13"  # 25 incidents lus, 7 d'impact none ignorés
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
                                   ("anthropic-status", "a_valider", "claude")):
        s = sources[sid]
        assert (s.statut, s.perimetre, s.officielle) == (statut, perimetre, True)
        assert ("Testé le 2026-10-07 : adresse changée" if sid == "claude-blog" else "Testé le 2026-10-01") in s.note
    actives = {s.id for s in sources_du_perimetre(list(sources.values()), "claude")}
    assert {"claude-blog", "anthropic-status"} <= actives
    assert sources["claude-blog"].url == "https://claude.com/resources/articles"
    assert sources["anthropic-status"].url == "https://status.claude.com/api/v2/incidents.json"
    assert "egress" in sources["anthropic-status"].note and "2026-10-01" in sources["anthropic-status"].note


def test_passage_openai_lit_les_incidents(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--depuis", "2026-09-24"]) == 0
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    inc = [n for n in brut["nouveautes"] if n["source_id"] == "openai-status"]
    titres = {n["titre"] for n in inc}
    assert "Issues with Codex" in titres
    assert "Elevated Error Rates on GPT-6 Astra Pro" not in titres, "impact none : ignoré (ignorer_impacts)"
    assert not any(n["empreinte"] for n in inc), "suivre_revisions désactivé : aucun incident n'est suivi par empreinte"
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "openai-status"]


# --- status.claude.com : échantillon réel (extrait de 3 incidents du 2026-10-01) -----------------------------------

def test_statuspage_claude_reel_la_panne_du_29_09_est_lue(sources):
    s = sources["anthropic-status"]
    r = ANALYSEURS[s.type](s, FauxClient())
    par_id = {e.id: e for e in r.elements}
    panne = par_id[f"anthropic-status-{ID_PANNE_29_09}"]
    assert panne.titre == "Elevated errors on claude.ai, Claude Code, Claude Cowork and the Claude API"
    assert panne.date_publication == "2026-09-29" and panne.officielle is True
    assert panne.url == f"https://status.claude.com/incidents/{ID_PANNE_29_09}"
    assert panne.produit == "claude-code", "le nom cite « Claude Code » : produits_par_mot de la source"
    assert panne.contenu.startswith("Impact : major ; statut : resolved ; ouvert le 2026-09-29T") and "résolu le" in panne.contenu
    assert "Composants : " in panne.contenu
    assert r.plus_ancienne == "2026-09-16", "la date la plus ancienne compte aussi l'incident ignoré (détection de trou)"


def test_statuspage_claude_reel_passage_complet(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-16"]) == 0  # l'extrait commence le 16/09
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    ids = {n["id"] for n in brut["nouveautes"] if n["source_id"] == "anthropic-status"}
    assert f"anthropic-status-{ID_PANNE_29_09}" in ids
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "anthropic-status"]


# --- bruit des pages d'état : impact none ignoré, un incident ne remonte qu'à son ouverture -----------------------

def test_incidents_d_impact_none_sont_ignores(sources):
    for sid, donnees, attendus in (("openai-status", INCIDENTS, 7), ("anthropic-status", INCIDENTS_CLAUDE, 1)):
        s = sources[sid]
        assert s.options["ignorer_impacts"] == ["none"]
        elements, _ = statuspage.parser_statuspage(donnees, s)
        nones = [i for i in donnees["incidents"] if i["impact"] == "none"]
        assert len(nones) == attendus
        assert len(elements) == len(donnees["incidents"]) - attendus
        assert not {f"{sid}-{i['id']}" for i in nones} & {e.id for e in elements}


def test_incident_aggrave_arrive_quand_son_impact_n_est_plus_none(sources):
    s = sources["anthropic-status"]
    modifie = json.loads(json.dumps(INCIDENTS_CLAUDE))
    cible = next(i for i in modifie["incidents"] if i["impact"] == "none")
    avant, _ = statuspage.parser_statuspage(modifie, s)
    cible["impact"] = "minor"
    apres, _ = statuspage.parser_statuspage(modifie, s)
    assert f"anthropic-status-{cible['id']}" not in {e.id for e in avant}
    assert f"anthropic-status-{cible['id']}" in {e.id for e in apres}


def test_sans_ignorer_impacts_tout_incident_est_lu(sources):
    s = sources["openai-status"]
    sans = Source(id=s.id, perimetre=s.perimetre, produit=s.produit, type=s.type, url=s.url, statut=s.statut,
                  officielle=True, options={k: v for k, v in s.options.items() if k != "ignorer_impacts"})
    assert len(statuspage.parser_statuspage(INCIDENTS, sans)[0]) == 25


def test_un_incident_ne_remonte_qu_a_son_ouverture(tmp_path, monkeypatch, sources, date_figee):
    for sid in ("openai-status", "anthropic-status"):
        assert sources[sid].options["suivre_revisions"] is False
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    from conftest import ecrire_quotidien
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--depuis", "2026-09-24"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    assert [n for n in brut["nouveautes"] if n["source_id"] == "openai-status"]
    ecrire_quotidien(tmp_path, "openai", brut, "2026-10-01")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--valider", "--date", "2026-10-01"]) == 0
    # un incident déjà vu reçoit une mise à jour : il ne revient pas en révision
    modifie = json.loads(json.dumps(INCIDENTS))
    cible = next(i for i in modifie["incidents"] if i["name"] == "Elevated errors in ChatGPT Space Pages")
    cible["status"] = "resolved"
    cible["resolved_at"] = "2026-10-01T03:00:00Z"
    cible["incident_updates"].insert(0, {"id": "x", "body": "Recovered.", "created_at": "2026-10-01T03:00:00Z", "status": "resolved"})
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({"https://status.openai.com/api/v2/incidents.json": (json.dumps(modifie), "application/json")}))
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    assert not [n for n in brut["nouveautes"] if n["source_id"] == "openai-status"]
