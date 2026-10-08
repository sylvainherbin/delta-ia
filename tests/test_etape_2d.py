"""Étape 2d : échéances de retrait (`deltalib/echeances.py`, option `echeances` des sources `anthropic-deprecations` et
`openai-deprecations`). Échantillons réels du 2026-10-01 (tests/fixtures/deprec_*.md), client simulé, dates figées, aucun réseau.

Jalon de référence : le retrait de `claude-sonnet-4-5-20250929` le 2026-11-30 (J-14 = 2026-11-16, J-1 = 2026-11-29)."""

import json
from datetime import date, timedelta

import pytest

from deltalib import echeances as E
from deltalib.echeances import extraire_retraits, lire_date_retrait, palier, produire_echeances
from test_etape_2c import (PAGE_ANTHROPIC, PAGE_OPENAI, URL_ANTHROPIC, URL_OPENAI, ID_CYBER, dossiers, etat_non_vide, passage,
                           valider)

ID_SONNET_J14 = "echeance-anthropic-deprecations-claude-sonnet-4-5-20250929-2026-11-30-j14"
ID_SONNET_J1 = "echeance-anthropic-deprecations-claude-sonnet-4-5-20250929-2026-11-30-j1"
OPENAI_28_09 = ["babbage-002", "davinci-002", "gpt-3-5-turbo-1106", "gpt-3-5-turbo-instruct"]


def ech(brut):
    return [n for n in brut["nouveautes"] if n["id"].startswith("echeance-")]


def ids_ech(brut):
    return sorted(n["id"] for n in ech(brut))


def jour_fige(monkeypatch, iso):
    import deltalib.passage as ps
    monkeypatch.setattr(ps, "aujourd_hui", lambda: date.fromisoformat(iso))


def avancer(tmp_path, monkeypatch, perimetre, iso, pannes=None, valide=True):
    """Un passage figé au jour `iso`, puis (par défaut) la validation de tout ce qu'il a produit, comme `/delta`."""
    jour_fige(monkeypatch, iso)
    _, brut = passage(tmp_path, monkeypatch, perimetre, pannes)
    if valide:
        valider(tmp_path, monkeypatch, perimetre, brut, iso)
    return brut


@pytest.fixture
def etat_claude(tmp_path):
    """Périmètre claude déjà en service : aucune fenêtre de premier passage, `anthropic-deprecations` seule source nouvelle."""
    from deltalib.etat import ecrire_json
    dossiers(tmp_path)
    ecrire_json(tmp_path / "state" / "claude.json", {"version": 1, "maj_le": "2026-11-01T10:00:00+00:00",
                                                       "vus": {"claude-code-2.1.281": {"source_id": "claude-code-changelog"}}})
    return tmp_path


def sonnet(sources):
    retraits, signales = extraire_retraits(PAGE_ANTHROPIC, sources["anthropic-deprecations"])
    (r,) = [x for x in retraits if x.cle == "claude-sonnet-4-5-20250929" and x.date_retrait == "2026-11-30"]
    return r, retraits, signales


# --- extraction ---------------------------------------------------------------------------------------------------

def test_options_declarees(sources):
    for sid in ("anthropic-deprecations", "openai-deprecations"):
        assert sources[sid].options["echeances"] is True
    assert sources["anthropic-deprecations"].options["ancre_points"] == "tiret"
    assert "ancre_points" not in sources["openai-deprecations"].options
    assert [s.id for s in sources.values() if s.options.get("echeances")] == ["anthropic-deprecations", "openai-deprecations"]


def test_extraction_anthropic_champs_complets(sources):
    r, retraits, signales = sonnet(sources)
    assert (r.modele, r.date_retrait, r.date_annonce, r.remplacement) == ("claude-sonnet-4-5-20250929", "2026-11-30", "2026-09-30", "claude-sonnet-5-5")
    assert r.url == "https://platform.claude.com/docs/en/about-claude/model-deprecations#2026-09-30-claude-sonnet-4-5-model"
    assert "notified developers using Claude Sonnet 4.5" in r.prose and "claude-sonnet-5-5" not in r.prose
    assert not signales and all(x.ferme and x.date_retrait for x in retraits)
    assert len(retraits) == 20, "une ligne par modèle des annonces ; le tableau d'état « Not sooner than » n'en donne aucun"
    assert not [x for x in retraits if x.cle in ("claude-haiku-4-5-20251001", "claude-mythos-preview")]
    # les ancres suivent le moteur du site : Anthropic remplace le point par un tiret, OpenAI le retire
    ancien = next(x for x in retraits if x.cle == "claude-2-0")
    assert ancien.url.endswith("#2025-01-21-claude-2-claude-2-1-and-claude-sonnet-3-models")


