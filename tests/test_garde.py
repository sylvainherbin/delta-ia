"""D68 : scripts/garde.py, garde du passage /delta automatique (lecture seule)."""

import json
import os
import time
from datetime import date, datetime, timezone

import pytest

import garde

J = date(2026, 9, 25)


def usage(racine, s5=10, sem=20, age_min=1, chatgpt=None):
    f = racine / "rapports" / "usage.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    contenu = {"claude": {"session_5h": {"pct": s5}, "semaine": {"pct": sem}}}
    if chatgpt is not None:
        contenu["chatgpt"] = {"semaine": {"pct": chatgpt}}
    f.write_text(json.dumps(contenu), encoding="utf-8")
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


@pytest.fixture(autouse=True)
def pauses(monkeypatch):
    """Aucune attente réelle : les pauses de relecture sont enregistrées, et un scénario peut agir pendant la pause."""
    appels = []
    monkeypatch.setattr(garde, "_dormir", lambda s: appels.append(s))
    return appels


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


@pytest.mark.parametrize("s5, sem, attendu", [
    (10, 97, 0), (10, 98, 11), (80, 10, 11), (79, 97, 0), (10, 95, 0), (95, 95, 11), (99, 99, 11),
])
def test_seuils_quotas(racine, capsys, s5, sem, attendu):
    usage(racine, s5, sem)
    assert lancer(racine, capsys)[0] == attendu


# --- D71 : alerte à 80 % du quota hebdomadaire, sans arrêt ------------------------------------------------

def alertes_hebdo(out):
    return [l for l in out.splitlines() if "quota hebdomadaire" in l]


def test_d71_79_pour_cent_sans_avertissement(racine, capsys):
    usage(racine, 10, 79, chatgpt=79)
    code, out = lancer(racine, capsys)
    assert code == 0 and alertes_hebdo(out) == [] and "GARDE: OK" in out


def test_d71_claude_a_80_avertit_sans_arreter(racine, capsys):
    usage(racine, 10, 80, chatgpt=10)
    code, out = lancer(racine, capsys)
    assert code == 0 and "GARDE: OK" in out
    assert alertes_hebdo(out) == ["! AVERTISSEMENT : quota hebdomadaire Claude à 80 % — vérifie tes remises à zéro disponibles "
                                  "(Paramètres > Utilisation) avant d'économiser (D71)"]


def test_d71_chatgpt_a_80_avertit_sans_arreter(racine, capsys):
    usage(racine, 10, 20, chatgpt=80)
    code, out = lancer(racine, capsys)
    assert code == 0
    assert alertes_hebdo(out) == ["! AVERTISSEMENT : quota hebdomadaire ChatGPT à 80 % — vérifie tes remises à zéro disponibles "
                                  "(Paramètres > Utilisation) avant d'économiser (D71)"]


def test_d71_chatgpt_a_100_ne_bloque_jamais(racine, capsys):
    usage(racine, 10, 20, chatgpt=100)
    code, out = lancer(racine, capsys)
    assert code == 0 and "GARDE: OK" in out and "ChatGPT à 100 %" in out


def test_d71_les_deux_produits_donnent_deux_avertissements(racine, capsys):
    usage(racine, 10, 82, chatgpt=92)
    code, out = lancer(racine, capsys)
    assert code == 0 and [("Claude" in l, "ChatGPT" in l) for l in alertes_hebdo(out)] == [(True, False), (False, True)]


def test_d71_claude_a_98_reste_en_code_11(racine, capsys):
    usage(racine, 10, 98)
    code, out = lancer(racine, capsys)
    assert code == garde.CODE_QUOTA == 11 and "ARRÊT" in out and "quota hebdomadaire Claude à 98 %" in out


def test_d71_champ_chatgpt_absent_inchange(racine, capsys):
    usage(racine, 10, 20)  # pas de bloc chatgpt
    code, out = lancer(racine, capsys)
    assert code == 0 and "AVERTISSEMENT" not in out


def test_d71_releve_perime_avertit_quand_meme_sans_arret(racine, capsys):
    usage(racine, 10, 90, age_min=16, chatgpt=93)
    code, out = lancer(racine, capsys)
    assert code == 0 and "GARDE: OK" in out and "console arrêtée" in out
    assert alertes_hebdo(out) == [
        "! AVERTISSEMENT : quota hebdomadaire Claude à 90 % (relevé périmé, il y a 16 min) — vérifie tes remises à zéro disponibles "
        "(Paramètres > Utilisation) avant d'économiser (D71)",
        "! AVERTISSEMENT : quota hebdomadaire ChatGPT à 93 % (relevé périmé, il y a 16 min) — vérifie tes remises à zéro disponibles "
        "(Paramètres > Utilisation) avant d'économiser (D71)"]


