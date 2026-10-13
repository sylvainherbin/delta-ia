"""Relevé continu de l'état des fournisseurs (scripts/etat_fournisseurs.py) sur des réponses enregistrées.

Les réponses sont celles des échantillons réels de `tests/fixtures` (status.openai.com, status.claude.com, 01/10/2026),
modifiées ici pour jouer ouverture, changement d'impact et résolution ; aucun accès réseau, aucun `operer`.
"""

import json
from copy import deepcopy

import pytest

import etat_fournisseurs as ef
from conftest import FIXTURES, FauxClient
from deltalib.modeles import ErreurReseau

OPENAI = json.loads((FIXTURES / "status_openai_incidents.json").read_text(encoding="utf-8"))
CLAUDE = json.loads((FIXTURES / "status_claude_incidents.json").read_text(encoding="utf-8"))
T0, T1, T2 = "2026-10-13T12:00:00Z", "2026-10-13T12:10:00Z", "2026-10-13T12:20:00Z"


def resoudre(donnees):
    """Copie où tout incident encore ouvert est résolu : base « calme » à laquelle on ajoute un incident à la fois."""
    d = deepcopy(donnees)
    for it in d["incidents"]:
        if it["status"] != "resolved":
            it["status"], it["resolved_at"] = "resolved", "2026-10-01T05:00:00Z"
    return d


def incident(id_, nom, statut="investigating", impact="major", cree="2026-10-13T10:10:00Z", composants=()):
    return {"id": id_, "name": nom, "status": statut, "impact": impact, "created_at": cree, "updated_at": cree,
            "incident_updates": [], "components": [{"name": c} for c in composants]}


class Faux(FauxClient):
    """Client dont le contenu de chaque page d'état se change entre deux relevés."""

    def __init__(self, sources):
        self.sources = sources
        self.pages = {}

    def regler(self, nom, donnees):
        self.pages[ef.FOURNISSEURS[nom]] = donnees

    def get(self, url, accept=None):
        from deltalib.http import Reponse
        for id_source, donnees in self.pages.items():
            if self.sources[id_source].url == url:
                if isinstance(donnees, Exception):
                    raise donnees
                texte = donnees if isinstance(donnees, str) else json.dumps(donnees)
                return Reponse(url, 200, "application/json", texte)
        raise AssertionError(url)


@pytest.fixture
def banc(sources):
    faux = Faux(sources)
    faux.regler("openai", resoudre(OPENAI))
    faux.regler("anthropic", resoudre(CLAUDE))
    messages = []

    def passer(maintenant, precedent=None, envoyer=None):
        return ef.releve(sources, faux, precedent or {}, maintenant, envoyer=envoyer or messages.append)

    return faux, messages, passer


def ouverts(doc, nom):
    return {i["id"]: i for i in doc["fournisseurs"][nom]["incidents_ouverts"]}


def test_premier_releve_amorce_sans_message(banc):
    faux, messages, passer = banc
    d = deepcopy(OPENAI)  # l'échantillon du 01/10 a des incidents encore ouverts
    faux.regler("openai", d)
    doc, code = passer(T0)
    assert code == 0 and messages == [] and doc["message_en_attente"] is None
    assert doc["fournisseurs"]["openai"]["derniere_lecture_ok"] == T0
    assert any(i["statut"] != "resolved" for i in doc["fournisseurs"]["openai"]["incidents_ouverts"])


def test_ouverture_codex_envoie_un_message_et_remplit_le_fichier(banc):
    faux, messages, passer = banc
    doc0, _ = passer(T0)
    assert ouverts(doc0, "openai") == {} and ouverts(doc0, "anthropic") == {}
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Degraded performance in GPT-6.1 Sol Codex and Work mode",
                                         statut="monitoring", impact="minor"))
    faux.regler("openai", page)
    doc1, code = passer(T1, doc0)
    assert code == 0 and len(messages) == 1
    assert messages[0].startswith("[ÉTAT FOURNISSEURS] OUVERT 13/10 12:10 Paris")  # 10:10 UTC = 12:10 à Paris (été)
    assert "OpenAI" in messages[0] and "(codex)" in messages[0] and "impact minor" in messages[0]
    assert "https://status.openai.com/incidents/INC1" in messages[0]
    i = ouverts(doc1, "openai")["INC1"]
    assert i["produits"] == ["codex"] and i["impact"] == "minor" and i["statut"] == "monitoring"
    assert i["ouvert_le"] == "2026-10-13T10:10:00Z" and i["lien"] == "https://status.openai.com/incidents/INC1"
    assert doc1["message_en_attente"] is None