def test_extraction_openai_tableaux_de_modeles_et_de_fonctionnalites(sources):
    retraits, signales = extraire_retraits(PAGE_OPENAI, sources["openai-deprecations"])
    par = {(x.cle, x.date_retrait): x for x in retraits}
    cyber = par[("gpt-5-4-cyber", "2026-10-01")]
    assert cyber.date_annonce == "2026-09-11" and cyber.remplacement == "The most capable cyber model available to you."
    assert cyber.url == "https://developers.openai.com/api/docs/deprecations#2026-09-11-gpt-54-cyber"
    # cellule à alias (`a` \| `b`, `c`) : un seul retrait, nommé par son premier nom, cellule complète conservée
    alias = par[("gpt-3-5-turbo-0125", "2026-10-23")]
    assert alias.modele.startswith("gpt-3.5-turbo-0125 | gpt-3.5-turbo") and alias.remplacement == "gpt-5.6-terra"
    # tableaux « Date / Update » : la fonctionnalité est le titre de l'annonce, une échéance par étape datée, étape conservée
    assert par[("evals-platform", "2026-10-31")].detail == "Existing evals become read-only."
    assert "shut down" in par[("evals-platform", "2026-11-30")].detail and par[("evals-platform", "2026-11-30")].remplacement is None
    assert par[("agent-builder", "2026-11-30")].modele == "Agent Builder"
    # annonce sans date : date d'annonce null, jamais devinée
    ft = par[("update-to-openai-s-self-serve-fine-tuning", "2027-01-06")]
    assert ft.date_annonce is None and ft.url.endswith("#update-to-openais-self-serve-fine-tuning")
    # remplacement « --- » : null ; tiret insécable U+2011 de « 2026‑08‑26 » lu comme une date
    assert par[("sora-2", "2026-09-24")].remplacement is None
    assert ("assistants-api", "2026-08-26") in par
    # seule la borne « at earliest 2024-06-13 » est écartée, et le tableau d'un autre format (colonnes de prix) est lu
    assert ("gpt-4-0314", "2024-06-13") not in par and ("text-davinci-003", "2024-01-04") in par
    assert [s.genre for s in signales] == ["date_non_ferme"]


def test_dates_de_retrait_formats_reels_et_bornes():
    assert lire_date_retrait("Oct 1, 2026") == ("2026-10-01", True)
    assert lire_date_retrait("October 23, 2026") == ("2026-10-23", True)
    assert lire_date_retrait("2026-09-24") == ("2026-09-24", True)
    assert lire_date_retrait("2026‑08‑26") == ("2026-08-26", True)
    assert lire_date_retrait("Jan 6, 2027") == ("2027-01-06", True)
    assert lire_date_retrait("at earliest 2024-06-13") == ("2024-06-13", False)
    assert lire_date_retrait("Not sooner than September 1, 2027") == ("2027-09-01", False)
    assert lire_date_retrait("To be announced") == (None, True)
    assert lire_date_retrait("---") == (None, True)
    assert E.normaliser_modele("gpt-4o-2024-05-13 | gpt-4o") == "gpt-4o-2024-05-13"
    assert E.normaliser_modele("gpt-5.4-cyber") == "gpt-5-4-cyber"


def test_paliers():
    assert [palier(n) for n in (16, 15, 14, 13, 2, 1, 0, -1)] == [None, None, "j14", "j14", "j14", "j1", None, None]


# --- éléments d'échéance ------------------------------------------------------------------------------------------