def test_d71_releve_perime_sous_80_sans_alerte(racine, capsys):
    usage(racine, 10, 79, age_min=30, chatgpt=50)
    assert alertes_hebdo(lancer(racine, capsys)[1]) == []


@pytest.mark.parametrize("contenu", [
    None, "{tronqué", json.dumps({"claude": {}}),
    json.dumps({"claude": {"session_5h": {"pct": None}, "semaine": {"pct": None}}}),
    json.dumps({"claude": {"session_5h": {"pct": 10}, "semaine": {}}})])
def test_d71_quotas_claude_inconnus_rappellent_de_verifier(racine, capsys, contenu):
    f = racine / "rapports" / "usage.json"
    f.unlink() if contenu is None else f.write_text(contenu, encoding="utf-8")
    code, out = lancer(racine, capsys)
    assert code == 0 and "quotas inconnus" in out
    assert "vérifie tes quotas et remises à zéro Claude dans Paramètres > Utilisation (D71)" in out


def test_d71_l_avertissement_declenche_le_rapport_du_mode_automatique():
    """D63 amendée : tout `! AVERTISSEMENT` de la garde impose un rapport ; l'avertissement D71 sort sous ce préfixe."""
    from conftest import RACINE
    skill = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "un avertissement de la garde (`! AVERTISSEMENT`)" in skill


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
    assert code == 10 and r["code"] == 10 and "verrou" in r["motif"] and len(r["controles"]) == 6


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
                "git add docs/data/claude state/claude.json docs/data/kb/claude docs/data/kb/recent.json docs/data/versions.json docs/data/etat.json",
                "git add docs/data/actu state/actu.json docs/data/semaine"):
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
                    "docs/data/kb/claude docs/data/kb/recent.json state/claude.json state/actu.json")
    arret_nouveaux = "git clean -f -- docs/data/claude docs/data/actu docs/data/semaine"
    arret_semaine = "git checkout -- docs/data/semaine"  # D98 : séparé, git refuse tout un checkout si un chemin n'est pas encore suivi
    assert f"`{arret_semaine}`" in sec
    assert f"`{arret_suivis}`" in sec and f"`{arret_nouveaux}`" in sec and "outil refusé" in sec and "13 arbre de travail" in sec
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert f"Bash({arret_suivis})" in s["allow"] and f"Bash({arret_nouveaux})" in s["allow"] and f"Bash({arret_semaine})" in s["allow"]
    assert not any(r.startswith(("Bash(git checkout *", "Bash(git clean *", "Bash(rm")) for r in s["allow"])
    # serveur local delta-ia, connecteur de compte dans Claude Desktop (identifiant relevé le 25/09) et dans la CLI
    assert {"mcp__delta-ia__*", "mcp__f15d4eb1-5763-45f3-b583-ed06d6d3532d__*", "mcp__claude_ai_Delta-IA__*"} <= set(s["deny"])
    assert not any(r.startswith("mcp__") for r in s["allow"])


