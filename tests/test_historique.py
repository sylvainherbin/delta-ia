"""D72 : historique daté du brut (raw/historique/AAAA-MM-JJ/<nom>-HHMMSS.json), jamais écrasé, jamais bloquant."""

import json
import os
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import fetch
import garde
from conftest import FauxClient
from deltalib.modeles import ErreurReseau

from test_kb import lancer_kb, racine_kb  # noqa: F401 — fixture réutilisée pour le brut de la base

MOMENT = datetime(2026, 9, 30, 17, 45, 12)


def fichiers(racine: Path):
    return sorted(str(p.relative_to(racine / "raw" / "historique")) for p in (racine / "raw" / "historique").rglob("*.json"))


def brut_cli(tmp_path, monkeypatch, sources, code_attendu=0):
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "raw").mkdir(exist_ok=True)
    url = sources["anthropic-newsroom"].url
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({url: ErreurReseau("délai dépassé")}))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"]) == code_attendu


def test_copie_identique_du_brut(tmp_path):
    src = tmp_path / "raw" / "claude-nouveautes.json"
    src.parent.mkdir()
    src.write_text('{"perimetre": "claude", "nouveautes": []}\n', encoding="utf-8")
    cible = fetch.historiser(src, tmp_path, MOMENT)
    assert cible == tmp_path / "raw" / "historique" / "2026-09-30" / "claude-nouveautes-174512.json"
    assert cible.read_bytes() == src.read_bytes()


def test_jamais_d_ecrasement_meme_seconde(tmp_path):
    src = tmp_path / "raw" / "claude-nouveautes.json"
    src.parent.mkdir()
    src.write_text("un", encoding="utf-8")
    premiere = fetch.historiser(src, tmp_path, MOMENT)
    src.write_text("deux", encoding="utf-8")
    seconde = fetch.historiser(src, tmp_path, MOMENT)
    src.write_text("trois", encoding="utf-8")
    troisieme = fetch.historiser(src, tmp_path, MOMENT)
    assert [p.name for p in (premiere, seconde, troisieme)] == [
        "claude-nouveautes-174512.json", "claude-nouveautes-174512-2.json", "claude-nouveautes-174512-3.json"]
    assert [p.read_text() for p in (premiere, seconde, troisieme)] == ["un", "deux", "trois"]


def test_cli_deux_passages_le_meme_jour_donnent_deux_fichiers(tmp_path, monkeypatch, date_figee, sources):
    brut_cli(tmp_path, monkeypatch, sources)
    brut_cli(tmp_path, monkeypatch, sources)
    liste = fichiers(tmp_path)
    assert len(liste) == 2 and len({Path(f).parent for f in map(Path, liste)}) == 1
    assert all(Path(f).name.startswith("claude-nouveautes-") for f in liste)
    assert json.loads((tmp_path / "raw" / "historique" / liste[-1]).read_text()) == \
        json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())


def test_cli_dry_run_n_ecrit_pas_d_historique(tmp_path, monkeypatch, date_figee, sources):
    (tmp_path / "state").mkdir()
    url = sources["anthropic-newsroom"].url
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({url: ErreurReseau("panne")}))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude", "--dry-run"]) == 0
    assert not (tmp_path / "raw").exists()


def test_cli_echec_d_ecriture_est_un_avertissement_code_inchange(tmp_path, monkeypatch, date_figee, sources, capsys):
    brut_cli(tmp_path, monkeypatch, sources)
    capsys.readouterr()
    shutil.rmtree(tmp_path / "raw" / "historique")
    (tmp_path / "raw" / "historique").write_text("un fichier là où un dossier est attendu")  # mkdir échoue
    brut_cli(tmp_path, monkeypatch, sources, code_attendu=0)  # même code de sortie qu'avant
    sortie = capsys.readouterr().out
    assert "! AVERTISSEMENT : historique du brut non écrit (" in sortie
    assert (tmp_path / "raw" / "claude-nouveautes.json").exists()  # le brut lui-même est intact


def test_echec_de_lecture_simulee_ne_leve_pas(tmp_path, monkeypatch, capsys):
    src = tmp_path / "raw" / "x-nouveautes.json"
    src.parent.mkdir()
    src.write_text("{}")
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("disque plein")))
    assert fetch.historiser(src, tmp_path, MOMENT) is None
    assert "historique du brut non écrit (OSError: disque plein)" in capsys.readouterr().out


def test_brut_de_la_base_de_reference(racine_kb, monkeypatch):  # noqa: F811
    assert lancer_kb(racine_kb, monkeypatch) == 0
    noms = sorted(Path(f).name.rsplit("-", 1)[0] for f in fichiers(racine_kb))
    assert noms == ["claude-modifications", "openai-modifications"]
    for f in fichiers(racine_kb):
        origine = racine_kb / "raw" / "kb" / (Path(f).name.rsplit("-", 1)[0] + ".json")
        assert (racine_kb / "raw" / "historique" / f).read_bytes() == origine.read_bytes()


def test_raw_historique_est_ignore_par_git():
    racine = Path(fetch.RACINE)
    r = subprocess.run(["git", "-C", str(racine), "check-ignore", "-q", "raw/historique/2026-09-30/claude-nouveautes-174512.json"])
    assert r.returncode == 0


def test_la_garde_ne_voit_pas_raw_historique(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, env=env)
    git("init", "-q")
    (tmp_path / ".gitignore").write_text("raw/*\n!raw/.gitkeep\nrapports/\n")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / ".gitkeep").write_text("")
    git("add", "-A")
    git("commit", "-qm", "init")
    src = tmp_path / "raw" / "claude-nouveautes.json"
    src.write_text("{}")
    assert fetch.historiser(src, tmp_path, MOMENT).exists()
    res = garde.controler(tmp_path, date(2026, 9, 30), datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
    assert res["code"] == 0 and res["fichiers_modifies"] == []