def test_format_de_l_element(sources):
    r, retraits, signales = sonnet(sources)
    (e,) = produire_echeances(sources["anthropic-deprecations"], [r], [], date(2026, 11, 16))[0]
    assert e.id == ID_SONNET_J14 and e.titre == "Retrait de claude-sonnet-4-5-20250929 le 2026-11-30 (dans 14 jours)"
    assert e.date_publication is None and e.version is None and e.produit == "claude" and e.officielle is True
    assert e.url == r.url and e.source_id == "anthropic-deprecations-echeances"
    assert "claude-sonnet-4-5-20250929 sera retiré le 2026-11-30 (dans 14 jours au passage du 2026-11-16)" in e.contenu
    assert "Remplacement recommandé : claude-sonnet-5-5" in e.contenu
    assert "Annonce d'origine (« Claude Sonnet 4.5 model », 2026-09-30) : On September 30, 2026, Anthropic notified" in e.contenu
    (e1,) = produire_echeances(sources["anthropic-deprecations"], [r], [], date(2026, 11, 29))[0]
    assert e1.id == ID_SONNET_J1 and e1.titre == "Retrait de claude-sonnet-4-5-20250929 le 2026-11-30 (dans 1 jour)"


def test_paliers_sur_la_page_reelle(sources):
    s = sources["anthropic-deprecations"]
    r, _, _ = sonnet(sources)
    quand = {"2026-11-15": [], "2026-11-16": [ID_SONNET_J14], "2026-11-17": [ID_SONNET_J14], "2026-11-29": [ID_SONNET_J1],
             "2026-11-30": [], "2026-12-01": [], "2027-03-01": []}
    for iso, attendu in quand.items():
        assert [e.id for e in produire_echeances(s, [r], [], date.fromisoformat(iso))[0]] == attendu, iso


def test_identifiant_stable_d_un_passage_a_l_autre(sources):
    s = sources["anthropic-deprecations"]
    r, _, _ = sonnet(sources)
    ids = {produire_echeances(s, [r], [], date(2026, 11, 30) - timedelta(days=n))[0][0].id for n in range(2, 15)}
    assert ids == {ID_SONNET_J14}, "du J-14 au J-2 : toujours le même identifiant, aucun ne dépend du jour du passage"
    a = produire_echeances(s, [r], [], date(2026, 11, 20))[0][0]
    b = produire_echeances(s, [r], [], date(2026, 11, 20))[0][0]
    assert a == b


# --- signalements ------------------------------------------------------------------------------------------------

def test_date_de_retrait_illisible_est_signalee_jamais_devinee(sources):
    s = sources["anthropic-deprecations"]
    page = PAGE_ANTHROPIC.replace("| November 30, 2026 | `claude-sonnet-4-5-20250929` |", "| soon | `claude-sonnet-4-5-20250929` |")
    assert page != PAGE_ANTHROPIC
    retraits, signales = extraire_retraits(page, s)
    assert not [x for x in retraits if x.cle == "claude-sonnet-4-5-20250929"]
    (sig,) = signales
    assert sig.genre == "date_illisible" and "claude-sonnet-4-5-20250929" in sig.texte and "'soon'" in sig.texte
    elements, message = produire_echeances(s, retraits, signales, date(2026, 11, 20))
    assert elements == [] and message.startswith("échéances : 1 signalement(s)") and "illisible" in message


def test_borne_a_venir_signalee_borne_echue_silencieuse(sources):
    s = sources["anthropic-deprecations"]
    page = PAGE_ANTHROPIC.replace("| November 30, 2026 | `claude-sonnet-4-5-20250929` |", "| Not sooner than November 30, 2026 | `claude-sonnet-4-5-20250929` |")
    retraits, signales = extraire_retraits(page, s)
    assert [x.genre for x in signales] == ["date_non_ferme"] and not [x for x in retraits if x.cle == "claude-sonnet-4-5-20250929"]
    assert produire_echeances(s, retraits, signales, date(2026, 11, 20))[1] is not None
    assert produire_echeances(s, retraits, signales, date(2026, 12, 20))[1] is None, "borne passée : sans objet"