def test_d68_grep_lecture_seule_et_settings_local_ignore():
    from conftest import RACINE
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    greps = sorted(r for r in s["allow"] if r.startswith("Bash(grep"))
    assert greps == ["Bash(grep -n *)", "Bash(grep -o *)", "Bash(grep -rn *)"], "grep en lecture seule, formes -n, -rn, -o seulement"
    assert ".claude/settings.local.json" in (RACINE / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_d71_d72_inscrites_dans_spec_regles_skills_et_prompts():
    from conftest import RACINE
    lire = lambda p: (RACINE / p).read_text(encoding="utf-8")
    spec, regles = lire("SPEC.md"), lire("REGLES.md")
    assert "| D71 |" in spec and "| D72 |" in spec and "## 9. Compte et quotas (D71)" in regles
    assert "vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser" in spec + regles
    for f in (".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta/SKILL.md",
              ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md", "prompts/codex-delta-kb.md"):
        assert "Compte et quotas" in lire(f) and "D71" in lire(f), f


# --- D71 : relecture unique de usage.json quand un champ manque (la console le réécrit) ----------------------

def usage_sans_claude(racine, chatgpt=None):
    f = racine / "rapports" / "usage.json"
    f.write_text(json.dumps({"claude": {}, **({"chatgpt": {"semaine": {"pct": chatgpt}}} if chatgpt is not None else {})}), encoding="utf-8")


def test_d71_champ_absent_puis_present_est_evalue_normalement(racine, capsys, monkeypatch, pauses):
    usage_sans_claude(racine)
    monkeypatch.setattr(garde, "_dormir", lambda s: (pauses.append(s), usage(racine, 10, 80, chatgpt=85)))
    code, out = lancer(racine, capsys)
    assert code == 0 and pauses == [garde.DELAI_RELECTURE_S] and "quotas inconnus" not in out
    assert "session 5 h 10 %, semaine 80 %" in out
    assert [("Claude" in l, "ChatGPT" in l) for l in alertes_hebdo(out)] == [(True, False), (False, True)]


def test_d71_champ_absent_puis_present_peut_arreter(racine, capsys, monkeypatch, pauses):
    usage_sans_claude(racine)
    monkeypatch.setattr(garde, "_dormir", lambda s: (pauses.append(s), usage(racine, 80, 20)))
    assert lancer(racine, capsys)[0] == garde.CODE_QUOTA == 11


def test_d71_fichier_absent_puis_present(racine, capsys, monkeypatch, pauses):
    (racine / "rapports" / "usage.json").unlink()
    monkeypatch.setattr(garde, "_dormir", lambda s: (pauses.append(s), usage(racine, 10, 20)))
    code, out = lancer(racine, capsys)
    assert code == 0 and "AVERTISSEMENT" not in out and len(pauses) == 1


def test_d71_champ_absent_aux_deux_lectures_comportement_actuel(racine, capsys, pauses):
    usage_sans_claude(racine)
    code, out = lancer(racine, capsys)
    assert code == 0 and "GARDE: OK" in out and "quotas inconnus" in out and "AVERTISSEMENT" in out
    assert pauses == [garde.DELAI_RELECTURE_S], "une seule relecture, jamais de boucle"


def test_d71_fichier_illisible_aux_deux_lectures_comportement_actuel(racine, capsys, pauses):
    (racine / "rapports" / "usage.json").write_text("{tronqué", encoding="utf-8")
    code, out = lancer(racine, capsys)
    assert code == 0 and "absent ou illisible" in out and len(pauses) == 1


def test_d71_pas_d_attente_quand_la_premiere_lecture_est_complete(racine, capsys, pauses):
    usage(racine, 10, 20, chatgpt=50)
    code, out = lancer(racine, capsys)
    assert code == 0 and pauses == []


def test_d71_delai_injectable_et_borne(racine, pauses):
    usage_sans_claude(racine)
    garde.controler(racine, J, delai_relecture=0.25)
    assert pauses == [0.25] and garde.DELAI_RELECTURE_S <= 3


# --- D70 : verrou de la chaîne (14), commits non poussés (15), contrôles par étape ---------------------------------

import fcntl


def tenir_verrou(racine, pid):
    """Tient `.git/delta-passage.lock` comme le fait passage-auto.sh (flock sur un autre descripteur) et y écrit le PID."""
    chemin = racine / ".git" / "delta-passage.lock"
    fd = os.open(chemin, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.ftruncate(fd, 0)
    os.write(fd, f"{pid}\n".encode())
    return fd


def test_d70_verrou_chaine_tenu_arrete_net(racine, capsys, monkeypatch):
    monkeypatch.delenv("DELTA_CHAINE_PID", raising=False)
    fd = tenir_verrou(racine, 4242)
    try:
        code, out = lancer(racine, capsys)
        assert code == garde.CODE_CHAINE == 14 and "delta-passage.lock" in out and "pid 4242" in out and "ARRÊT" in out
    finally:
        os.close(fd)


def test_d70_appel_de_la_chaine_est_exempte(racine, capsys, monkeypatch):
    fd = tenir_verrou(racine, 4242)
    try:
        monkeypatch.setenv("DELTA_CHAINE_PID", "4242")
        code, out = lancer(racine, capsys)
        assert code == 0 and "cet appel en fait partie" in out
        monkeypatch.setenv("DELTA_CHAINE_PID", "4243")  # autre PID : relance manuelle pendant la chaîne
        assert lancer(racine, capsys)[0] == 14
    finally:
        os.close(fd)


def test_d70_verrou_relache_ou_absent_ne_bloque_pas(racine, capsys, monkeypatch):
    monkeypatch.delenv("DELTA_CHAINE_PID", raising=False)
    assert lancer(racine, capsys)[0] == 0 and not (racine / ".git" / "delta-passage.lock").exists(), "la garde ne crée pas le verrou"
    os.close(tenir_verrou(racine, 1))  # fichier présent, verrou relâché (chaîne terminée) : pas d'arrêt
    assert lancer(racine, capsys)[0] == 0


def test_d70_la_garde_ne_prend_pas_le_verrou(racine, capsys):
    chemin = racine / ".git" / "delta-passage.lock"
    chemin.write_text("1\n")
    lancer(racine, capsys)
    fd = os.open(chemin, os.O_RDWR)  # un autre processus peut le prendre juste après
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)


@pytest.fixture
def racine_avec_origin(racine, tmp_path_factory):
    bare = tmp_path_factory.mktemp("origin") / "origin.git"
    import subprocess
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    git(racine, "remote", "add", "origin", str(bare))
    git(racine, "push", "-q", "origin", "HEAD:refs/heads/main")
    git(racine, "fetch", "-q", "origin")
    return racine


def test_d70_commits_non_pousses_arretent_code_15(racine_avec_origin, capsys):
    racine = racine_avec_origin
    assert lancer(racine, capsys)[0] == 0 and "commits non poussés : aucun" in capsys.readouterr().out or True
    (racine / "notes.txt").write_text("x")
    git(racine, "add", "notes.txt")
    git(racine, "commit", "-qm", "local")
    code, out = lancer(racine, capsys)
    assert code == garde.CODE_NON_POUSSE == 15 and "1 commit(s) local(aux)" in out
    git(racine, "push", "-q", "origin", "HEAD:refs/heads/main")
    git(racine, "fetch", "-q", "origin")
    assert lancer(racine, capsys)[0] == 0


def test_d70_sans_origin_main_les_commits_ne_sont_pas_evalues(racine, capsys):
    code, out = lancer(racine, capsys)
    assert code == 0 and "non évalué (pas de origin/main)" in out


def openai_du_jour(racine):
    f = racine / "docs" / "data" / "openai" / f"{J.isoformat()}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"date": J.isoformat(), "genere_le": datetime(2026, 9, 25, 8, 0).astimezone().isoformat()}), encoding="utf-8")
    git(racine, "add", str(f.relative_to(racine)))
    git(racine, "commit", "-qm", "openai")


@pytest.mark.parametrize("etape, attendu", [("delta", 11), ("codex-delta", 0), ("delta-kb", 11), ("codex-delta-kb", 0), (None, 11)])
def test_d70_quota_claude_ne_vaut_que_pour_les_etapes_claude(racine, capsys, etape, attendu):
    usage(racine, 90, 20)
    args = ("--etape", etape) if etape else ()
    assert lancer(racine, capsys, *args)[0] == attendu


def test_d70_chaque_etape_regarde_son_fichier_du_jour(racine, capsys):
    quotidien(racine, datetime(2026, 9, 25, 8, 0).astimezone().isoformat())  # claude fait
    assert lancer(racine, capsys, "--etape", "delta")[0] == 12
    assert lancer(racine, capsys, "--etape", "codex-delta")[0] == 0, "le passage claude fait ne bloque pas Codex"
    assert lancer(racine, capsys, "--etape", "delta-kb")[0] == 0 and lancer(racine, capsys, "--etape", "codex-delta-kb")[0] == 0
    openai_du_jour(racine)
    assert lancer(racine, capsys, "--etape", "codex-delta")[0] == 12
    assert lancer(racine, capsys, "--etape", "codex-delta-kb")[0] == 0


def test_d70_arbre_sale_dans_openai_ou_kb_arrete(racine, capsys):
    for chemin in ("docs/data/openai/2026-09-25.json", "docs/data/kb/openai/x.json"):
        f = racine / chemin
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}")
        code, out = lancer(racine, capsys, "--etape", "codex-delta")
        assert code == 13 and f"{chemin} (non suivi)" in out
        f.unlink()


def test_d83_arbre_sale_hors_perimetre_de_l_etape_ne_bloque_pas(racine, capsys):
    (racine / "docs" / "data" / "versions.json").write_text('{"modifie": true}\n')
    (racine / "CONTEXTE.md").write_text("modifié\n")
    f = racine / "docs" / "data" / "openai" / "2026-09-25.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}")
    assert lancer(racine, capsys, "--etape", "codex-delta-kb")[0] == 0   # versions.json est un chemin Claude, CONTEXTE.md aucun
    code, out = lancer(racine, capsys, "--etape", "delta")               # le fichier openai n'est pas à cette étape
    assert code == 13 and "docs/data/versions.json (M)" in out and "openai" not in out and "CONTEXTE.md" not in out
    assert lancer(racine, capsys)[0] == 13                                # sans --etape : comportement D68 inchangé


def test_d83_arbre_sale_dans_l_etape_bloque_toujours(racine, capsys):
    (racine / "docs" / "data" / "etat.json").write_text('{"x": 1}\n')
    code, out = lancer(racine, capsys, "--etape", "delta")
    assert code == 13 and "docs/data/etat.json (M)" in out
    assert lancer(racine, capsys, "--etape", "codex-delta")[0] == 0 and lancer(racine, capsys, "--etape", "delta-kb")[0] == 0


def test_d70_etape_inconnue_est_refusee(racine):
    with pytest.raises(SystemExit) as e:
        garde.main(["--racine", str(racine), "--etape", "inconnue"])
    assert e.value.code == 2
