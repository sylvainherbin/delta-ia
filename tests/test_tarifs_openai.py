"""O2 (26/09) : https://learn.chatgpt.com/docs/pricing.md suivie par empreinte de section (crédits, parrainage, limites)."""

import json

import pytest

import fetch
from conftest import FIXTURES, FauxClient
from deltalib.analyseurs.html_notes import parser_sections_suivies
from deltalib.modeles import FormatInattendu

PAGE = (FIXTURES / "oa_pricing.md").read_text(encoding="utf-8")
URL = "https://learn.chatgpt.com/docs/pricing.md"


def test_source_declaree(sources):
    s = sources["openai-tarifs"]
    assert s.perimetre == "openai" and s.statut == "a_valider" and s.officielle and s.options["suivre_revisions"]
    assert {c["id"] for c in s.options["sections"]} == {"plans-credits", "parrainage", "limites", "limites-atteintes", "credits"}


def test_sections_extrait_reel(sources):
    es = {e.id: e for e in parser_sections_suivies(PAGE, sources["openai-tarifs"])}
    assert set(es) == {f"openai-tarifs-{k}" for k in ("plans-credits", "parrainage", "limites", "limites-atteintes", "credits")}
    assert all(e.date_publication is None and e.contenu for e in es.values())
    assert "banked rate-limit reset" in es["openai-tarifs-parrainage"].contenu
    assert es["openai-tarifs-parrainage"].url == "https://learn.chatgpt.com/docs/pricing#invite-friends-and-coworkers"
    assert "## " not in es["openai-tarifs-plans-credits"].contenu, "le chapeau s'arrête au premier sous-titre"
    assert "Token rates" in es["openai-tarifs-credits"].contenu, "une section complète garde ses sous-sections"


def test_section_disparue_erreur_explicite(sources):
    with pytest.raises(FormatInattendu, match="Invite friends"):
        parser_sections_suivies(PAGE.replace("## Invite friends and coworkers", "## Refer a friend"), sources["openai-tarifs"])


def test_revision_quand_une_section_change(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    from conftest import ecrire_quotidien
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--depuis", "2026-09-20"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    ids = {n["id"] for n in brut["nouveautes"] if n["source_id"] == "openai-tarifs"}
    assert len(ids) == 5, "premier passage : l'état actuel des sections arrive une fois"
    ecrire_quotidien(tmp_path, "openai", brut, "2026-09-26")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "openai", "--valider", "--date", "2026-09-26"]) == 0
    # rien n'a changé : aucune nouveauté de la page
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    assert not [n for n in brut["nouveautes"] if n["source_id"] == "openai-tarifs"]
    # la promotion de parrainage change : seule cette section revient, en révision
    change = PAGE.replace("From June 11 through June 24, 2026", "From October 1 through October 14, 2026")
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({URL: (change, "text/markdown")}))
    fetch.main(["--racine", str(tmp_path), "--perimetre", "openai"])
    brut = json.loads((tmp_path / "raw" / "openai-nouveautes.json").read_text())
    rev = [n for n in brut["nouveautes"] if n["source_id"] == "openai-tarifs"]
    assert [(n["id"], n.get("revision")) for n in rev] == [("openai-tarifs-parrainage", True)]
