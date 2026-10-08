"""Relevé hebdomadaire du serveur MCP (scripts/mcp_stats.py) sur une réponse /stats de référence."""

import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mcp_stats as m  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp" / "stats.json"
STATS = json.loads(FIXTURE.read_text(encoding="utf-8"))
AUJOURDHUI = date(2026, 10, 14)  # mercredi : la semaine écoulée est 2026-W41 (05/10 au 11/10)


def test_semaine_ecoulee_et_bornes():
    assert m.semaine_ecoulee(AUJOURDHUI) == "2026-W41"
    assert m.semaine_ecoulee(date(2026, 10, 12)) == "2026-W41"  # lundi : la semaine qui vient de finir
    assert m.semaine_ecoulee(date(2027, 1, 4)) == "2026-W53"
    assert m.lundi_de("2026-W41") == date(2026, 10, 5)
    assert m.jours_a_lire(m.lundi_de("2026-W41"), AUJOURDHUI) == 17  # du lundi de la semaine précédente à aujourd'hui
    assert m.jours_a_lire(m.lundi_de("2026-W30"), AUJOURDHUI) == 90
    assert m.jours_a_lire(m.lundi_de("2026-W42"), AUJOURDHUI) == 14
    for faux in ("2026-41", "2026-W54", "W41", ""):
        with pytest.raises(ValueError):
            m.lundi_de(faux)


def test_cumul_de_la_semaine_et_de_la_precedente():
    cette = m.cumuler(STATS, m.lundi_de("2026-W41"))
    assert cette["outils"] == {"chercher_reference": 10, "fiche_reference": 2, "a_tester": 1, "inconnu": 1}
    assert cette["zero"] == {"chercher_reference": 2}
    assert cette["clients"] == {"claude-ai": 2, "codex-mcp-client": 1}
    assert cette["jours_lus"] == 7
    avant = m.cumuler(STATS, m.lundi_de("2026-W40"))
    assert avant["outils"] == {"chercher_reference": 4, "etat_versions": 1, "resume_du_jour": 2}
    assert avant["jours_lus"] == 7


def test_rapport_compare_et_signale_le_signal_prioritaire():
    texte = m.rapport(STATS, "2026-W41", AUJOURDHUI)
    compact = re.sub(r" +", " ", texte)
    assert texte.splitlines()[0] == "Serveur MCP Delta — semaine 2026-W41 (05/10 au 11/10), comparée à 2026-W40"
    assert "Appels d'outils : 14 (préc. 7, +7)" in texte
    assert "chercher_reference 10 (préc. 4, +6)" in compact
    assert "resume_du_jour 0 (préc. 2, -2)" in compact
    assert "Erreurs :\n fiche_reference 1 (préc. 0, +1)" in compact
    assert "chercher_reference sans résultat 2 fois sur 10 (20 %)" in texte
    assert "! " not in texte  # semaine terminée, 14 jours présents


def test_rapport_signale_semaine_partielle_et_jours_absents():
    partiel = {"statut": "ok", "jours": [j for j in STATS["jours"] if j["jour"] >= "2026-10-06"]}
    texte = m.rapport(partiel, "2026-W42", date(2026, 10, 14))
    assert "! Semaine non terminée : relevé partiel" in texte
    assert "! Jours absents de la réponse : 4 sur la semaine, 1 sur la précédente" in texte


class Reponse:
    def __init__(self, corps, erreur=False):
        self._corps, self._erreur = corps, erreur

    def json(self):
        if self._erreur:
            raise ValueError("pas du json")
        return self._corps


def test_lire_stats_refuse_inactif_erreur_et_illisible(monkeypatch):
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Reponse({"statut": "inactif"}))
    with pytest.raises(m.Indisponible, match="compteur inactif"):
        m.lire_stats("https://h", 14)
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Reponse({"statut": "erreur", "raison": "stockage illisible"}))
    with pytest.raises(m.Indisponible, match="stockage illisible"):
        m.lire_stats("https://h", 14)
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Reponse(None, erreur=True))
    with pytest.raises(m.Indisponible, match="illisible"):
        m.lire_stats("https://h", 14)

    def injoignable(*a, **k):
        raise m.requests.ConnectionError("détail à ne pas afficher")
    monkeypatch.setattr(m.requests, "get", injoignable)
    with pytest.raises(m.Indisponible) as e:
        m.lire_stats("https://h", 14)
    assert "détail" not in str(e.value)


def test_hote_lu_dans_contexte(tmp_path):
    ligne = "| Connecteur | `claude mcp add --transport http delta-ia https://delta-mcp-ruddy.vercel.app/mcp` |"
    assert m.hote_depuis_contexte(ligne) == "https://delta-mcp-ruddy.vercel.app"
    assert m.hote_depuis_contexte("rien") is None
    assert m.url_de_base("https://x.exemple/", tmp_path) == "https://x.exemple"
    with pytest.raises(m.Indisponible, match="--url"):
        m.url_de_base(None, tmp_path)
    (tmp_path / "CONTEXTE.md").write_text(ligne, encoding="utf-8")
    assert m.url_de_base(None, tmp_path) == "https://delta-mcp-ruddy.vercel.app"


def test_contexte_reel_donne_un_hote():
    assert m.hote_depuis_contexte((m.RACINE / "CONTEXTE.md").read_text(encoding="utf-8")) == "https://delta-mcp-ruddy.vercel.app"


def test_main_imprime_le_releve_sans_ecrire(monkeypatch, capsys, tmp_path):
    vus = {}

    def faux_get(url, params=None, **k):
        vus.update(url=url, params=params)
        return Reponse(STATS)
    monkeypatch.setattr(m.requests, "get", faux_get)
    monkeypatch.chdir(tmp_path)
    assert m.main(["--url", "https://h"], AUJOURDHUI) == 0
    assert vus == {"url": "https://h/stats", "params": {"jours": 17}}
    assert "semaine 2026-W41" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_main_code_1_quand_inactif(monkeypatch, capsys):
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Reponse({"statut": "inactif"}))
    assert m.main(["--url", "https://h", "--semaine", "2026-W41"], AUJOURDHUI) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "Relevé impossible : compteur inactif" in captured.err


def test_main_refuse_une_semaine_mal_formee(capsys):
    with pytest.raises(SystemExit) as e:
        m.main(["--url", "https://h", "--semaine", "2026-41"], AUJOURDHUI)
    assert e.value.code == 2