def test_annonce_recente_sans_tableau_signalee_ancienne_non(sources):
    s = sources["anthropic-deprecations"]
    tableau = ("| Retirement date   | Deprecated model             | Recommended replacement |\n"
               "| ----------------- | ---------------------------- | ----------------------- |\n"
               "| November 30, 2026 | `claude-sonnet-4-5-20250929` | `claude-sonnet-5-5`     |\n")
    assert tableau in PAGE_ANTHROPIC
    page = PAGE_ANTHROPIC.replace(tableau, "It will be retired on November 30, 2026.\n")
    retraits, signales = extraire_retraits(page, s)
    assert [x.genre for x in signales] == ["annonce_sans_retrait"] and not [x for x in retraits if x.cle == "claude-sonnet-4-5-20250929"]
    _, message = produire_echeances(s, retraits, signales, date(2026, 11, 20))
    assert message and "Claude Sonnet 4.5 model" in message
    # la même annonce, deux ans plus tard : historique, plus rien à signaler
    assert produire_echeances(s, retraits, signales, date(2028, 11, 20))[1] is None


def test_page_sans_aucun_retrait_signale_le_gabarit(sources):
    s = sources["anthropic-deprecations"]
    page = PAGE_ANTHROPIC.replace("Retirement date", "Colonne")  # en-têtes renommés : plus aucun tableau de dates reconnu
    retraits, signales = extraire_retraits(page, s)
    assert retraits == []
    elements, message = produire_echeances(s, retraits, [], date(2026, 11, 20))
    assert elements == [] and "gabarit changé" in message


# --- de bout en bout : état, validation, passages manqués ----------------------------------------------------------

def test_j15_rien_j14_un_element_j13_rien_de_nouveau_j1_un_element_retrait_et_apres_rien(etat_claude, monkeypatch):
    t = etat_claude
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-15")) == [], "J-15"
    brut = avancer(t, monkeypatch, "claude", "2026-11-16")
    (n,) = ech(brut)
    assert n["id"] == ID_SONNET_J14 and n["titre"].endswith("(dans 14 jours)") and n["source_id"] == "anthropic-deprecations-echeances"
    assert n["date_publication"] is None and n["officielle"] is True and n["revision"] is False
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-17")) == [], "J-13 : déjà vue, rien de nouveau"
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-28")) == [], "J-2 : rien"
    brut = avancer(t, monkeypatch, "claude", "2026-11-29")
    (n,) = ech(brut)
    assert n["id"] == ID_SONNET_J1 and n["titre"] == "Retrait de claude-sonnet-4-5-20250929 le 2026-11-30 (dans 1 jour)"
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-29")) == [], "même jour relancé : rien de nouveau"
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-30")) == [], "jour du retrait"
    assert ech(avancer(t, monkeypatch, "claude", "2026-12-01")) == [], "après le retrait"
    vus = json.loads((t / "state" / "claude.json").read_text(encoding="utf-8"))["vus"]
    assert ID_SONNET_J14 in vus and ID_SONNET_J1 in vus


def test_passage_manque_a_j14_rattrape_a_j12(etat_claude, monkeypatch):
    t = etat_claude
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-10")) == []
    brut = avancer(t, monkeypatch, "claude", "2026-11-18")  # aucun passage les 16 et 17
    (n,) = ech(brut)
    assert n["id"] == ID_SONNET_J14 and n["titre"].endswith("(dans 12 jours)")
    assert ech(avancer(t, monkeypatch, "claude", "2026-11-19")) == []


def test_echeance_non_validee_revient_au_passage_suivant_sous_le_meme_identifiant(etat_claude, monkeypatch):
    t = etat_claude
    b1 = avancer(t, monkeypatch, "claude", "2026-11-16", valide=False)
    b2 = avancer(t, monkeypatch, "claude", "2026-11-17", valide=False)
    assert ids_ech(b1) == ids_ech(b2) == [ID_SONNET_J14], "le suivi n'inscrit que ce que /delta a couvert : rien n'est perdu"
    assert ech(b2)[0]["titre"].endswith("(dans 13 jours)")


def test_premier_passage_au_dernier_jour_ne_sort_que_j1(etat_claude, monkeypatch):
    brut = avancer(etat_claude, monkeypatch, "claude", "2026-11-29")
    assert ids_ech(brut) == [ID_SONNET_J1], "le niveau le plus urgent seul : pas de j14 en plus d'un j1"


