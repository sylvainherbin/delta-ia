"""Étape 2c : pages officielles des dépréciations de modèles (analyseur `annonces_datees`, sources `anthropic-deprecations`
et `openai-deprecations`) et ajouts de la base de référence cités dans la veille (`ajouts_a_citer`).
Échantillons réels du 2026-10-01 (tests/fixtures/deprec_*.md), client simulé, aucun réseau."""

import json

import pytest

import fetch
from conftest import FIXTURES, FauxClient, ecrire_quotidien
from deltalib.analyseurs.html_notes import parser_annonces_datees
from deltalib.kb import catalogue
from deltalib.modeles import ErreurReseau, FormatInattendu

URL_ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/model-deprecations.md"
URL_OPENAI = "https://developers.openai.com/api/docs/deprecations.md"
PAGE_ANTHROPIC = (FIXTURES / "deprec_anthropic.md").read_text(encoding="utf-8")
PAGE_OPENAI = (FIXTURES / "deprec_openai.md").read_text(encoding="utf-8")
ID_SONNET = "anthropic-deprecations-2026-09-30-claude-sonnet-4-5-model"
ID_TABLEAU = "anthropic-deprecations-statut-modeles"


def lire(p):
    return json.loads(p.read_text(encoding="utf-8"))


def dossiers(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "raw").mkdir()


def passage(tmp_path, monkeypatch, perimetre, pannes=None, *args):
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient(pannes or {}))
    code = fetch.main(["--racine", str(tmp_path), "--perimetre", perimetre, *args])
    return code, lire(tmp_path / "raw" / f"{perimetre}-nouveautes.json")


def deprec(brut, source):
    return [n for n in brut["nouveautes"] if n["source_id"] == source]


def valider(tmp_path, monkeypatch, perimetre, brut, jour):
    ecrire_quotidien(tmp_path, perimetre, brut, jour)
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", perimetre, "--valider", "--date", jour]) == 0


# --- sources déclarées -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sid, perimetre, produit, url", [
    ("anthropic-deprecations", "claude", "claude", URL_ANTHROPIC),
    ("openai-deprecations", "openai", "codex", URL_OPENAI)])
def test_sources_declarees(sources, sid, perimetre, produit, url):
    s = sources[sid]
    assert (s.perimetre, s.produit, s.url) == (perimetre, produit, url)
    assert s.statut == "a_valider" and s.officielle is True
    assert s.options["format"] == "annonces_datees" and s.options["suivre_revisions"] is True
    assert "Testé le 2026-10-01" in s.note and "200, text/markdown" in s.note, "date, statut HTTP, type de la page dans la note"


# --- analyseur sur les pages réelles -----------------------------------------------------------------------------

def test_anthropic_tableau_preavis_et_une_annonce_par_titre_date(sources):
    els = {e.id: e for e in parser_annonces_datees(PAGE_ANTHROPIC, sources["anthropic-deprecations"])}
    assert len(els) == 12 and all(e.officielle and e.source_id == "anthropic-deprecations" for e in els.values())
    assert els[ID_TABLEAU].date_publication is None and "claude-haiku-4-5-20251001" in els[ID_TABLEAU].contenu
    assert "Not sooner than October 15, 2026" in els[ID_TABLEAU].contenu
    assert els["anthropic-deprecations-preavis"].date_publication is None and "60 days" in els["anthropic-deprecations-preavis"].contenu
    e = els[ID_SONNET]
    assert e.date_publication == "2026-09-30" and "November 30, 2026" in e.contenu and "claude-sonnet-5-5" in e.contenu
    assert e.url == "https://platform.claude.com/docs/en/about-claude/model-deprecations" and e.produit == "claude"
    opus = els["anthropic-deprecations-2026-06-05-claude-opus-4-1-model"]
    assert "This model was retired August 5, 2026" in opus.contenu, "la note d'état fait partie du corps suivi"
    # les sections hors historique (paramètres d'API, bonnes pratiques) ne sont pas des annonces
    assert not any("temperature" in x.contenu for x in els.values())


