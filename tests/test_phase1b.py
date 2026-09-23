"""Phase 1b : identifiants natifs (D1), produit par entrée (D2), non datés (D3), trous et pagination (D4), révisions."""

import json

import pytest

import fetch
from conftest import FIXTURES, FauxClient, ecrire_quotidien

JOUR = __import__("datetime").date.today().isoformat()
from deltalib.analyseurs import github_changelog, github_releases, json_changelog, rss
from deltalib.etat import detecter
from deltalib.passage import detecter_trou, recuperer
from deltalib.sources import sources_du_perimetre


# --- D1 : la clé native, pas le titre -----------------------------------------------------------------------

def test_d1_titre_modifie_meme_identifiant(sources, fixture_texte):
    s = sources["openai-changelog-general"]
    d = json.loads(fixture_texte("oa_general.json"))
    avant = json_changelog.parser_json(d, s)[0]
    d["items"][0]["title"] = "Titre réécrit par l'éditeur"
    apres = json_changelog.parser_json(d, s)[0]
    assert avant.id == apres.id == "oa-codex/2026-09-22-gpt-6-sol-luna" and avant.titre != apres.titre

    texte = fixture_texte("cc_changelog.md").replace("## 2.1.280", "## 2.1.280", 1)
    a = github_changelog.parser_changelog(texte, sources["claude-code-changelog"])[0]
    b = github_changelog.parser_changelog(texte.replace("Added Claude Opus 5.5", "Titre changé"), sources["claude-code-changelog"])[0]
    assert a.id == b.id == "claude-code-2.1.280"


def test_d1_entree_commune_general_et_codex_app_donne_un_seul_element(sources, client):
    s = [sources["openai-changelog-general"], sources["openai-changelog-codex-app"]]
    elements, echecs, traitees, _ = recuperer(s, client)
    commun = [e for e in elements if e.id == "oa-codex/2026-08-20-app"]
    assert len(commun) == 2 and {e.source_id for e in commun} == {"openai-changelog-general", "openai-changelog-codex-app"}
    nouveautes, ignores = detecter(elements, {"vus": {}}, None)
    assert [e.id for e in nouveautes].count("oa-codex/2026-08-20-app") == 1
    assert len(nouveautes) == len({e.id for e in elements})


def test_d1_identifiants_rss_atom(sources, fixture_texte):
    s = sources["openai-news"]
    s.options = {}
    e = rss.parser_flux(fixture_texte("openai_news.xml"), s)[0][0]
    assert e.id == "https://openai.com/index/openai-extends-cyber-access-to-ukraine-for-civilian-defense"  # guid
    e = rss.parser_flux(fixture_texte("simonw.atom"), sources["simon-willison"])[0][0]
    assert e.id == "https://simonwillison.net/2026/Sep/23/bof-agentic-engineering/"  # <id> Atom
    sans_guid = "<rss><channel><item><title>t</title><link>https://x.test/a</link></item></channel></rss>"
    assert rss.parser_flux(sans_guid, sources["import-ai"])[0][0].id == "https://x.test/a"


def test_d1_identifiant_release_et_notes(sources, client):
    r = github_releases.analyser(sources["codex-cli-releases"], client)
    assert r.elements[0].id == "rust-v0.156.1"
    from deltalib.analyseurs import html_notes
    r = html_notes.analyser(sources["claude-platform-notes"], client)
    assert [e.id for e in r.elements] == ["claude-platform-notes-2026-09-22", "claude-platform-notes-2026-09-18", "claude-platform-notes-2026-09-14"]


# --- D2 : produit par entrée dans general.json ---------------------------------------------------------------

