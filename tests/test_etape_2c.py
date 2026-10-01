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


TITRE_ETAT_INITIAL = "État initial des dépréciations OpenAI en cours"
ID_CYBER = "openai-deprecations-2026-09-11-gpt-5-4-cyber"


def test_openai_premier_passage_avec_depuis_regroupe_en_un_element(tmp_path, monkeypatch, date_figee):
    dossiers(tmp_path)
    _, brut = passage(tmp_path, monkeypatch, "openai", None, "--depuis", "2026-09-01")
    (etat,) = deprec(brut, "openai-deprecations")
    assert etat["titre"] == TITRE_ETAT_INITIAL
    assert {i for i in brut["ignores"] if i.startswith("openai-deprecations-")} >= {ID_CYBER, "openai-deprecations-preavis"}
    assert "GPT-5.4-Cyber" in etat["contenu"] and "2026-06-11" not in etat["contenu"]
    _, brut = passage(tmp_path, monkeypatch, "openai", None, "--depuis", "2026-06-01")
    (etat,) = deprec(brut, "openai-deprecations")
    assert "GPT-5 and o3 model deprecations" in etat["contenu"] and "gpt-5.2-chat-latest" not in etat["contenu"]


# --- étape 2c, décision A : amorcage_jours par source, état initial en un seul élément ---------------------------

@pytest.fixture
def jour_2c(monkeypatch):
    """Les échantillons datent du 2026-10-01 : le jour du passage est figé là, pas au 23/09 de date_figee."""
    import deltalib.passage as ps
    from datetime import date
    monkeypatch.setattr(ps, "aujourd_hui", lambda: date(2026, 10, 1))


def etat_non_vide(tmp_path):
    """L'état du périmètre existe déjà (une autre source y a des traces) : openai-deprecations est une source nouvelle (D30)."""
    from deltalib.etat import ecrire_json
    dossiers(tmp_path)
    ecrire_json(tmp_path / "state" / "openai.json", {"version": 1, "maj_le": "2026-09-30T10:00:00+00:00",
                                                       "vus": {"rust-v0.156.1": {"source_id": "codex-cli-releases"}}})


def test_option_amorcage_jours_lue_et_defaut_inchange(sources):
    assert sources["openai-deprecations"].options["amorcage_jours"] == 120
    assert sources["openai-deprecations"].options["etat_initial"] == TITRE_ETAT_INITIAL
    assert "amorcage_jours" not in sources["anthropic-deprecations"].options and "etat_initial" not in sources["anthropic-deprecations"].options
    assert [s.id for s in sources.values() if "amorcage_jours" in s.options] == ["openai-deprecations"]


def test_fenetre_amorcage_defaut_j_moins_7_et_option_et_depuis(sources):
    from datetime import date
    from deltalib.passage import fenetre_amorcage, FENETRE_AMORCAGE_SOURCE_JOURS
    j = date(2026, 10, 1)
    assert FENETRE_AMORCAGE_SOURCE_JOURS == 7
    assert fenetre_amorcage(sources["anthropic-deprecations"], j, None) == date(2026, 9, 24), "défaut J-7 inchangé"
    assert fenetre_amorcage(sources["releasebot-chatgpt"], j, None) == date(2026, 9, 24)
    assert fenetre_amorcage(sources["openai-deprecations"], j, None) == date(2026, 6, 3), "120 jours"
    assert fenetre_amorcage(sources["openai-deprecations"], j, date(2026, 9, 1)) == date(2026, 9, 1), "--depuis prime"


def test_source_nouvelle_avec_amorcage_jours_arrive_en_un_seul_element(tmp_path, monkeypatch, jour_2c):
    etat_non_vide(tmp_path)
    _, brut = passage(tmp_path, monkeypatch, "openai")
    assert "openai-deprecations" in brut["sources_amorcees"]
    (etat,) = deprec(brut, "openai-deprecations")
    assert etat["titre"] == TITRE_ETAT_INITIAL and etat["date_publication"] is None and etat["officielle"]
    lignes = [l for l in etat["contenu"].splitlines() if l.startswith("- ")]
    # annonces ouvertes des 120 derniers jours (03/06 et après) + préavis et mise à jour fine-tuning (non datés)
    assert len(lignes) == 9 and any("GPT-5.4-Cyber" in l for l in lignes) and any("Agent Builder" in l for l in lignes)
    assert not any("gpt-5.2-chat-latest" in l for l in lignes), "plus ancien que 120 jours : ignoré"
    ids = {i for i in brut["ignores"] if i.startswith("openai-deprecations-")}
    assert ID_CYBER in ids and "openai-deprecations-preavis" in ids and len(ids) > 9, "les annonces plus anciennes vont aussi dans ignores"
    assert all(brut["empreintes"].get(i) for i in (ID_CYBER, "openai-deprecations-preavis")), "tenues par empreinte, page par page"
    # la source garde son état : valider puis une annonce modifiée revient seule, en révision
    valider(tmp_path, monkeypatch, "openai", brut, "2026-10-01")
    _, brut2 = passage(tmp_path, monkeypatch, "openai")
    assert not deprec(brut2, "openai-deprecations")
    page = PAGE_OPENAI.replace("will be removed from the API on October 1, 2026", "will be removed from the API on October 15, 2026")
    assert page != PAGE_OPENAI
    _, brut3 = passage(tmp_path, monkeypatch, "openai", {URL_OPENAI: (page, "text/markdown")})
    assert [(n["id"], n["revision"]) for n in deprec(brut3, "openai-deprecations")] == [(ID_CYBER, True)]


