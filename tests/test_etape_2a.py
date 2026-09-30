"""Étape 2a (D71) : articles d'aide du compte et des quotas dans la veille du jour, nouveaux articles par comparaison
d'index llms.txt, champ `sujet_d71` de la base de référence. Échantillons réels (tests/fixtures/aide_*, oa_*)."""

import json

import pytest

import fetch
from conftest import ARTICLES_AIDE, FIXTURES, FauxClient, ecrire_quotidien
from deltalib import sujet_d71
from deltalib.analyseurs.html_notes import parser_index_articles, parser_sections_suivies
from deltalib.kb import catalogue
from deltalib.modeles import ErreurReseau, FormatInattendu
from deltalib.passage import texte_markdown

INDEX_CLAUDE = (FIXTURES / "aide_llms_claude.txt").read_text(encoding="utf-8")
INDEX_OPENAI = (FIXTURES / "oa_llms_index.txt").read_text(encoding="utf-8")
ARTICLE = (FIXTURES / "aide_limit_reset.md").read_text(encoding="utf-8")
URL_INDEX_CLAUDE = "https://support.claude.com/llms.txt"
URL_ARTICLE_RESET = "https://support.claude.com/en/articles/17007452-what-is-a-limit-reset.md"
NOUVEAU = "- [Extra usage promotion for Max plans](https://support.claude.com/en/articles/99999001-extra-usage-promotion-for-max-plans.md)"
HORS_SUJET = "- [How to verify your email address](https://support.claude.com/en/articles/99999002-how-to-verify-your-email-address.md)"


def lire(p):
    return json.loads(p.read_text(encoding="utf-8"))


# --- filtres : liste de l'index d'aide (b2) et liste de la base de référence (c) ----------------------------------

@pytest.mark.parametrize("texte", ["What is a limit reset?", "Remises à zéro de Codex", "Buy more credits", "Forfait Max",
                                   "Claude API pricing", "Réinitialisation des limites", "Enterprise plans", "Free trial",
                                   "Models, usage, and limits in Claude Code", "How do usage and length limits work?"])
def test_index_sujet_pertinent_reconnu(texte):
    assert sujet_d71.correspond_index(texte)


@pytest.mark.parametrize("texte", ["What is Claude Tag?", "Verify your phone number", "Configure the terminal title", "",
                                   "Usage Policy", "Claude Code usage analytics"])
def test_index_hors_sujet_non_reconnu(texte):
    assert not sujet_d71.correspond_index(texte)


def test_mots_entiers_seulement():
    assert not sujet_d71.correspond_index("planning", "replanned", "offering", "pricey")
    assert not sujet_d71.correspond_base("quotation", "billingual")


@pytest.mark.parametrize("texte", ["Use plan mode to review changes", "Utilise le mode plan avant d'écrire"])
def test_exclusion_plan_mode_est_effective(texte, monkeypatch):
    assert not sujet_d71.correspond_index(texte)
    monkeypatch.setattr(sujet_d71, "_EXCLUS", [])  # sans l'exclusion, le même texte est retenu : le test prouve bien quelque chose
    assert sujet_d71.correspond_index(texte)


@pytest.mark.parametrize("texte", ["Finances : check your credit score", "Finances : votre score de crédit"])
def test_expression_exclue_seule_n_est_pas_retenue(texte):
    assert not sujet_d71.correspond_index(texte) and not sujet_d71.correspond_base(texte)


@pytest.mark.parametrize("texte, mot", [
    ("Finances : your credit score and your usage limits", "usage limit"),
    ("Finances : votre score de crédit et vos crédits", "crédits"),
    ("Plan mode is free, but the Max plan has weekly limits", "plan"),
    ("Utilise le mode plan ; ton forfait Max a une limite hebdomadaire", "forfait"),
])
def test_exclusion_porte_sur_l_expression_pas_sur_le_texte(texte, mot):
    """Un texte qui contient l'expression exclue ET un vrai mot-clé D71 reste marqué."""
    assert mot in sujet_d71.mots_trouves_index(texte)