def test_d2_produit_par_entree(sources, client):
    r = json_changelog.analyser(sources["openai-changelog-general"], client)
    produits = {e.id: e.produit for e in r.elements}
    assert produits["oa-codex/2026-09-22-gpt-6-sol-luna"] == "codex"          # « Codex » et « ChatGPT » : codex l'emporte
    assert produits["oa-codex/2026-09-14-codex-spark-deprecation"] == "codex"
    assert produits["oa-codex/2026-09-14-gpt-55-retirement"] == "codex"       # « ChatGPT » et « Codex » dans le titre
    assert produits["oa-codex/2026-08-20-app"] == "codex"                     # « codex-app » dans les sujets
    assert produits["oa-codex/2026-07-29"] == "chatgpt"  # « Sign in with ChatGPT (beta) », sans « codex »
    # D2bis : sans « chatgpt » ni « codex », c'est le changelog Codex, donc codex
    d = json.loads((FIXTURES / "oa_general.json").read_text())
    d["items"][0]["title"] = "Best of N"; d["items"][0]["topics"] = ["general"]
    assert json_changelog.parser_json(d, sources["openai-changelog-general"])[0].produit == "codex"
    # les autres flux gardent le produit de la source
    r = json_changelog.analyser(sources["openai-changelog-ios"], client)
    assert {e.produit for e in r.elements} == {"chatgpt"}


# --- D3 : non datés ---------------------------------------------------------------------------------------------

def test_d3_changelog_versions_non_datees(sources, client, fixture_texte):
    """Une version non datée plus récente que la plus ancienne datée est une nouveauté ; plus ancienne : historique."""
    s = sources["claude-code-changelog"]
    texte = fixture_texte("cc_changelog.md")
    texte = texte.replace("# Changelog\n", "# Changelog\n\n## 2.1.281\n\n- Version publiée dans le changelog avant la release GitHub\n", 1)
    texte += "\n## 0.2.21\n\n- Ancienne version, sans release datée\n"
    r = github_changelog.analyser(s, FauxClient({s.url: (texte, "text/plain")}))
    versions = {e.version: e.date_publication for e in r.elements}
    assert versions["2.1.281"] is None and "0.2.21" not in versions
    assert r.ignores == ["claude-code-0.2.21"]
    nouveautes, ignores = detecter(r.elements, {"vus": {}}, __import__("datetime").date(2026, 9, 20))
    assert "claude-code-2.1.281" in [e.id for e in nouveautes]


def test_d3_element_non_date_jamais_ignore_par_la_fenetre(tmp_path, monkeypatch, date_figee, sources):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    url = sources["anthropic-newsroom"].url
    html = (FIXTURES / "anthropic_news.html").read_text().replace("Aug 27, 2026", "date illisible")
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({url: (html, "text/html")}))
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-20"])
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    non_dates = [e for e in brut["nouveautes"] if e["date_publication"] is None]
    assert len(non_dates) == 1 and non_dates[0]["titre"] == "Previewing the Model Hardware Standard"


# --- D4 : trous et pagination ---------------------------------------------------------------------------------

def test_d4_trou_possible_signale_en_partiel(sources, client):
    s = [sources["claude-code-changelog"]]
    _, echecs, _, _ = recuperer(s, client, borne="2026-08-24")
    assert [(e.id, e.erreur, e.partiel) for e in echecs] == [("claude-code-changelog", "trou possible entre 2026-08-24 et 2026-09-18", True)]
    _, echecs, _, _ = recuperer(s, client, borne="2026-09-18")
    assert echecs == []
    _, echecs, _, _ = recuperer(s, client, borne=None)
    assert echecs == []


