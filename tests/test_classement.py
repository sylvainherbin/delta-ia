"""Classement préalable de la veille sur la clé « delta » (A1) : modes batch, direct, aucun ; coût par jour ; replis dits."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import classement as cl

JOUR = "2026-10-16"
NOUVEAUTES = [
    {"id": "cc-2.1.300", "produit": "claude-code", "titre": "Claude Code 2.1.300", "version": "2.1.300",
     "date_publication": JOUR, "url": "https://example.test/cc", "contenu": "x" * 3000, "source_id": "cc-changelog",
     "officielle": True, "revision": False},
    {"id": "web-abc", "produit": "actu", "titre": "Procès", "version": None, "date_publication": None,
     "url": "https://example.test/w", "contenu": "procès", "source_id": "web", "officielle": False, "revision": False},
]
REPONSE = {"classement": [
    {"id": "cc-2.1.300", "verdict": "moyen", "pourquoi": "Tu utilises Claude Code sur delta-ia."},
    {"id": "web-abc", "verdict": "ecarte", "pourquoi": "Sans rapport avec les outils IA."}]}


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    (tmp_path / "CONTEXTE.md").write_text("# Contexte\n### 2.6 discipline\n", encoding="utf-8")
    (tmp_path / "profil.yaml").write_text("priorites: []\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "claude-nouveautes.json").write_text(json.dumps({"nouveautes": NOUVEAUTES}), encoding="utf-8")
    return tmp_path


def cfg(mode: str) -> dict:
    return {**cl.charger_config(), "mode": mode, "claude_cle": "/faux/claude-cle", "intervalle_s": 1}


def sortie(racine: Path, perimetre: str = "claude", jour: str = JOUR) -> dict:
    return json.loads(cl.chemin_sortie(racine, jour, perimetre).read_text(encoding="utf-8"))


class FauxA1:
    """Faux `credits_api` : soumettre_lot(requetes, usage=…) -> id ; relever_lot(id, usage=…) -> None puis résultats."""

    def __init__(self, pret_apres: int = 0, cout: float | None = 0.0123, texte: str | None = None):
        self.requetes, self.releves, self.pret_apres, self.cout = [], 0, pret_apres, cout
        self.texte = json.dumps(REPONSE) if texte is None else texte

    def soumettre_lot(self, requetes, usage=None):
        assert usage == "veille-delta-ia"
        self.requetes.append(requetes)
        return {"id": f"lot-{len(self.requetes)}"}

    def relever_lot(self, lot, usage=None):
        self.releves += 1
        if self.releves <= self.pret_apres:
            return None
        res = [{"custom_id": r["custom_id"], "result": {"type": "succeeded", "message": {
            "content": [{"type": "text", "text": f"```json\n{self.texte}\n```"}]}}} for r in self.requetes[-1]]
        if self.cout is not None:
            for r in res:
                r["cout_usd"] = self.cout
        return res


def test_config_livree_desactivee():
    """Réglage réversible : livré à « aucun » tant que Delta-pilote n'a pas présenté la première dépense."""
    c = cl.charger_config()
    assert c["mode"] == "aucun" and c["usage"] == "veille-delta-ia"


def test_aucun_n_ecrit_rien(racine, capsys):
    assert cl.soumettre(racine, cfg("aucun"), "claude", JOUR) == 0
    assert not (racine / cl.DOSSIER).exists()
    assert "désactivé" in capsys.readouterr().out


