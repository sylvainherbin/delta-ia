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
    git(racine, "add", str(f.relative_to(racine)))
    git(racine, "commit", "-qm", "jour")


def git(racine, *args):
    import subprocess
    subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def racine(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("rapports/\n")
    for f in ("docs/data/versions.json", "docs/data/etat.json", "docs/data/claude/index.json", "CONTEXTE.md"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("{}\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
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
    assert code == 10 and r["code"] == 10 and "verrou" in r["motif"] and len(r["controles"]) == 4


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


@pytest.mark.parametrize("fichier, attendu", [
    ("docs/data/versions.json", "docs/data/versions.json (M)"),
    ("docs/data/etat.json", "docs/data/etat.json (M)"),
    ("CONTEXTE.md", "CONTEXTE.md (M)"),
])
def test_arbre_fichier_suivi_modifie(racine, capsys, fichier, attendu):
    (racine / fichier).write_text('{"modifie": true}\n')
    code, out = lancer(racine, capsys, "--json")
    r = json.loads(out)
    assert code == garde.CODE_ARBRE == 13 and r["fichiers_modifies"] == [attendu]


def test_arbre_fichier_du_jour_non_suivi(racine, capsys):
    f = racine / "docs" / "data" / "claude" / f"{J.isoformat()}.json"
    f.write_text("{}")
    code, out = lancer(racine, capsys)
    assert code == 13 and f"docs/data/claude/{J.isoformat()}.json (non suivi)" in out


def test_arbre_non_suivi_hors_chemins_et_ignores_toleres(racine, capsys):
    (racine / "notes.txt").write_text("x")
    (racine / "rapports").mkdir(exist_ok=True)
    (racine / "rapports" / "r.md").write_text("x")
    assert lancer(racine, capsys)[0] == 0


def test_arbre_fichier_indexe(racine, capsys):
    (racine / "docs" / "data" / "etat.json").write_text('{"x": 1}\n')
    git(racine, "add", "docs/data/etat.json")
    code, out = lancer(racine, capsys)
    assert code == 13 and "docs/data/etat.json (M)" in out


def test_d68_correctif_mcp_et_arret_propre():
    from conftest import RACINE
    skill = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "Jamais d'outil MCP pendant un passage" in skill and "docs/data/kb/claude/*.json" in skill
    assert "Grep et Glob n'existent pas dans les sessions Claude Desktop" in skill
    sec = skill[skill.index("## Mode automatique (D68)"):skill.index("## 0. Préparation")]
    arret_suivis = ("git checkout -- docs/data/versions.json docs/data/etat.json docs/data/claude docs/data/actu "
                    "docs/data/kb/claude state/claude.json state/actu.json")
    arret_nouveaux = "git clean -f -- docs/data/claude docs/data/actu"
    assert f"`{arret_suivis}`" in sec and f"`{arret_nouveaux}`" in sec and "outil refusé" in sec and "13 arbre de travail" in sec
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert f"Bash({arret_suivis})" in s["allow"] and f"Bash({arret_nouveaux})" in s["allow"]
    assert not any(r.startswith(("Bash(git checkout *", "Bash(git clean *", "Bash(rm")) for r in s["allow"])
    # serveur local delta-ia, connecteur de compte dans Claude Desktop (identifiant relevé le 25/09) et dans la CLI
    assert {"mcp__delta-ia__*", "mcp__f15d4eb1-5763-45f3-b583-ed06d6d3532d__*", "mcp__claude_ai_Delta-IA__*"} <= set(s["deny"])
    assert not any(r.startswith("mcp__") for r in s["allow"])