def test_openai_annonces_en_attente_dont_une_sans_date_et_passees(sources):
    els = {e.id: e for e in parser_annonces_datees(PAGE_OPENAI, sources["openai-deprecations"])}
    assert len(els) == 36 and len({e.titre for e in els.values()}) == 36
    cyber = els["openai-deprecations-2026-09-11-gpt-5-4-cyber"]
    assert cyber.date_publication == "2026-09-11" and "October 1, 2026" in cyber.contenu
    sans_date = els["openai-deprecations-update-to-openai-s-self-serve-fine-tuning"]
    assert sans_date.date_publication is None, "annonce en attente sans date : null, jamais devinée"
    assert [e.date_publication for e in els.values() if e.date_publication is None] == [None, None]  # préavis + fine-tuning
    # deux annonces du même jour : deux éléments
    assert {i for i in els if i.startswith("openai-deprecations-2026-04-22-")} == {
        "openai-deprecations-2026-04-22-legacy-gpt-model-snapshots", "openai-deprecations-2026-04-22-legacy-gpt-model-snapshots-july-2026-shutdown"}
    # les sous-titres `####` font partie de l'annonce, la section de définitions « Plain-text aliases » n'en est pas une
    assert "Fine-tunes endpoint" in els["openai-deprecations-2023-08-22-fine-tunes-endpoint"].contenu
    assert not any(i.endswith("plain-text-aliases") for i in els)
    assert "6 months" in els["openai-deprecations-preavis"].contenu


def test_annonces_datees_gabarit_change_ne_donne_jamais_un_vide_silencieux(sources):
    s = sources["anthropic-deprecations"]
    with pytest.raises(FormatInattendu, match="introuvable"):
        parser_annonces_datees(PAGE_ANTHROPIC.replace("## Deprecation history", "## Historique"), s)
    with pytest.raises(FormatInattendu, match="introuvable"):
        parser_annonces_datees(PAGE_ANTHROPIC.replace("## Model status", "## État"), s)
    with pytest.raises(FormatInattendu, match="date invalide"):
        parser_annonces_datees(PAGE_ANTHROPIC.replace("### 2026-09-30:", "### 2026-13-45:"), s)
    # historique vidé de ses annonces datées et sections suivies retirées : rien à rapporter, donc une erreur
    seul = type(s)(**{**s.__dict__, "options": {"parents": s.options["parents"], "nom": "x"}})
    sans_annonce = PAGE_ANTHROPIC.replace("### ", "#### ")
    with pytest.raises(FormatInattendu, match="aucune annonce"):
        parser_annonces_datees(sans_annonce, seul)
    vide = type(s)(**{**s.__dict__, "options": {"nom": "x"}})
    with pytest.raises(FormatInattendu, match="options.parents"):
        parser_annonces_datees(PAGE_ANTHROPIC, vide)


def test_parent_en_attente_vide_n_est_pas_une_erreur(sources):
    """Plus aucune annonce en attente chez OpenAI est un état normal, tant que la page garde sa structure."""
    page = PAGE_OPENAI.replace("### 2026-09-11:", "### Past 2026-09-11:")
    debut = page.index("### 2026-08-26")
    fin = page.index("## Past deprecations")
    page = page[:debut] + "\n" + page[fin:]
    els = parser_annonces_datees(page, sources["openai-deprecations"])
    assert not [e for e in els if e.id.startswith("openai-deprecations-2026-08")] and len(els) > 20


# --- de bout en bout : état, révisions, page bloquée -------------------------------------------------------------

def test_premier_passage_puis_page_suivie_sans_changement(tmp_path, monkeypatch, date_figee):
    dossiers(tmp_path)
    _, brut = passage(tmp_path, monkeypatch, "claude", None, "--depuis", "2026-09-20")
    n = {e["id"]: e for e in deprec(brut, "anthropic-deprecations")}
    # dates >= 2026-09-20 et éléments non datés : l'annonce du 30/09, le tableau d'état, le préavis
    assert set(n) == {ID_SONNET, ID_TABLEAU, "anthropic-deprecations-preavis"} and not any(e["revision"] for e in n.values())
    anciens = [i for i in brut["ignores"] if i.startswith("anthropic-deprecations-")]
    assert len(anciens) == 9 and all(brut["empreintes"][i] for i in anciens), "annonces anciennes ignorées, empreinte gardée"
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "anthropic-deprecations"]
    valider(tmp_path, monkeypatch, "claude", brut, "2026-09-26")
    vus = lire(tmp_path / "state" / "claude.json")["vus"]
    assert ID_SONNET in vus and ID_TABLEAU in vus and set(anciens) <= set(vus) and vus[ID_SONNET]["empreinte"]
    _, brut2 = passage(tmp_path, monkeypatch, "claude")
    assert deprec(brut2, "anthropic-deprecations") == [], "page inchangée : rien"