def test_deux_listes_constantes_distinctes():
    base, index = set(sujet_d71.MOTS_CLES_BASE), set(sujet_d71.MOTS_CLES_INDEX)
    assert base < index and {"limit", "plan", "reset", "offer", "offre", "limite"} <= index - base
    assert not {"limit", "plan", "reset", "offer", "offre", "limite", "usage"} & base
    assert {"usage limit", "rate limit", "limit reset", "extra usage", "free trial", "remise à zéro", "quota", "credits", "crédits",
            "billing", "subscription", "abonnement", "pricing", "price", "tarif", "forfait", "promotion", "réinitialisation"} == base
    assert "credit score" in sujet_d71.EXCLUSIONS and "plan mode" in sujet_d71.EXCLUSIONS


@pytest.mark.parametrize("nom, usage, description", [
    ("auto-compact-token-limit", "auto-compact-token-limit = 120000", "Token limit that triggers automatic compaction."),
    ("tool-output-token-limit", "tool_output_token_limit = 10000", "Maximum tokens kept from a tool output. Limit applies per call."),
    ("bash-max-output-length", "BASH_MAX_OUTPUT_LENGTH=30000", "Limits the characters of bash output kept in context."),
    ("/plan", "/plan", "Enter plan mode. Available on paid plans."),
    ("/clear", "/clear", "Reset the conversation context."),
    ("reset-font-size", "reset-font-size", "Reset the font size to the default."),
    ("/feedback-offer", "/feedback", "We offer a way to send feedback. Offre de retour."),
])
def test_base_reglage_technique_avec_mot_ambigu_seul_n_est_pas_marque(nom, usage, description):
    assert not sujet_d71.correspond_base(nom, usage, description)
    assert catalogue.sujet_d71({"x": {"nom": nom, "usage": usage, "description_source": description}}, {"ajoutees": ["x"]}) == []


@pytest.mark.parametrize("nom, usage, description", [
    ("/usage", "/usage", "Show your plan usage limits and when they reset."),
    ("/extra-usage", "/extra-usage", "Turn on extra usage when you reach a limit."),
    ("/cost", "/cost", "Session cost and quota."),
    ("billing", "", "Gérer la facturation et l'abonnement."),
    ("promotion", "", "Offre promotionnelle : promotion sur les forfaits Pro."),
])
def test_base_expressions_sans_double_sens_marquees(nom, usage, description):
    assert sujet_d71.correspond_base(nom, usage, description)


def test_index_garde_les_mots_ambigus_la_base_non():
    titre = "Models, usage, and limits in Claude Code"
    assert sujet_d71.correspond_index(titre) and not sujet_d71.correspond_base(titre)
    assert sujet_d71.correspond_index("What is the Pro plan?") and not sujet_d71.correspond_base("What is the Pro plan?")


def entrees(**noms):
    return {i: {"nom": n, "usage": u, "description_source": d} for i, (n, u, d) in noms.items()}


def test_catalogue_sujet_d71_marque_les_entrees_pertinentes():
    e = entrees(a=("/usage", "/usage", "Show your plan usage limits"), b=("/color", "/color", "Change the prompt bar color"),
                c=("finances", "credit score", "View your credit score"), d=("/cost", "/cost", "Session cost and quota"),
                e=("Plan mode", "claude --permission-mode plan", "Enter plan mode"), f=("finances", "credit score", "View your credit score and usage limits"),
                g=("tool-output-token-limit", "tool_output_token_limit", "Maximum tokens kept from a tool output."))
    modif = {"ajoutees": ["a", "b", "e", "g"], "usage_modifie": ["c", "f"], "description_source_modifiee": ["d", "a"], "retirees": ["b"]}
    # b hors sujet, c et e ne portent que l'expression exclue, g n'a que « limit » (réglage technique), f garde un vrai mot-clé, a une seule fois
    assert catalogue.sujet_d71(e, modif) == ["a", "d", "f"]


def test_catalogue_sujet_d71_liste_vide_sans_entree_pertinente():
    e = entrees(b=("/color", "/color", "Change the prompt bar color"))
    assert catalogue.sujet_d71(e, {"ajoutees": ["b"], "usage_modifie": [], "description_source_modifiee": []}) == []
    assert catalogue.sujet_d71(e, {}) == []