def test_source_en_echec_ne_produit_aucune_echeance(etat_claude, monkeypatch):
    from deltalib.modeles import ErreurReseau
    brut = avancer(etat_claude, monkeypatch, "claude", "2026-11-16", {URL_ANTHROPIC: ErreurReseau("HTTP 403 pour " + URL_ANTHROPIC)}, valide=False)
    assert ech(brut) == [] and [e["id"] for e in brut["sources_en_echec"] if e["id"] == "anthropic-deprecations"] == ["anthropic-deprecations"]


def test_date_illisible_remonte_en_source_partielle(etat_claude, monkeypatch):
    page = PAGE_ANTHROPIC.replace("| November 30, 2026 | `claude-sonnet-4-5-20250929` |", "| soon | `claude-sonnet-4-5-20250929` |")
    brut = avancer(etat_claude, monkeypatch, "claude", "2026-11-16", {URL_ANTHROPIC: (page, "text/markdown")}, valide=False)
    assert ech(brut) == []
    (e,) = [x for x in brut["sources_en_echec"] if x["id"] == "anthropic-deprecations"]
    assert e["partiel"] is True and "illisible" in e["erreur"] and "claude-sonnet-4-5-20250929" in e["erreur"]
    assert "anthropic-deprecations" in brut["sources_traitees"], "la source reste traitée : ses annonces arrivent"


def test_date_de_retrait_modifiee_donne_une_nouvelle_echeance(etat_claude, monkeypatch):
    t = etat_claude
    assert ids_ech(avancer(t, monkeypatch, "claude", "2026-11-16")) == [ID_SONNET_J14]
    page = PAGE_ANTHROPIC.replace("November 30, 2026", "December 15, 2026")
    brut = avancer(t, monkeypatch, "claude", "2026-12-01", {URL_ANTHROPIC: (page, "text/markdown")})
    assert ids_ech(brut) == ["echeance-anthropic-deprecations-claude-sonnet-4-5-20250929-2026-12-15-j14"]


# --- état initial : pas de répétition, échéances normales ---------------------------------------------------------

def test_etat_initial_ne_repete_pas_les_retraits_leurs_echeances_sortent_normalement(tmp_path, monkeypatch):
    etat_non_vide(tmp_path)  # openai-deprecations est une source nouvelle : état initial regroupé (amorçage de 180 jours)
    jour_fige(monkeypatch, "2026-11-20")  # J-10 du 30/11 et J-11 du 01/12 : retraits déjà dans l'état initial (annonces du 02 et 03/06)
    _, brut = passage(tmp_path, monkeypatch, "openai")
    propres = [n for n in brut["nouveautes"] if n["source_id"] == "openai-deprecations"]
    (etat,) = propres
    assert etat["titre"] == "État initial des dépréciations OpenAI en cours" and not etat["id"].startswith("echeance-")
    for sujet in ("Reusable prompts", "Evals platform", "Agent Builder", "GPT Image model deprecations"):
        assert sujet in etat["contenu"]
    attendues = {"reusable-prompts-2026-11-30", "evals-platform-2026-11-30", "agent-builder-2026-11-30",
                 "gpt-image-1-mini-2026-12-01", "gpt-image-1-5-2026-12-01", "chatgpt-image-latest-2026-12-01"}
    assert {n["id"] for n in ech(brut)} == {f"echeance-openai-deprecations-{a}-j14" for a in attendues}
    assert not any(i.startswith("echeance-") for i in brut["ignores"]), "les échéances ne partent jamais dans les ignorés"
    # tout ce que la source rapporte : l'état initial en un élément, puis les seules échéances ; aucune annonce répétée
    assert all(n["id"].startswith("echeance-") or n["id"] == etat["id"] for n in brut["nouveautes"] if n["produit"] == "codex" and "deprecations" in n["source_id"])
    # après validation, rien ne revient le lendemain
    valider(tmp_path, monkeypatch, "openai", brut, "2026-11-20")
    jour_fige(monkeypatch, "2026-11-21")
    _, brut2 = passage(tmp_path, monkeypatch, "openai")
    assert ech(brut2) == [] and not [n for n in brut2["nouveautes"] if n["source_id"] == "openai-deprecations"]
    # J-1 : un élément -j1 par retrait
    jour_fige(monkeypatch, "2026-11-29")
    _, brut3 = passage(tmp_path, monkeypatch, "openai")
    assert {n["id"] for n in ech(brut3) if n["id"].endswith("-j1")} == {
        f"echeance-openai-deprecations-{a}-j1" for a in ("reusable-prompts-2026-11-30", "evals-platform-2026-11-30", "agent-builder-2026-11-30")}
    assert {n["id"] for n in ech(brut3) if n["id"].endswith("-j14")} == {
        f"echeance-openai-deprecations-{m}-2026-12-11-j14" for m in (
            "gpt-5-2025-08-07", "gpt-5-mini-2025-08-07", "gpt-5-nano-2025-08-07", "gpt-5-pro-2025-10-06", "o3-2025-04-16", "o3-pro-2025-06-10")}, \
        "les retraits du 11/12 (J-12) entrent à leur tour, une seule fois"