def test_batch_soumet_puis_releve(racine):
    a1 = FauxA1(pret_apres=1)
    fab = lambda: cl.LotA1(cfg("batch"), racine, module=a1)
    assert cl.soumettre(racine, cfg("batch"), "claude", JOUR, lot_a1_fabrique=fab) == 0
    doc = sortie(racine)
    assert doc["statut"] == "en_cours" and doc["lot"] == "lot-1"
    req = a1.requetes[0][0]
    assert req["custom_id"] == f"{JOUR}-claude"
    assert req["params"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "# CONTEXTE.md" in req["params"]["system"][0]["text"]
    assert "x" * 1500 + " […]" in req["params"]["messages"][0]["content"]  # contenu tronqué à contenu_max
    t = [0.0]
    code = cl.relever(racine, cfg("batch"), "claude", JOUR, attendre_s=10, lot_a1=fab(),
                      dormir=lambda s: t.__setitem__(0, t[0] + s), horloge=lambda: t[0])
    assert code == 0
    doc = sortie(racine)
    assert doc["statut"] == "ok" and doc["cout_usd"] == 0.0123 and doc["cout_statut"] == "mesure"
    assert [e["verdict"] for e in doc["classement"]] == ["moyen", "ecarte"] and doc["manquants"] == []


def test_batch_non_termine_en_attente_puis_releve_au_passage_suivant(racine):
    a1 = FauxA1(pret_apres=100)
    fab = lambda: cl.LotA1(cfg("batch"), racine, module=a1)
    cl.soumettre(racine, cfg("batch"), "claude", JOUR, lot_a1_fabrique=fab)
    t = [0.0]
    assert cl.relever(racine, cfg("batch"), "claude", JOUR, attendre_s=3, lot_a1=fab(),
                      dormir=lambda s: t.__setitem__(0, t[0] + s), horloge=lambda: t[0]) == 0
    assert sortie(racine)["statut"] == "en_attente"
    # Passage suivant : le lot de la veille est relevé d'abord (A1 ne le compte qu'au relevé).
    a1.pret_apres = 0
    cl.soumettre(racine, cfg("batch"), "claude", "2026-10-17", lot_a1_fabrique=fab)
    assert sortie(racine)["statut"] == "ok"
    assert sortie(racine, jour="2026-10-17")["lot"] == "lot-2"


def test_batch_a1_absent_echec_dit(racine, tmp_path):
    c = {**cfg("batch"), "a1_src": str(tmp_path / "absent")}
    assert cl.soumettre(racine, c, "claude", JOUR) == 1
    doc = sortie(racine)
    assert doc["statut"] == "echec" and "A1 introuvable" in doc["raison"]


def test_batch_cout_non_mesure_jamais_zero(racine):
    a1 = FauxA1(cout=None)
    fab = lambda: cl.LotA1(cfg("batch"), racine, module=a1)
    cl.soumettre(racine, cfg("batch"), "claude", JOUR, lot_a1_fabrique=fab)
    cl.relever(racine, cfg("batch"), "claude", JOUR, attendre_s=0, lot_a1=fab())
    doc = sortie(racine)
    assert doc["statut"] == "ok" and doc["cout_usd"] is None and doc["cout_statut"] == "non_mesure"
    assert cl.couts(racine, 7, date(2026, 10, 16)) == [
        {"date": JOUR, "cout_usd": 0.0, "appels": 1, "non_mesures": 1}]


def test_batch_signature_inattendue(racine):
    module = SimpleNamespace(soumettre_lot=lambda a, b, c: "x", relever_lot=lambda lot: None)
    fab = lambda: cl.LotA1(cfg("batch"), racine, module=module)
    assert cl.soumettre(racine, cfg("batch"), "claude", JOUR, lot_a1_fabrique=fab) == 1
    assert "signature inattendue" in sortie(racine)["raison"]


def faux_claude_cle(code=0, sortie_json=None, vus=None):
    def executer(cmd, input, **kw):
        if vus is not None:
            vus.append((cmd, input))
        doc = sortie_json if sortie_json is not None else {
            "type": "result", "subtype": "success", "is_error": False, "result": json.dumps(REPONSE),
            "total_cost_usd": 0.0456}
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(doc), stderr="")
    return executer


def test_direct_passe_par_claude_cle_et_mesure(racine):
    vus = []
    assert cl.soumettre(racine, cfg("direct"), "claude", JOUR, executer=faux_claude_cle(vus=vus)) == 0
    cmd, entree = vus[0]
    assert cmd == ["/faux/claude-cle", "--usage", "veille-delta-ia", "--model", "claude-sonnet-5-5"]
    assert "# CONTEXTE.md" in entree and "cc-2.1.300" in entree
    doc = sortie(racine)
    assert doc["statut"] == "ok" and doc["cout_usd"] == 0.0456 and doc["cout_statut"] == "mesure"


def test_direct_solde_epuise_code_5(racine):
    assert cl.soumettre(racine, cfg("direct"), "claude", JOUR, executer=faux_claude_cle(code=5, sortie_json={})) == 5
    assert sortie(racine)["statut"] == "solde_epuise"


def test_direct_reponse_hors_format(racine):
    s = {"is_error": False, "result": "je ne sais pas", "total_cost_usd": 0.01}
    assert cl.soumettre(racine, cfg("direct"), "claude", JOUR, executer=faux_claude_cle(sortie_json=s)) == 1
    assert sortie(racine)["statut"] == "echec"


def test_analyser_ecarte_le_hors_format():
    texte = json.dumps({"classement": [
        {"id": "a", "verdict": "fort", "pourquoi": "ok"}, {"id": "a", "verdict": "nul", "pourquoi": "double"},
        {"id": "b", "verdict": "énorme", "pourquoi": "x"}, {"id": "z", "verdict": "nul", "pourquoi": "x"},
        {"id": "c", "verdict": "nul", "pourquoi": " "}]})
    retenus, manquants, anomalies = cl.analyser(texte, ["a", "b", "c", "d"])
    assert [e["id"] for e in retenus] == ["a"]
    assert manquants == ["b", "c", "d"] and len(anomalies) == 4


def test_rien_a_classer(racine):
    (racine / "raw" / "actu-nouveautes.json").write_text(json.dumps({"nouveautes": []}), encoding="utf-8")
    assert cl.soumettre(racine, cfg("direct"), "actu", JOUR, executer=faux_claude_cle()) == 0
    assert not cl.chemin_sortie(racine, JOUR, "actu").exists()


def test_couts_par_jour(racine):
    cl.soumettre(racine, cfg("direct"), "claude", JOUR, executer=faux_claude_cle())
    (racine / "raw" / "actu-nouveautes.json").write_text(json.dumps({"nouveautes": NOUVEAUTES}), encoding="utf-8")
    cl.soumettre(racine, cfg("direct"), "actu", JOUR, executer=faux_claude_cle())
    cl.soumettre(racine, cfg("direct"), "claude", "2026-10-01", executer=faux_claude_cle())  # hors fenêtre
    assert cl.couts(racine, 7, date(2026, 10, 16)) == [
        {"date": JOUR, "cout_usd": 0.0912, "appels": 2, "non_mesures": 0}]


def test_skill_delta_cite_le_classement():
    skill = (Path(cl.RACINE) / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/classement.py soumettre --perimetre p" in skill
    assert "scripts/classement.py relever --perimetre p" in skill
    reglages = json.loads((Path(cl.RACINE) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Bash(.venv/bin/python scripts/classement.py *)" in reglages["permissions"]["allow"]