def test_section_modifiee_et_nouvelle_annonce(tmp_path, monkeypatch, date_figee):
    dossiers(tmp_path)
    _, brut = passage(tmp_path, monkeypatch, "claude", None, "--depuis", "2026-09-20")
    valider(tmp_path, monkeypatch, "claude", brut, "2026-09-26")
    # 1) la date de retrait de Sonnet 4.5 change, le tableau avance : deux révisions, pas de nouvel élément
    page = PAGE_ANTHROPIC.replace("November 30, 2026", "December 15, 2026")
    assert page != PAGE_ANTHROPIC
    _, brut2 = passage(tmp_path, monkeypatch, "claude", {URL_ANTHROPIC: (page, "text/markdown")})
    rev = {e["id"]: e for e in deprec(brut2, "anthropic-deprecations")}
    assert set(rev) == {ID_SONNET, ID_TABLEAU} and all(e["revision"] for e in rev.values())
    assert "December 15, 2026" in rev[ID_SONNET]["contenu"]
    # 2) une note « retired » ajoutée à une annonce ancienne ignorée au premier passage : révision elle aussi
    page2 = PAGE_ANTHROPIC.replace("These models were retired June 15, 2026.", "These models were retired June 16, 2026.")
    assert page2 != PAGE_ANTHROPIC
    _, brut3 = passage(tmp_path, monkeypatch, "claude", {URL_ANTHROPIC: (page2, "text/markdown")})
    assert [(e["id"], e["revision"]) for e in deprec(brut3, "anthropic-deprecations")] == [
        ("anthropic-deprecations-2026-04-14-claude-sonnet-4-and-claude-opus-4-models", True)]
    # 3) une nouvelle annonce : élément nouveau (revision faux), titre et date lus dans la page
    nouvelle = ("### 2026-10-01: Claude Haiku 4.5 model\n\nOn October 1, 2026, Anthropic notified developers.\n\n"
                "| Retirement date | Deprecated model | Recommended replacement |\n| --- | --- | --- |\n"
                "| December 1, 2026 | `claude-haiku-4-5-20251001` | `claude-sonnet-5-5` |\n\n")
    page3 = PAGE_ANTHROPIC.replace("### 2026-09-30:", nouvelle + "### 2026-09-30:", 1)
    _, brut4 = passage(tmp_path, monkeypatch, "claude", {URL_ANTHROPIC: (page3, "text/markdown")})
    (e,) = deprec(brut4, "anthropic-deprecations")
    assert e["id"] == "anthropic-deprecations-2026-10-01-claude-haiku-4-5-model" and not e["revision"]
    assert e["date_publication"] == "2026-10-01" and "December 1, 2026" in e["contenu"] and e["officielle"]


def test_page_bloquee_va_dans_sources_en_echec(tmp_path, monkeypatch, date_figee):
    dossiers(tmp_path)
    pannes = {URL_ANTHROPIC: ErreurReseau("HTTP 403 pour " + URL_ANTHROPIC)}
    code, brut = passage(tmp_path, monkeypatch, "claude", pannes)
    assert code == 0
    (echec,) = [e for e in brut["sources_en_echec"] if e["id"] == "anthropic-deprecations"]
    assert "403" in echec["erreur"] and echec["partiel"] is False and echec["url"] == URL_ANTHROPIC
    assert "anthropic-deprecations" not in brut["sources_traitees"]
    assert not deprec(brut, "anthropic-deprecations") and not [i for i in brut["ignores"] if i.startswith("anthropic-deprecations")]
    code, brut = passage(tmp_path, monkeypatch, "openai", {URL_OPENAI: ErreurReseau("HTTP 403 pour " + URL_OPENAI)})
    assert [e["id"] for e in brut["sources_en_echec"] if e["id"] == "openai-deprecations"] == ["openai-deprecations"]


def test_page_au_format_inattendu_va_dans_sources_en_echec(tmp_path, monkeypatch, date_figee):
    dossiers(tmp_path)
    html = "<!DOCTYPE html><html><head><title>Model deprecations</title></head><body>app</body></html>"
    _, brut = passage(tmp_path, monkeypatch, "claude", {URL_ANTHROPIC: (html, "text/html")})
    (echec,) = [e for e in brut["sources_en_echec"] if e["id"] == "anthropic-deprecations"]
    assert "FormatInattendu" in echec["erreur"] and "HTML" in echec["erreur"]
    _, brut = passage(tmp_path, monkeypatch, "openai", {URL_OPENAI: (PAGE_OPENAI.replace("## Upcoming deprecations", "## À venir"), "text/markdown")})
    (echec,) = [e for e in brut["sources_en_echec"] if e["id"] == "openai-deprecations"]
    assert "FormatInattendu" in echec["erreur"] and "introuvable" in echec["erreur"]


def test_openai_premier_passage_et_amorcage_complet_avec_depuis(tmp_path, monkeypatch, date_figee):
    dossiers(tmp_path)
    _, brut = passage(tmp_path, monkeypatch, "openai", None, "--depuis", "2026-09-01")
    n = {e["id"]: e for e in deprec(brut, "openai-deprecations")}
    assert set(n) == {"openai-deprecations-2026-09-11-gpt-5-4-cyber", "openai-deprecations-preavis",
                      "openai-deprecations-update-to-openai-s-self-serve-fine-tuning"}
    _, brut = passage(tmp_path, monkeypatch, "openai", None, "--depuis", "2026-06-01")
    n = {e["id"]: e for e in deprec(brut, "openai-deprecations")}
    assert "openai-deprecations-2026-06-11-gpt-5-and-o3-model-deprecations" in n and "openai-deprecations-2026-05-08-gpt-5-2-chat-latest-and-gpt-5-3-chat-latest-model-snapshots" not in n