def test_pas_de_message_a_chaque_passage(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex"))
    faux.regler("openai", page)
    doc, _ = passer(T1, doc)
    doc, _ = passer(T2, doc)
    assert len(messages) == 1


def test_changement_d_impact_puis_resolution(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex", impact="minor"))
    faux.regler("openai", page)
    doc, _ = passer(T1, doc)
    page["incidents"][0]["impact"] = "major"
    doc, _ = passer(T2, doc)
    assert len(messages) == 2 and "IMPACT minor → major" in messages[1]
    page["incidents"][0].update(status="resolved", resolved_at="2026-10-13T11:00:00Z")
    doc, _ = passer("2026-10-13T12:30:00Z", doc)
    assert len(messages) == 3 and messages[2].startswith("[ÉTAT FOURNISSEURS] RÉSOLU (résolu (resolved))")
    assert ouverts(doc, "openai") == {}


def test_incident_ramene_a_none_compte_comme_sorti(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex", impact="minor"))
    faux.regler("openai", page)
    doc, _ = passer(T1, doc)
    page["incidents"][0]["impact"] = "none"
    doc, _ = passer(T2, doc)
    assert "impact ramené à none" in messages[-1] and ouverts(doc, "openai") == {}


def test_claude_code_et_api_sont_suivis_mais_pas_chatgpt_ni_claude_ai(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(CLAUDE)
    page["incidents"].insert(0, incident("C1", "Elevated errors on Claude Code", composants=["Claude Code"]))
    page["incidents"].insert(0, incident("C2", "Elevated errors on the API", composants=["Claude API (api.anthropic.com)"]))
    page["incidents"].insert(0, incident("C3", "Login failures on claude.ai", composants=["claude.ai"]))
    page["incidents"].insert(0, incident("C4", "Elevated errors on platform.claude.com",
                                         composants=["Claude Console (platform.claude.com)"]))
    faux.regler("anthropic", page)
    autre = resoudre(OPENAI)
    autre["incidents"].insert(0, incident("O1", "Elevated error rates for ChatGPT"))
    faux.regler("openai", autre)
    doc, _ = passer(T1, doc)
    assert len(messages) == 1
    texte = messages[0]
    assert "C1" in texte and "C2" in texte and "C3" not in texte and "C4" not in texte and "O1" not in texte
    o = ouverts(doc, "anthropic")
    assert o["C1"]["produits"] == ["claude-code"] and o["C2"]["produits"] == ["api"]
    assert o["C3"]["produits"] == ["claude.ai"] and o["C4"]["produits"] == ["claude"]
    assert ouverts(doc, "openai")["O1"]["produits"] == ["chatgpt"]


def test_produits_multiples_reprennent_toutes_les_regles(sources):
    s = sources["openai-status"]
    assert ef.produits_de("Elevated errors across ChatGPT, Codex, and the API", [], s) == ["codex", "api", "chatgpt"]
    assert ef.produits_de("Elevated latency for some API requests", [], s) == ["api"]
    assert ef.produits_de("Something odd", [], s) == ["chatgpt"]  # sans correspondance : produit de la source


def test_incident_d_impact_none_a_l_ouverture_est_ignore(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex", impact="none"))
    faux.regler("openai", page)
    doc, _ = passer(T1, doc)
    assert messages == [] and ouverts(doc, "openai") == {}
    page["incidents"][0]["impact"] = "minor"  # il arrive au relevé où son impact change
    doc, _ = passer(T2, doc)
    assert len(messages) == 1 and "INC1" in ouverts(doc, "openai")


@pytest.mark.parametrize("panne, motif", [
    (ErreurReseau("HTTP 503 pour https://status.openai.com/api/v2/incidents.json"), "HTTP 503"),
    ("<html><body>Just a moment...</body></html>", "JSON invalide"),
    ({"incidents": []}, "vide"),
    ({"page": {}}, "incidents"),
])
def test_page_en_echec_garde_les_incidents_et_n_en_resout_aucun(banc, panne, motif):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex"))
    faux.regler("openai", page)
    doc, _ = passer(T1, doc)
    assert len(messages) == 1
    faux.regler("openai", panne)
    doc, code = passer(T2, doc)
    f = doc["fournisseurs"]["openai"]
    assert code == 1 and f["lecture"] == "echec" and motif in f["erreur"] and f["echecs_consecutifs"] == 1
    assert "INC1" in ouverts(doc, "openai") and f["derniere_lecture_ok"] == T1  # aucun « résolu » fantôme
    assert len(messages) == 1
    assert doc["fournisseurs"]["anthropic"]["lecture"] == "ok"  # l'autre fournisseur est lu quand même


def test_injoignable_prolonge_envoie_un_seul_message_puis_se_remet(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    faux.regler("openai", ErreurReseau("HTTP 503"))
    for n in range(ef.SEUIL_INJOIGNABLE + 3):
        doc, _ = passer(f"2026-10-13T13:{n:02d}:00Z", doc)
    assert len(messages) == 1 and "injoignable" in messages[0] and "OpenAI" in messages[0]
    assert doc["fournisseurs"]["openai"]["echecs_consecutifs"] == ef.SEUIL_INJOIGNABLE + 3
    faux.regler("openai", resoudre(OPENAI))
    doc, code = passer("2026-10-13T14:00:00Z", doc)
    f = doc["fournisseurs"]["openai"]
    assert code == 0 and f["lecture"] == "ok" and f["echecs_consecutifs"] == 0 and f["alerte_injoignable"] is False


def test_premiere_lecture_en_echec_puis_reussie_n_inonde_pas(banc):
    faux, messages, passer = banc
    faux.regler("openai", ErreurReseau("HTTP 503"))
    doc, code = passer(T0)
    assert code == 1 and doc["fournisseurs"]["openai"]["derniere_lecture_ok"] is None
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex"))
    faux.regler("openai", page)
    doc, code = passer(T1, doc)
    assert code == 0 and messages == [] and "INC1" in ouverts(doc, "openai")  # amorçage, pas d'ouverture annoncée


def test_message_refuse_est_garde_et_renvoye_au_releve_suivant(banc):
    faux, messages, passer = banc
    doc, _ = passer(T0)
    page = resoudre(OPENAI)
    page["incidents"].insert(0, incident("INC1", "Elevated errors in Codex"))
    faux.regler("openai", page)

    def refuse(texte):
        raise RuntimeError("operer indisponible")

    doc, _ = passer(T1, doc, envoyer=refuse)
    assert doc["message_en_attente"] and "INC1" in doc["message_en_attente"] and messages == []
    doc, _ = passer(T2, doc)  # même état, plus de changement : seul le message gardé part
    assert len(messages) == 1 and "INC1" in messages[0] and doc["message_en_attente"] is None
    doc, _ = passer("2026-10-13T12:30:00Z", doc)
    assert len(messages) == 1


def test_sans_message_ne_perd_pas_le_message_en_attente(sources):
    faux = Faux(sources)
    faux.regler("openai", resoudre(OPENAI))
    faux.regler("anthropic", resoudre(CLAUDE))
    doc, _ = ef.releve(sources, faux, {"message_en_attente": "gardé"}, T1, envoyer=lambda t: pytest.fail("envoi"), avec_message=False)
    assert doc["message_en_attente"] == "gardé"


def test_main_ecrit_le_fichier_et_relit_l_etat_precedent(sources, tmp_path, monkeypatch):
    faux = Faux(sources)
    faux.regler("openai", resoudre(OPENAI))
    faux.regler("anthropic", resoudre(CLAUDE))
    monkeypatch.setattr(ef, "Client", lambda: faux)
    sortie = tmp_path / "etat" / "etat-fournisseurs.json"
    assert ef.main(["--sortie", str(sortie), "--sans-message"]) == 0
    doc = json.loads(sortie.read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and set(doc["fournisseurs"]) == {"openai", "anthropic"}
    assert not list(sortie.parent.glob("*.tmp"))
    assert ef.charger_precedent(sortie)["fournisseurs"]["openai"]["lecture"] == "ok"
    sortie.write_text("pas du json", encoding="utf-8")
    assert ef.charger_precedent(sortie) == {}  # état illisible : on repart d'un amorçage, sans planter


def test_ecriture_impossible_donne_le_code_2(sources, tmp_path, monkeypatch, capsys):
    faux = Faux(sources)
    faux.regler("openai", resoudre(OPENAI))
    faux.regler("anthropic", resoudre(CLAUDE))
    monkeypatch.setattr(ef, "Client", lambda: faux)
    (tmp_path / "bloque").write_text("fichier", encoding="utf-8")
    assert ef.main(["--sortie", str(tmp_path / "bloque" / "etat.json"), "--sans-message"]) == 2
    assert "écriture impossible" in capsys.readouterr().err