def test_etat_initial_du_02_10_aucune_echeance_a_tort(tmp_path, monkeypatch):
    """Premier passage réel prévu le 02/10 : le retrait de gpt-5.4-cyber (01/10) est passé, le prochain est le 23/10 (J-21)."""
    etat_non_vide(tmp_path)
    jour_fige(monkeypatch, "2026-10-02")
    _, brut = passage(tmp_path, monkeypatch, "openai")
    assert ech(brut) == []
    assert [n["titre"] for n in brut["nouveautes"] if n["source_id"] == "openai-deprecations"] == ["État initial des dépréciations OpenAI en cours"]
    assert ID_CYBER in brut["ignores"]


# --- événement 11 : l'arrêt du 28/09 doit sortir deux fois ----------------------------------------------------------

def test_evenement_11_arret_du_28_09_sort_a_j14_puis_a_j1(tmp_path, monkeypatch):
    etat_non_vide(tmp_path)
    brut = avancer(tmp_path, monkeypatch, "openai", "2026-09-14")
    j14 = {n["id"] for n in ech(brut) if "2026-09-28" in n["id"]}
    assert j14 == {f"echeance-openai-deprecations-{m}-2026-09-28-j14" for m in OPENAI_28_09}
    assert all(n["titre"].endswith("le 2026-09-28 (dans 14 jours)") for n in ech(brut) if "2026-09-28" in n["id"])
    # Sora 2 (24/09, J-10) sort aussi ce jour-là ; gpt-5.4-cyber (01/10, J-17) pas encore
    assert any("sora-2-2026-09-24-j14" in n["id"] for n in ech(brut)) and not any("gpt-5-4-cyber" in n["id"] for n in ech(brut))
    brut2 = avancer(tmp_path, monkeypatch, "openai", "2026-09-27")
    j1 = {n["id"] for n in ech(brut2) if "2026-09-28" in n["id"]}
    assert j1 == {f"echeance-openai-deprecations-{m}-2026-09-28-j1" for m in OPENAI_28_09}
    assert not (j1 & {n["id"] for n in ech(brut)}), "deux événements distincts, deux identifiants"
    assert not any("sora" in n["id"] for n in ech(brut2)), "retrait du 24/09 passé : rien"
    assert any("gpt-5-4-cyber-2026-10-01-j14" in n["id"] for n in ech(brut2)), "J-4 : le retrait du 01/10 entre à son tour"
    brut3 = avancer(tmp_path, monkeypatch, "openai", "2026-09-28")
    assert not [n for n in ech(brut3) if "2026-09-28" in n["id"]], "jour du retrait : rien"


# --- le fichier quotidien d'un élément d'échéance passe `valider.py` -------------------------------------------------