def test_fetch_kb_ecrit_sujet_d71_dans_le_fichier_de_modifications(tmp_path, monkeypatch):
    from test_kb import YAML, lancer_kb
    (tmp_path / "sources.yaml").write_text(YAML, encoding="utf-8")
    assert lancer_kb(tmp_path, monkeypatch) == 0
    for p in ("claude", "openai"):
        modif = lire(tmp_path / "raw" / "kb" / f"{p}-modifications.json")
        entrees_p = catalogue.charger(tmp_path, p)
        attendu = sorted(i for i in modif["ajoutees"] if sujet_d71.correspond_base(
            entrees_p[i].get("nom"), entrees_p[i].get("usage"), entrees_p[i].get("description_source")))
        assert modif["sujet_d71"] == attendu and set(attendu) <= set(modif["ajoutees"])


def test_fetch_kb_affiche_la_ligne_sujet_d71(tmp_path, monkeypatch, capsys):
    from test_kb import YAML, lancer_kb
    (tmp_path / "sources.yaml").write_text(YAML, encoding="utf-8")
    monkeypatch.setattr(catalogue, "sujet_d71", lambda entrees, modif: sorted(modif["ajoutees"])[:2])
    assert lancer_kb(tmp_path, monkeypatch, None, "claude-code") == 0
    modif = lire(tmp_path / "raw" / "kb" / "claude-modifications.json")
    assert len(modif["sujet_d71"]) == 2
    assert f"~ SUJET D71 claude : {', '.join(modif['sujet_d71'])}" in capsys.readouterr().out


# --- (b1) sources à sections suivies -------------------------------------------------------------------------------

def test_sources_declarees(sources):
    claude = [sources[f"claude-aide-{k}"] for k in ("limites", "limites-bonnes-pratiques", "remise-a-zero", "bundles", "credits",
                                                    "limites-claude-code", "claude-code-pro-max", "fable-forfait", "agent-sdk-forfait", "forfait-max")]
    assert {s.url for s in claude} == {f"https://support.claude.com/en/articles/{a}.md" for a in ARTICLES_AIDE}
    for s in [*claude, sources["openai-usage-commande"]]:
        assert s.statut == "a_valider" and s.officielle and s.options["suivre_revisions"] and "Testé le 2026-09-30" in s.note
    for s in (sources["claude-aide-index"], sources["openai-aide-index"]):
        assert s.statut == "a_valider" and s.officielle and s.options["amorcage_silencieux"] and s.options["lire_articles"] == "markdown"
    assert sources["claude-aide-index"].perimetre == "claude" and sources["openai-aide-index"].perimetre == "openai"
    assert sources["claude-aide-index"].options["section"] == "English"


def test_article_entier_suivi_par_le_premier_titre(sources):
    (e,) = parser_sections_suivies(ARTICLE, sources["claude-aide-remise-a-zero"])
    assert e.id == "claude-aide-remise-a-zero-article" and e.date_publication is None and e.officielle
    assert e.url == "https://support.claude.com/en/articles/17007452-what-is-a-limit-reset#what-is-a-limit-reset"
    assert "Reset for free" in e.contenu and "How a limit reset works" in e.contenu, "tout l'article, sous-sections comprises"
    # un titre de page modifié ne casse pas le suivi (l'empreinte, elle, change)
    (e2,) = parser_sections_suivies(ARTICLE.replace("# What is a limit reset?", "# What is a usage reset?"), sources["claude-aide-remise-a-zero"])
    assert e2.id == e.id


def test_commande_usage_de_codex_suivie(sources):
    (e,) = parser_sections_suivies((FIXTURES / "oa_devcmd_usage.md").read_text(encoding="utf-8"), sources["openai-usage-commande"])
    assert e.id == "openai-usage-commande-usage" and "redeem an available earned reset" in e.contenu
    assert ".md" not in e.url and e.url.startswith("https://learn.chatgpt.com/docs/developer-commands?surface=cli#")
    assert "/debug-config" not in e.contenu, "la section s'arrête à la suivante"


TITRE_ETAT_INITIAL = "État initial des pages compte et quotas suivies"


def aide(brut, index=False):
    return [n for n in brut["nouveautes"] if n["source_id"].startswith("claude-aide-") and (index or n["source_id"] != "claude-aide-index")]


