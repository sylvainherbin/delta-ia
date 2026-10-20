"""Catalogue public factorisé : couverture, faits corrigés, provenance et validation."""
import json
import shutil
import subprocess
import sys

import pytest
import valider
from conftest import RACINE
from deltalib.kb import fiches_modeles as fm


@pytest.fixture
def depot(tmp_path):
    shutil.copytree(RACINE / "kb-modeles", tmp_path / "kb-modeles")
    return tmp_path


def rapport(racine):
    r = valider.Rapport()
    valider.verifier_modeles(racine, r)
    return r


def test_couverture_et_factorisation():
    d = fm.construire_modeles(RACINE)
    assert d["schema_version"] == 2
    assert len(d["modeles"]) == d["total_modeles"] == 17
    assert len(d["entrees"]) == d["total"] == 63
    assert len({e["id"] for e in d["entrees"]}) == 63
    for e in d["entrees"]:
        assert e["modele"] in d["modeles"]
        assert not {"benchmarks", "points_forts", "constats_internes", "aliases"} & e.keys()
        assert e["cout_quota"]["poids_relatif"] is None
    assert len(json.dumps(d).encode()) < 500_000
    assert not (RACINE / "docs/data/modeles.json").exists()


def test_faits_corriges_et_inconnus_non_inventes():
    m = fm.construire_modeles(RACINE)["modeles"]
    opus = m["claude-opus-5-5"]["benchmarks"]
    assert all(b["effort_mesure"] == "max" for b in opus if b["nom"] not in {"Terminal-Bench 4.0", "AA-Briefcase v1.1"})
    assert next(b for b in opus if b["nom"] == "Terminal-Bench 4.0")["comparaisons"] == "Opus 5 : 52.3%"
    assert m["gemini-4-argon"]["date_sortie"] == "2026-10-13"
    assert m["gemini-4-argon"]["sortie_max_jetons"] is None
    assert m["claude-fable-5-1"]["date_sortie"] is None
    assert m["gpt-6-astra"]["date_sortie"] is None
    assert m["gpt-6.1-sol"]["effort_defaut_modele"] == "low"
    assert m["gpt-6.1-sol"]["effort_defaut_portee"] == "catalogue-codex"
    assert "API : medium" in m["gpt-6.1-sol"]["effort_defaut_detail"]
    assert "API : high" in m["claude-sonnet-5-5"]["effort_defaut_detail"]
    assert m["gpt-6.1-sol"]["tarifs_credits"]["entree"] == 50
    assert "ne détermine pas seul" in m["gpt-6.1-sol"]["tarifs_credits"]["note"]
    assert m["antigravity-claude-sonnet-5-5"]["prix_api"]["portee"] == "api-anthropic-directe-modele-sous-jacent"
    assert m["gpt-oss-20b"]["sortie_max_jetons"] == 131072
    qwen = m["Qwen3.5-4B"]["benchmarks"]
    assert next(b for b in qwen if b["nom"] == "LiveCodeBench v6")["valeur"] == 55.8
    for modele in m.values():
        for b in modele["benchmarks"]:
            assert b["verifie"] is True and b["extrait"] and b["url"].startswith("https://")
    assert any("21 min" in s["constat"] for s in m["antigravity-claude-sonnet-5-5"]["sources_internes"])


def test_fichier_a_jour_et_sans_fuite():
    assert rapport(RACINE).ok
    contenu = fm.chemin_kb_modeles(RACINE).read_text()
    assert json.loads(contenu) == fm.construire_modeles(RACINE)
    assert "/home/" not in contenu and "cc-socks" not in contenu
    assert "*(défaut)*" not in contenu and "*(source" not in contenu


def test_validation_absence_desynchronisation_fuite(depot):
    assert not rapport(depot).ok
    fm.ecrire_modeles(depot)
    assert rapport(depot).ok
    p = fm.chemin_kb_modeles(depot)
    texte = p.read_text()
    p.write_text(texte.replace("Claude Haiku 5.5", "modification"))
    assert any("catalogue.py modeles" in e for e in rapport(depot).erreurs)
    p.write_text(texte.replace("Claude Haiku 5.5", "/home/personne/secret"))
    assert any("/home/" in e for e in rapport(depot).erreurs)
    p.write_text(texte)
    d = json.loads(texte); d["entrees"][0]["modele"] = "absent"
    p.write_text(json.dumps(d))
    assert any("modèle absent" in e for e in rapport(depot).erreurs)


def test_absence_hors_catalogue_acceptee(tmp_path):
    assert rapport(tmp_path).ok


def test_commande_et_generation_deterministe(depot):
    cmd = [sys.executable, str(RACINE / "scripts/catalogue.py"), "modeles", "--racine", str(depot)]
    sec = subprocess.run([*cmd, "--dry-run"], capture_output=True, text=True)
    assert sec.returncode == 0 and not fm.chemin_kb_modeles(depot).exists()
    reel = subprocess.run(cmd, capture_output=True, text=True)
    assert reel.returncode == 0, reel.stderr
    avant = fm.chemin_kb_modeles(depot).read_bytes()
    fm.ecrire_modeles(depot)
    assert fm.chemin_kb_modeles(depot).read_bytes() == avant
    assert not (depot / "docs/data/modeles.json").exists()


def test_accueil_et_fichiers_legers_intacts():
    for n in ("recent.json", "a-tester.json", "noms.json"):
        assert "modele-claude-" not in (RACINE / "docs/data/kb" / n).read_text()