def test_un_element_d_echeance_passe_valider_py_et_fetch_valider(tmp_path, monkeypatch, date_figee):
    import fetch
    import valider as v
    from conftest import FauxClient, ecrire_quotidien
    from test_valider import CONTEXTE
    (tmp_path / "state").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text(encoding="utf-8"))
    mes = {n["id"] for n in brut["nouveautes"] if n["id"].startswith("echeance-")}
    assert any("2026-09-28" in i for i in mes), "au 2026-09-23 (échantillon OpenAI), les retraits du 24/09, 28/09 et 01/10 sortent"
    ecrire_quotidien(tmp_path, "openai", brut, "2026-09-23")  # un élément par nouveauté brute, échéances comprises
    args = ["--racine", str(tmp_path), "--perimetre", "openai", "--contexte", str(tmp_path / "CONTEXTE.md"), "--date", "2026-09-23",
            "--brut", str(tmp_path / "raw" / "openai-nouveautes.json")]
    assert v.main(args) == 0
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--valider", "--date", "2026-09-23"]) == 0
    vus = json.loads((tmp_path / "state" / "openai.json").read_text(encoding="utf-8"))["vus"]
    assert mes <= set(vus)


# --- D71 : résumé léger raw/echeances.json, lisible par la supervision --------------------------------------------

def resume_fichier(tmp_path):
    return json.loads((tmp_path / "raw" / "echeances.json").read_text(encoding="utf-8"))


def test_resume_ecrit_a_chaque_passage_meme_apres_validation(etat_claude, monkeypatch):
    """Les éléments bruts ne sortent qu'une fois ; le résumé, lui, liste tous les retraits de l'horizon à chaque passage."""
    t = etat_claude
    avancer(t, monkeypatch, "claude", "2026-11-16")
    r = resume_fichier(t)
    (e,) = [x for x in r["perimetre"]["claude"] if x["id"] == ID_SONNET_J14]
    assert e["modele_ou_fonction"] == "claude-sonnet-4-5-20250929" and e["date_retrait"] == "2026-11-30"
    assert e["jours_restants"] == 14 and e["palier"] == "j14" and e["source_url"].startswith("https://")
    assert r["statut"] == "ok" and r["raison"] is None and r["horizon_jours"] == 14 and r["releve_le"]
    avancer(t, monkeypatch, "claude", "2026-11-17")  # déjà vue : aucun élément brut, mais le résumé la garde
    (e,) = [x for x in resume_fichier(t)["perimetre"]["claude"] if x["id"] == ID_SONNET_J14]
    assert e["jours_restants"] == 13
    avancer(t, monkeypatch, "claude", "2026-11-29")
    (e,) = [x for x in resume_fichier(t)["perimetre"]["claude"] if x["date_retrait"] == "2026-11-30"]
    assert e["id"] == ID_SONNET_J1 and e["jours_restants"] == 1 and e["palier"] == "j1"


def test_resume_horizon_14_jours_trie_par_date(etat_claude, monkeypatch):
    t = etat_claude
    avancer(t, monkeypatch, "claude", "2026-11-15", valide=False)
    assert resume_fichier(t)["perimetre"]["claude"] == [], "J-15 : hors horizon, fichier écrit quand même (liste vide)"
    avancer(t, monkeypatch, "claude", "2026-11-30", valide=False)
    (e,) = resume_fichier(t)["perimetre"]["claude"]
    assert e["jours_restants"] == 0 and e["palier"] is None and not e["id"].endswith(("-j1", "-j14")), "le jour même : listée, sans palier"
    avancer(t, monkeypatch, "claude", "2026-12-01", valide=False)
    assert resume_fichier(t)["perimetre"]["claude"] == [], "retrait passé : plus listé"
    avancer(t, monkeypatch, "openai", "2026-11-20", valide=False) if False else None


def test_resume_claude_et_openai_dans_un_seul_fichier(tmp_path, monkeypatch):
    from deltalib.etat import ecrire_json
    dossiers(tmp_path)
    for p in ("claude", "openai"):
        ecrire_json(tmp_path / "state" / f"{p}.json", {"version": 1, "maj_le": "2026-11-01T10:00:00+00:00", "vus": {"x": {"source_id": "autre"}}})
    jour_fige(monkeypatch, "2026-11-20")
    passage(tmp_path, monkeypatch, "claude")
    passage(tmp_path, monkeypatch, "openai")
    r = resume_fichier(tmp_path)
    assert sorted(r["perimetre"]) == ["claude", "openai"] and sorted(r["sources"]) == ["claude", "openai"]
    assert [x["date_retrait"] for x in r["perimetre"]["claude"]] == ["2026-11-30"]
    assert {x["date_retrait"] for x in r["perimetre"]["openai"]} >= {"2026-11-30", "2026-12-01"}
    for lignes in r["perimetre"].values():
        assert [x["date_retrait"] for x in lignes] == sorted(x["date_retrait"] for x in lignes)
    passage(tmp_path, monkeypatch, "claude")  # un nouveau passage claude ne touche pas openai
    assert resume_fichier(tmp_path)["perimetre"]["openai"] == r["perimetre"]["openai"]
    assert (tmp_path / "raw" / "echeances.json").stat().st_size < 10_000, "quelques Ko : lisible en entier"