def test_premier_passage_un_seul_element_etat_initial_une_ligne_par_page(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-20"])
    brut = lire(tmp_path / "raw" / "claude-nouveautes.json")
    (etat,) = aide(brut, index=True)  # un seul élément pour dix pages et l'index, ni dix éléments ni silence
    assert etat["titre"] == TITRE_ETAT_INITIAL and etat["date_publication"] is None and etat["officielle"] and not etat["revision"]
    lignes = [l for l in etat["contenu"].splitlines() if l.startswith("- ")]
    pages = [l for l in lignes if not l.startswith("- Index ")]
    assert len(pages) == 10 and len(set(pages)) == 10, "une ligne par page"
    assert all("https://support.claude.com/en/articles/" in l for l in pages)
    assert any("What is a limit reset?" in l and "17007452" in l for l in pages)
    (ligne_index,) = [l for l in lignes if l.startswith("- Index ")]
    assert "https://support.claude.com/llms.txt" in ligne_index and "enregistré(s) comme référence" in ligne_index
    # les pages vont dans `ignores` avec leur empreinte : l'état est tenu page par page
    ids_pages = {f"{src}-article" for src in ("claude-aide-limites", "claude-aide-remise-a-zero", "claude-aide-forfait-max")}
    assert ids_pages <= set(brut["ignores"]) and all(brut["empreintes"][i] for i in ids_pages)
    ecrire_quotidien(tmp_path, "claude", brut, "2026-09-26")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider", "--date", "2026-09-26"]) == 0
    vus = lire(tmp_path / "state" / "claude.json")["vus"]
    assert ids_pages <= set(vus) and all(vus[i]["empreinte"] for i in ids_pages) and etat["id"] in vus
    # passage suivant, rien n'a changé : l'état initial ne revient pas
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    assert not aide(lire(tmp_path / "raw" / "claude-nouveautes.json"), index=True)


def test_section_modifiee_donne_une_revision(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-20"])
    ecrire_quotidien(tmp_path, "claude", lire(tmp_path / "raw" / "claude-nouveautes.json"), "2026-09-26")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider", "--date", "2026-09-26"]) == 0
    change = ARTICLE.replace("Click \"Reset for free\"", "Click \"Reset now\"")
    assert change != ARTICLE
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({URL_ARTICLE_RESET: (change, "text/markdown")}))
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    rev = aide(lire(tmp_path / "raw" / "claude-nouveautes.json"), index=True)
    assert [(n["id"], n["revision"], n["titre"] == TITRE_ETAT_INITIAL) for n in rev] == [("claude-aide-remise-a-zero-article", True, False)]


def test_nouvelle_page_ajoutee_plus_tard_a_son_propre_etat_initial(tmp_path, monkeypatch, date_figee):
    """Une source-page ajoutée après le premier passage arrive dans un nouvel élément d'état initial, pas en silence."""
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--depuis", "2026-09-20"])
    brut = lire(tmp_path / "raw" / "claude-nouveautes.json")
    ecrire_quotidien(tmp_path, "claude", brut, "2026-09-26")
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider", "--date", "2026-09-26"])
    etat_f = tmp_path / "state" / "claude.json"
    e = lire(etat_f)
    for sid in ("claude-aide-forfait-max",):  # la source est oubliée de l'état : comme si elle venait d'être ajoutée
        e["sources"].pop(sid, None)
        e["vus"] = {k: v for k, v in e["vus"].items() if v.get("source_id") != sid}
    etat_f.write_text(json.dumps(e), encoding="utf-8")
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    (etat,) = aide(lire(tmp_path / "raw" / "claude-nouveautes.json"), index=True)
    assert etat["titre"] == TITRE_ETAT_INITIAL and "Forfait Max" in etat["contenu"] and "Index " not in etat["contenu"]


def test_page_d_aide_en_echec_va_dans_sources_en_echec(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({URL_ARTICLE_RESET: ErreurReseau("HTTP 403 pour " + URL_ARTICLE_RESET)}))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"]) == 0
    brut = lire(tmp_path / "raw" / "claude-nouveautes.json")
    echecs = [e for e in brut["sources_en_echec"] if e["id"] == "claude-aide-remise-a-zero"]
    assert len(echecs) == 1 and "403" in echecs[0]["erreur"] and echecs[0]["partiel"] is False
    assert not [n for n in brut["nouveautes"] if n["source_id"] == "claude-aide-remise-a-zero"]


def test_page_d_aide_sans_titre_ni_contenu_est_une_erreur_explicite(sources):
    with pytest.raises(FormatInattendu):
        parser_sections_suivies("Un texte sans aucun titre.\n", sources["claude-aide-remise-a-zero"])


# --- (b2) nouveaux articles par comparaison d'index ----------------------------------------------------------------

def test_index_claude_section_english_et_filtre(sources):
    es = parser_index_articles(INDEX_CLAUDE, sources["claude-aide-index"])
    ids = [e.id for e in es]
    assert "claude-aide-index-17007452" in ids and "claude-aide-index-9797557" in ids
    assert "claude-aide-index-15594475" not in ids, "« What is Claude Tag? » ne touche pas au compte : hors sujet"
    assert "claude-aide-index-7996845" not in ids and len(ids) == len(set(ids)), "hors sujet absent, aucun doublon avec la section française"
    e = next(x for x in es if x.id == "claude-aide-index-17007452")
    assert e.date_publication is None and e.officielle and e.produit == "claude"
    assert e.titre == "Nouvel article d'aide — What is a limit reset?"
    assert e.url == "https://support.claude.com/en/articles/17007452-what-is-a-limit-reset" and "limit reset" in e.contenu


def test_index_identifiant_stable_malgre_un_changement_de_titre_ou_de_slug(sources):
    t = INDEX_CLAUDE.replace("17007452-what-is-a-limit-reset", "17007452-what-is-a-usage-reset").replace("What is a limit reset?", "What is a limit reset now?")
    assert "claude-aide-index-17007452" in [e.id for e in parser_index_articles(t, sources["claude-aide-index"])]


def test_index_sans_section_english_ou_sans_ligne_est_une_erreur(sources):
    with pytest.raises(FormatInattendu, match="English"):
        parser_index_articles(INDEX_CLAUDE.replace("## English", "## Anglais"), sources["claude-aide-index"])
    with pytest.raises(FormatInattendu, match="aucune ligne"):
        parser_index_articles("# Claude Help Center\n\n## English\n\nPage en maintenance.\n", sources["claude-aide-index"])


def test_index_openai_identifiant_par_chemin(sources):
    ids = [e.id for e in parser_index_articles(INDEX_OPENAI, sources["openai-aide-index"])]
    assert "openai-aide-index-docs-pricing" in ids and "openai-aide-index-docs-enterprise-usage-limits" in ids
    assert "openai-aide-index-docs-integrated-terminal" not in ids and "openai-aide-index-docs-image-generation" not in ids


def passage(tmp_path, monkeypatch, pannes, *args):
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient(pannes))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", *args]) == 0
    return lire(tmp_path / "raw" / "claude-nouveautes.json")