# --- ajouts de la base de référence ------------------------------------------------------------------------------

def test_ajouts_a_citer_unite():
    modif = {"ajoutees": ["b", "a", "c"], "usage_modifie": ["d"]}
    assert catalogue.ajouts_a_citer(modif, ["c"], True) == ["a", "b"], "triés, sans les ids déjà cités par sujet_d71, sans les usages modifiés"
    assert catalogue.ajouts_a_citer({"ajoutees": []}, [], True) == [] and catalogue.ajouts_a_citer({}, [], True) == []
    assert catalogue.ajouts_a_citer(modif, [], False) == [], "création initiale de la base : pas une nouveauté"


def modifs_kb(tmp_path, perimetre="claude"):
    return lire(tmp_path / "raw" / "kb" / f"{perimetre}-modifications.json")


NOUVEAUX = ("\n### `monReglageDeTest`\n\nType : string. Nouveau réglage de test sans autre particularité.\n"
            "\n### `billing`\n\nBilling and subscription settings.\n")


def test_ajout_cite_dans_le_fichier_de_modifications_et_a_l_ecran(tmp_path, monkeypatch, capsys):
    from test_kb import YAML, lancer_kb, lire as lire_page
    (tmp_path / "sources.yaml").write_text(YAML, encoding="utf-8")
    url = "https://code.claude.com/docs/en/settings-reference.md"
    assert lancer_kb(tmp_path, monkeypatch, None, "claude-code") == 0
    assert modifs_kb(tmp_path)["ajouts_a_citer"] == [], "premier import : base vide, rien à citer"
    assert "AJOUTS BASE" not in capsys.readouterr().out
    # une page de réglages gagne deux entrées : l'une sans rapport avec D71, l'autre qui y touche
    page = lire_page("cc_settings.md")
    page = page.replace("## Enterprise and managed settings", NOUVEAUX + "\n## Enterprise and managed settings", 1)
    assert lancer_kb(tmp_path, monkeypatch, {url: page}, "claude-code") == 0
    m = modifs_kb(tmp_path)
    assert len(m["ajoutees"]) == 2
    cite = [i for i in m["ajoutees"] if "monreglagedetest" in i.lower()]
    d71 = [i for i in m["ajoutees"] if "billing" in i.lower()]
    assert len(cite) == 1 and len(d71) == 1
    assert m["ajouts_a_citer"] == cite, "l'ajout hors sujet D71 est à citer ; celui de sujet_d71 est déjà cité avec l'impact de D71"
    assert m["sujet_d71"] == d71 and not set(m["ajouts_a_citer"]) & set(m["sujet_d71"])
    sortie = capsys.readouterr().out
    assert f"+ AJOUTS BASE claude : {cite[0]}" in sortie and "~ SUJET D71 claude" in sortie


def test_aucun_ajout_rien_a_citer(tmp_path, monkeypatch, capsys):
    from test_kb import YAML, lancer_kb
    (tmp_path / "sources.yaml").write_text(YAML, encoding="utf-8")
    assert lancer_kb(tmp_path, monkeypatch, None, "claude-code") == 0
    capsys.readouterr()
    assert lancer_kb(tmp_path, monkeypatch, None, "claude-code") == 0  # deuxième passage identique
    m = modifs_kb(tmp_path)
    assert m["ajoutees"] == [] and m["ajouts_a_citer"] == [] and m["sujet_d71"] == []
    assert "AJOUTS BASE" not in capsys.readouterr().out


@pytest.mark.parametrize("fichier, perimetre", [(".claude/skills/delta/SKILL.md", "claude"), (".agents/skills/delta/SKILL.md", "openai"),
                                                 ("prompts/codex-delta.md", "openai")])
def test_les_skills_citent_ajouts_et_depreciations(fichier, perimetre):
    from conftest import RACINE
    texte = (RACINE / fichier).read_text(encoding="utf-8")
    assert f"chaque id de la liste `ajouts_a_citer` de `raw/kb/{perimetre}-modifications.json`" in texte
    assert "`+ AJOUTS BASE`" in texte and "sans jugement" in texte and "hors `sujet_d71`" in texte
    assert "Liste absente ou vide : rien à citer" in texte
    source = "anthropic-deprecations" if perimetre == "claude" else "openai-deprecations"
    assert f"`{source}`" in texte and "`type: depreciation`" in texte and "Dépréciations (étape 2c)" in texte