def test_autre_source_nouvelle_garde_la_fenetre_j_moins_7(tmp_path, monkeypatch, jour_2c):
    etat_non_vide(tmp_path)
    _, brut = passage(tmp_path, monkeypatch, "claude")  # état claude vide : premier passage du périmètre
    from deltalib.etat import ecrire_json
    ecrire_json(tmp_path / "state" / "claude.json", {"version": 1, "maj_le": "2026-09-30T10:00:00+00:00",
                                                       "vus": {"claude-code-2.1.281": {"source_id": "claude-code-changelog"}}})
    _, brut = passage(tmp_path, monkeypatch, "claude")
    assert "anthropic-deprecations" in brut["sources_amorcees"]
    datees = [n for n in deprec(brut, "anthropic-deprecations") if n["date_publication"]]
    assert [n["id"] for n in datees] == [ID_SONNET], "seule l'annonce des 7 derniers jours arrive ; pas d'état initial regroupé"
    assert not [n for n in brut["nouveautes"] if n["titre"].startswith("État initial des dépréciations")]


def test_premier_passage_du_perimetre_la_source_garde_sa_propre_fenetre(tmp_path, monkeypatch, jour_2c):
    dossiers(tmp_path)  # état openai vide : fenêtre de 30 jours pour le périmètre, 120 pour openai-deprecations
    _, brut = passage(tmp_path, monkeypatch, "openai")
    (etat,) = deprec(brut, "openai-deprecations")
    assert "GPT-5 and o3 model deprecations" in etat["contenu"], "11/06 : hors des 30 jours du périmètre, dans les 120 de la source"


# --- étape 2c, décision B : au-delà de 30 ajouts, un décompte par catégorie ---------------------------------------

def res_ajouts(n, cats):
    ids = [f"claude-code-{c}-x{i}" for i, c in enumerate(cats[:n])]
    entrees = {i: {"categorie": c} for i, c in zip(ids, cats)}
    return {"ajouts_a_citer": ids, "ajouts_par_categorie": catalogue.ajouts_par_categorie(ids, entrees)}


def test_seuil_30_une_ligne_par_ajout_31_un_decompte_par_categorie():
    assert catalogue.SEUIL_AJOUTS_PAR_LIGNE == 30
    r30 = res_ajouts(30, ["parametres"] * 30)
    (l30,) = fetch.lignes_ajouts_base("claude", r30)
    assert l30.startswith("  + AJOUTS BASE claude : claude-code-parametres-x0, ") and l30.count("claude-code-") == 30
    r31 = res_ajouts(31, ["parametres"] * 20 + ["commandes"] * 11)
    (l31,) = fetch.lignes_ajouts_base("claude", r31)
    assert l31 == "  + AJOUTS BASE claude : 31 (parametres 20, commandes 11)"
    assert len(r31["ajouts_a_citer"]) == 31, "la liste complète reste dans ajouts_a_citer"
    assert fetch.lignes_ajouts_base("claude", {"ajouts_a_citer": []}) == []


def test_ajouts_par_categorie_du_plus_fourni_au_moins_fourni_lu_dans_la_base():
    entrees = {"a": {"categorie": "commandes"}, "b": {"categorie": "parametres"}, "c": {"categorie": "parametres"}, "d": {}}
    assert catalogue.ajouts_par_categorie(["a", "b", "c", "d", "inconnu"], entrees) == {"parametres": 2, "autre": 2, "commandes": 1}


def test_gros_ajout_ecrit_le_decompte_a_l_ecran_et_la_liste_dans_le_fichier(tmp_path, monkeypatch, capsys):
    from test_kb import YAML, lancer_kb, lire as lire_page
    (tmp_path / "sources.yaml").write_text(YAML, encoding="utf-8")
    url = "https://code.claude.com/docs/en/settings-reference.md"
    assert lancer_kb(tmp_path, monkeypatch, None, "claude-code") == 0  # création de l'inventaire : rien à citer
    capsys.readouterr()
    monkeypatch.setattr(catalogue, "SEUIL_AJOUTS_PAR_LIGNE", 0)  # tout ajout dépasse le seuil : on observe la forme du décompte
    page = lire_page("cc_settings.md").replace("## Enterprise and managed settings", NOUVEAUX + "\n## Enterprise and managed settings", 1)
    assert lancer_kb(tmp_path, monkeypatch, {url: page}, "claude-code") == 0
    sortie = capsys.readouterr().out
    m = modifs_kb(tmp_path)
    n = len(m["ajouts_a_citer"])
    assert n >= 1 and sum(m["ajouts_par_categorie"].values()) == n and set(m["ajouts_par_categorie"]) == {"parametres"}
    ligne = [l for l in sortie.splitlines() if "AJOUTS BASE claude" in l]
    assert ligne == [f"  + AJOUTS BASE claude : {n} (parametres {n})"], "décompte seul à l'écran, les ids restent dans le fichier"


def test_skills_disent_le_decompte_par_categorie():
    from conftest import RACINE
    for f in (".claude/skills/delta/SKILL.md", ".agents/skills/delta/SKILL.md", "prompts/codex-delta.md"):
        t = (RACINE / f).read_text(encoding="utf-8")
        assert "Au-delà de 30 ids, `fetch.py --kb` n'imprime plus qu'un décompte par catégorie" in t, f
    for f in (".agents/skills/delta/SKILL.md", "prompts/codex-delta.md"):
        assert "État initial des dépréciations OpenAI en cours" in (RACINE / f).read_text(encoding="utf-8"), f


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
