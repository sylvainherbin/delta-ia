"""D68 : scripts/garde.py, garde du passage /delta automatique (lecture seule)."""

import json
import os
import time
from datetime import date, datetime, timezone

import pytest

import garde

J = date(2026, 9, 25)


def usage(racine, s5=10, sem=20, age_min=1):
    f = racine / "rapports" / "usage.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"claude": {"session_5h": {"pct": s5}, "semaine": {"pct": sem}}}), encoding="utf-8")
    t = time.time() - age_min * 60
    os.utime(f, (t, t))


def quotidien(racine, genere_le):
    f = racine / "docs" / "data" / "claude" / f"{J.isoformat()}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"date": J.isoformat(), "genere_le": genere_le}), encoding="utf-8")


@pytest.fixture
def racine(tmp_path):
    (tmp_path / ".git").mkdir()
    usage(tmp_path)
    return tmp_path


def lancer(racine, capsys, *args):
    code = garde.main(["--racine", str(racine), "--date", J.isoformat(), *args])
    return code, capsys.readouterr().out


def test_ok(racine, capsys):
    code, out = lancer(racine, capsys)
    assert code == 0 and "GARDE: OK" in out and "AVERTISSEMENT" not in out


def test_verrou(racine, capsys):
    (racine / ".git" / "index.lock").write_text("")
    code, out = lancer(racine, capsys)
    assert code == garde.CODE_VERROU == 10 and "index.lock" in out and "ARRÊT" in out


@pytest.mark.parametrize("s5, sem, attendu", [(80, 10, 11), (79, 84, 0), (10, 85, 11), (95, 95, 11)])
def test_seuils_quotas(racine, capsys, s5, sem, attendu):
    usage(racine, s5, sem)
    assert lancer(racine, capsys)[0] == attendu


def test_usage_perime_continue_mais_signale(racine, capsys):
    usage(racine, 99, 99, age_min=16)
    code, out = lancer(racine, capsys)
    assert code == 0 and "console arrêtée" in out and "99 %" in out, "console arrêtée : on continue, on le signale"


@pytest.mark.parametrize("contenu", [None, "pas du json", json.dumps({"claude": {"session_5h": {"pct": None}}})])
def test_usage_absent_illisible_ou_incomplet(racine, capsys, contenu):
    f = racine / "rapports" / "usage.json"
    if contenu is None:
        f.unlink()
    else:
        f.write_text(contenu, encoding="utf-8")
    code, out = lancer(racine, capsys)
    assert code == 0 and "AVERTISSEMENT" in out and "quotas inconnus" in out


def test_passage_deja_fait(racine, capsys):
    local = datetime(2026, 9, 25, 8, 0).astimezone()
    quotidien(racine, local.isoformat())
    code, out = lancer(racine, capsys)
    assert code == garde.CODE_DEJA_FAIT == 12 and "déjà fait" in out


def test_fichier_du_jour_d_une_autre_date(racine, capsys):
    quotidien(racine, "2026-09-20T10:00:00+00:00")
    assert lancer(racine, capsys)[0] == 0


def test_premier_motif_prime_et_json(racine, capsys):
    (racine / ".git" / "index.lock").write_text("")
    usage(racine, 90, 90)
    code, out = lancer(racine, capsys, "--json")
    r = json.loads(out)
    assert code == 10 and r["code"] == 10 and "verrou" in r["motif"] and len(r["controles"]) == 3


def test_lecture_seule(racine, capsys):
    avant = sorted((p, p.stat().st_mtime) for p in racine.rglob("*") if p.is_file())
    lancer(racine, capsys)
    assert sorted((p, p.stat().st_mtime) for p in racine.rglob("*") if p.is_file()) == avant


def test_date_invalide(racine, capsys):
    assert garde.main(["--racine", str(racine), "--date", "25/09"]) == 2


def test_d68_skill_et_reglages():
    from conftest import RACINE
    skill = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    tete = skill.split("---\n", 2)[1]
    assert "disable-model-invocation: true" in tete, "option A : /delta reste invocable par Sylvain seul"
    sec = skill[skill.index("## Mode automatique (D68)"):skill.index("## 0. Préparation")]
    for attendu in ("que si la consigne le demande explicitement", "scripts/garde.py --date J", "AskUserQuestion",
                    "sans push", "delta-ia-delta-auto.md", "même après un arrêt par la garde", "git push` une seule fois"):
        assert attendu in sec, attendu
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))
    brut = json.dumps(s)
    assert "bypassPermissions" not in brut and "defaultMode" not in s.get("permissions", {})
    allow = s["permissions"]["allow"]
    for r in allow:
        assert r.startswith(("Bash(", "Edit(")), r
        assert r not in ("Bash", "Edit", "Bash(*)", "Edit(**)") and not r.startswith(("Bash(git *", "Bash(python", "Bash(.venv/bin/python *")), r
        assert "-c" not in r.split(), r
    # chaque commande nommée par la section automatique a sa règle
    for cmd in ("git pull --rebase", "git push", "date +%F", "sha1sum CONTEXTE.md",
                "git add docs/data/claude state/claude.json docs/data/kb/claude docs/data/versions.json docs/data/etat.json",
                "git add docs/data/actu state/actu.json"):
        assert f"Bash({cmd})" in allow and f"`{cmd}`" in sec.replace("\n", " ") or f"Bash({cmd})" in allow, cmd
    assert {"Bash(git push --force *)", "Bash(git add -A *)"} <= set(s["permissions"]["deny"])
    assert "| D68 |" in (RACINE / "SPEC.md").read_text(encoding="utf-8")
