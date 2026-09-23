"""Ligne de commande : options obligatoires, validation des arguments, cas d'erreur."""

import pytest

import fetch


def test_perimetre_obligatoire_et_restreint():
    with pytest.raises(SystemExit) as e:
        fetch.main([])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        fetch.main(["--perimetre", "codex"])


def test_depuis_doit_etre_une_date():
    with pytest.raises(SystemExit):
        fetch.main(["--perimetre", "claude", "--depuis", "23/09/2026"])


def test_valider_sans_fichier_en_attente(tmp_path, capsys):
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider"]) == 2
    assert "aucun fichier de nouveautés" in capsys.readouterr().err


def test_valider_refuse_un_fichier_d_un_autre_perimetre(tmp_path, capsys):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "claude-nouveautes.json").write_text('{"perimetre": "actu", "nouveautes": [], "ignores": []}')
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--valider"]) == 2


def test_sources_yaml_invalide(tmp_path, capsys):
    yml = tmp_path / "s.yaml"
    yml.write_text("sources:\n  - id: x\n    perimetre: claude\n    produit: claude\n    type: inconnu\n    url: https://a\n    statut: ok\n")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--sources", str(yml)]) == 2
    assert "type inconnu" in capsys.readouterr().err


def test_statuts_bloque_et_desactive_ignores(tmp_path, capsys):
    yml = tmp_path / "s.yaml"
    yml.write_text("sources:\n  - {id: a, perimetre: actu, produit: actu, type: rss, url: https://a, statut: bloque}\n"
                   "  - {id: b, perimetre: actu, produit: actu, type: rss, url: https://b, statut: desactive}\n")
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "actu", "--sources", str(yml)]) == 2
    assert "aucune source active" in capsys.readouterr().err


def test_sources_yaml_reel_est_valide():
    from deltalib.sources import charger_sources
    sources = charger_sources(fetch.RACINE / "sources.yaml")
    assert len(sources) >= 15
    assert all("Testé le 2026-" in s.note for s in sources), "chaque source déclare la date de son test"
    bloquees = [s.id for s in sources if s.statut == "bloque"]
    assert bloquees == ["chatgpt-release-notes"]
    for s in sources:
        if "learn.chatgpt.com" in s.url:
            assert "sans préavis" in s.note, "endpoint non documenté : la note doit prévenir"