def test_resume_vide_ecrit_sans_signalement_ni_echec(etat_claude, monkeypatch):
    jour_fige(monkeypatch, "2026-10-01")
    passage(etat_claude, monkeypatch, "claude")
    r = resume_fichier(etat_claude)
    assert r["perimetre"]["claude"] == [] and r["statut"] == "ok" and r["raison"] is None
    assert [s for s in r["signalements"] if s["perimetre"] == "claude" and "gabarit" in s["texte"]] == []


def test_resume_en_echec_quand_la_page_n_est_pas_lue(etat_claude, monkeypatch):
    from deltalib.modeles import ErreurReseau
    jour_fige(monkeypatch, "2026-11-16")
    passage(etat_claude, monkeypatch, "claude", {URL_ANTHROPIC: ErreurReseau("HTTP 403 pour " + URL_ANTHROPIC)})
    r = resume_fichier(etat_claude)
    assert r["statut"] == "echec" and "anthropic-deprecations" in r["raison"] and "403" in r["raison"]
    assert r["perimetre"]["claude"] == [], "liste vide : ici elle ne veut pas dire « aucune échéance »"
    assert r["sources"]["claude"]["statut"] == "echec"


def test_resume_reprend_les_signalements_de_lecture(etat_claude, monkeypatch):
    page = PAGE_ANTHROPIC.replace("| November 30, 2026 | `claude-sonnet-4-5-20250929` |", "| soon | `claude-sonnet-4-5-20250929` |")
    jour_fige(monkeypatch, "2026-11-16")
    passage(etat_claude, monkeypatch, "claude", {URL_ANTHROPIC: (page, "text/markdown")})
    r = resume_fichier(etat_claude)
    assert r["statut"] == "ok", "page lue : les trous de lecture sont des signalements, pas un échec"
    assert any("illisible" in s["texte"] and s["perimetre"] == "claude" for s in r["signalements"])


def test_resume_fichier_existant_illisible_est_repris_a_zero(etat_claude, monkeypatch):
    (etat_claude / "raw" / "echeances.json").write_text("{pas du json", encoding="utf-8")
    jour_fige(monkeypatch, "2026-11-16")
    passage(etat_claude, monkeypatch, "claude")
    assert [x["id"] for x in resume_fichier(etat_claude)["perimetre"]["claude"]] == [ID_SONNET_J14]


def test_resume_pas_ecrit_en_dry_run_ni_pour_actu(etat_claude, monkeypatch):
    jour_fige(monkeypatch, "2026-11-16")
    from test_etape_2c import FauxClient, fetch
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({}))
    fetch.main(["--racine", str(etat_claude), "--perimetre", "claude", "--dry-run"])
    assert not (etat_claude / "raw" / "echeances.json").exists()
    from deltalib.etat import ecrire_json
    ecrire_json(etat_claude / "state" / "actu.json", {"version": 1, "maj_le": "2026-11-01T10:00:00+00:00", "vus": {"x": {"source_id": "autre"}}})
    passage(etat_claude, monkeypatch, "actu")
    assert not (etat_claude / "raw" / "echeances.json").exists(), "actu n'a aucune source d'échéances"


def test_resume_n_ajoute_rien_au_brut(etat_claude, monkeypatch):
    jour_fige(monkeypatch, "2026-11-16")
    _, brut = passage(etat_claude, monkeypatch, "claude")
    assert "echeances" not in brut, "le brut garde sa forme : le résumé est un fichier à part"