def test_d4_pagination_adaptative(sources):
    s = sources["codex-cli-releases"]
    base = s.url
    # borne atteinte dès la première page : un seul appel de liste
    c = FauxClient(); github_releases.analyser(s, c, borne="2026-09-23")
    assert [u for u in c.appels if "&page=" in u] == []
    # borne la veille : la page 1 (tout au 23) ne suffit pas, la page 2 (22) oui
    c = FauxClient(); r = github_releases.analyser(s, c, borne="2026-09-22")
    assert [u for u in c.appels if "&page=" in u] == [base + "&page=2"]
    assert [e.version for e in r.elements] == ["0.156.1", "0.156.0"] and r.plus_ancienne == "2026-09-22"
    # borne lointaine : pages 2, 3, puis page 4 vide = fin de l'historique ; trou signalé
    c = FauxClient(); r = github_releases.analyser(s, c, borne="2026-08-24")
    assert [u for u in c.appels if "&page=" in u] == [base + "&page=2", base + "&page=3", base + "&page=4"]
    assert detecter_trou(r, "2026-08-24") == "trou possible entre 2026-08-24 et 2026-09-22"


def test_d4_pagination_s_arrete_a_quatre_pages(sources):
    s = sources["codex-cli-releases"]
    p3 = (FIXTURES / "codex_releases_p3.json").read_text()
    c = FauxClient({s.url + "&page=4": (p3, "application/json"), s.url + "&page=5": (p3, "application/json")})
    r = github_releases.analyser(s, c, borne="2026-01-01")
    assert len([u for u in c.appels if "&page=" in u]) == 3  # pages 2, 3, 4 : jamais la 5e
    assert detecter_trou(r, "2026-01-01") == "trou possible entre 2026-01-01 et 2026-09-22"


def test_d4_borne_vient_de_l_etat(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    assert brut["borne"] == "2026-08-24"
    ecrire_quotidien(tmp_path, "openai", brut, JOUR)
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--valider"])
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    assert brut["borne"] == __import__("datetime").date.today().isoformat()  # date du dernier --valider


# --- suivre_revisions -----------------------------------------------------------------------------------------

def test_suivre_revisions_de_bout_en_bout(tmp_path, monkeypatch, date_figee, sources):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    url = sources["claude-apps-notes"].url
    original = (FIXTURES / "claude_apps.md").read_text()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    suivis = [e for e in brut["nouveautes"] if e["source_id"] in ("claude-apps-notes", "claude-platform-notes")]
    assert suivis and all(e["empreinte"] for e in suivis)
    assert all(e["empreinte"] is None for e in brut["nouveautes"] if e["source_id"] == "claude-code-changelog")
    ecrire_quotidien(tmp_path, "claude", brut, JOUR)
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider"])
    etat = json.loads((tmp_path / "state" / "claude.json").read_text())
    assert etat["vus"]["claude-apps-notes-2026-09-22"]["empreinte"]
    # contenu inchangé : rien
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    assert json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())["nouveautes"] == []
    # l'éditeur complète l'entrée du 22 septembre : elle revient, marquée révision, même identifiant
    modifie = original.replace("costs 40% less to run than Opus 5.", "costs 40% less to run than Opus 5. Correction ajoutée.")
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({url: (modifie, "text/markdown")}))
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    assert [(e["id"], e["revision"]) for e in brut["nouveautes"]] == [("claude-apps-notes-2026-09-22", True)]
    ecrire_quotidien(tmp_path, "claude", brut, JOUR)
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider"])
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    assert json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())["nouveautes"] == []


# --- D12 : horizon d'un flux filtré -----------------------------------------------------------------------

def test_d12_plus_ancienne_sur_le_flux_entier(sources, client, fixture_texte):
    s = sources["openai-news"]
    r = rss.analyser(s, client)
    elements_filtres = r.elements
    tous, ancienne_flux = rss.parser_flux(fixture_texte("openai_news.xml"), type(s)(**{**s.__dict__, "options": {}}))
    assert len(elements_filtres) < len(tous)
    assert r.plus_ancienne == ancienne_flux == min(e.date_publication for e in tous)
    assert r.plus_ancienne < min(e.date_publication for e in elements_filtres)
    # sans ce calcul, la borne comparée aux seuls éléments filtrés signalerait un faux trou
    assert detecter_trou(r, ancienne_flux) is None