def test_premier_passage_silencieux_puis_nouvel_article(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    brut = passage(tmp_path, monkeypatch, {}, "--depuis", "2026-09-20")
    assert not [n for n in brut["nouveautes"] if n["source_id"] == "claude-aide-index"], "l'existant n'est pas annoncé"
    deja = [i for i in brut["ignores"] if i.startswith("claude-aide-index-")]
    assert deja and brut["ignores_sources"][deja[0]] == "claude-aide-index"
    ecrire_quotidien(tmp_path, "claude", brut, "2026-09-26")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider", "--date", "2026-09-26"]) == 0
    assert set(deja) <= set(lire(tmp_path / "state" / "claude.json")["vus"]), "la référence est inscrite dans l'état"
    # deuxième passage, index identique : rien
    assert not [n for n in passage(tmp_path, monkeypatch, {}) ["nouveautes"] if n["source_id"] == "claude-aide-index"]
    # un article pertinent et un article hors sujet apparaissent dans l'index
    index = INDEX_CLAUDE.replace("## Français", NOUVEAU + "\n" + HORS_SUJET + "\n\n## Français", 1)
    url_nouveau = "https://support.claude.com/en/articles/99999001-extra-usage-promotion-for-max-plans.md"
    texte = "# Extra usage promotion for Max plans\n\nMax subscribers get 50% more extra usage until October 15.\n"
    brut = passage(tmp_path, monkeypatch, {URL_INDEX_CLAUDE: (index, "text/plain"), url_nouveau: (texte, "text/markdown")})
    nouveaux = [n for n in brut["nouveautes"] if n["source_id"] == "claude-aide-index"]
    assert [n["id"] for n in nouveaux] == ["claude-aide-index-99999001"], "le hors sujet ne produit rien"
    assert "50% more extra usage" in nouveaux[0]["contenu"] and nouveaux[0]["date_publication"] is None and not nouveaux[0]["revision"]
    assert nouveaux[0]["url"] == "https://support.claude.com/en/articles/99999001-extra-usage-promotion-for-max-plans"
    assert not [e for e in brut["sources_en_echec"] if e["id"] == "claude-aide-index"]


def test_article_nouveau_illisible_garde_le_resume_et_signale(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    brut = passage(tmp_path, monkeypatch, {}, "--depuis", "2026-09-20")
    ecrire_quotidien(tmp_path, "claude", brut, "2026-09-26")
    fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider", "--date", "2026-09-26"])
    index = INDEX_CLAUDE.replace("## Français", NOUVEAU + "\n\n## Français", 1)
    brut = passage(tmp_path, monkeypatch, {URL_INDEX_CLAUDE: (index, "text/plain"),
                                           "https://support.claude.com/en/articles/99999001-extra-usage-promotion-for-max-plans.md": ErreurReseau("HTTP 500")})
    (n,) = [x for x in brut["nouveautes"] if x["source_id"] == "claude-aide-index"]
    assert "Extra usage promotion" in n["contenu"]  # le titre remplace le contenu absent, jamais un vide
    assert [e["partiel"] for e in brut["sources_en_echec"] if e["id"] == "claude-aide-index"] == [True]


def test_index_en_echec_est_signale_sans_nouveaute(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    for erreur in (ErreurReseau("HTTP 403 pour " + URL_INDEX_CLAUDE),):
        brut = passage(tmp_path, monkeypatch, {URL_INDEX_CLAUDE: erreur})
        (e,) = [x for x in brut["sources_en_echec"] if x["id"] == "claude-aide-index"]
        assert "403" in e["erreur"] and not [n for n in brut["nouveautes"] if n["source_id"] == "claude-aide-index"]
    brut = passage(tmp_path, monkeypatch, {URL_INDEX_CLAUDE: ("# Claude Help Center\n\n## English\n\n(maintenance)\n", "text/plain")})
    (e,) = [x for x in brut["sources_en_echec"] if x["id"] == "claude-aide-index"]
    assert e["erreur"].startswith("FormatInattendu:")


def test_texte_markdown_refuse_le_vide_et_le_html():
    with pytest.raises(FormatInattendu):
        texte_markdown("  \n")
    with pytest.raises(FormatInattendu):
        texte_markdown("<!DOCTYPE html><html><body>403</body></html>")
    assert texte_markdown("> For the complete documentation index, see llms.txt\n\n# Titre\n\nCorps.") == "# Titre\n\nCorps."


@pytest.mark.parametrize("fichier, perimetre", [(".claude/skills/delta/SKILL.md", "claude"), (".agents/skills/delta/SKILL.md", "openai"),
                                                 ("prompts/codex-delta.md", "openai")])
def test_les_skills_citent_chaque_id_de_sujet_d71(fichier, perimetre):
    from conftest import RACINE
    texte = (RACINE / fichier).read_text(encoding="utf-8")
    assert f"chaque id de la liste `sujet_d71` de `raw/kb/{perimetre}-modifications.json`" in texte and "SUJET D71" in texte
    assert "nouvel article d'aide" in texte and "type: nouveaute" in texte
    assert "sans jugement" in texte
    assert "« État initial des pages compte et quotas suivies »" in texte and "un seul élément `fort`" in texte


def test_d73_inscrite_dans_la_spec():
    from conftest import RACINE
    spec = (RACINE / "SPEC.md").read_text(encoding="utf-8")
    assert "| D73 |" in spec and "`MOTS_CLES_BASE`" in spec and "`MOTS_CLES_INDEX`" in spec and "`sujet_d71`" in spec and "amorcage_silencieux" in spec and "D71" in spec.split("| D73 |")[1]
    assert "Claude (compte et quotas, D73)" in spec
