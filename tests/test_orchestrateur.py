"""D70 : orchestrateur des passages automatiques. Aucun appel réel à `claude` ni à `codex` : les étapes sont de faux agents
(petits scripts Python) qui modifient un dépôt de test avec son `origin` local. La vraie garde tourne avant chaque étape."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from datetime import date
from pathlib import Path

import pytest

import orchestrateur as orc
from conftest import RACINE

JOUR = date(2026, 10, 2)

FAUX_AGENT = r'''
import json, os, subprocess, sys, time
mode = sys.argv[1]

def git(*a):
    subprocess.run(["git", *a], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

def ecrire(chemin, texte):
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    open(chemin, "w").write(texte)

REFUS = {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "for l in 1 2; do sed -n \"$l p\" f; done"}}

def claude_ok(denials=()):
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "permission_denials": list(denials), "result": "ok"}))

def passage(dossier, fichier, pousser=True, sujet=None):
    ecrire(f"{dossier}/{fichier}", f"{fichier}\n")
    git("add", dossier); git("commit", "-qm", sujet or f"delta: {fichier}")
    if pousser:
        git("push", "-q", "origin", "HEAD:refs/heads/main")

if mode == "ok":
    passage(sys.argv[2], sys.argv[3]); claude_ok()
elif mode == "ok-codex":
    passage(sys.argv[2], sys.argv[3])
elif mode == "ok-sans-commit":
    claude_ok()
elif mode == "echec":
    ecrire(f"{sys.argv[2]}/index.json", "modifié par une étape en échec\n")
    ecrire(f"{sys.argv[2]}/nouveau.json", "{}\n")
    ecrire("notes.txt", "touché hors périmètre\n")
    print("échec simulé", file=sys.stderr); sys.exit(3)
elif mode == "sale-hors-chemins":
    ecrire("notes.txt", "touché hors périmètre\n"); claude_ok()
elif mode == "non-pousse":
    passage(sys.argv[2], sys.argv[3], pousser=False); claude_ok()
elif mode == "refus":
    claude_ok([{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "ls /etc | head -3"}}])
elif mode == "refus-commit":   # refus de permission, mais l'étape a produit et poussé son commit attendu
    passage(sys.argv[2], sys.argv[3], sujet="delta(claude): 2026-10-02 — 1 éléments (0 fort)"); claude_ok([REFUS])
elif mode == "refus-mauvais-sujet":
    passage(sys.argv[2], sys.argv[3], sujet="autre chose"); claude_ok([REFUS])
elif mode == "refus-non-pousse":
    passage(sys.argv[2], sys.argv[3], pousser=False, sujet="delta(claude): 2026-10-02 — 1 éléments (0 fort)"); claude_ok([REFUS])
elif mode == "refus-sale":
    passage(sys.argv[2], sys.argv[3], sujet="delta(claude): 2026-10-02 — 1 éléments (0 fort)")
    ecrire("notes.txt", "touché hors périmètre\n"); claude_ok([REFUS])
elif mode == "refus-echec":
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": False, "permission_denials": [REFUS]}))
elif mode == "pas-json":
    print("ceci n'est pas du JSON")
elif mode == "verrou-git":
    ecrire(".git/index.lock", ""); claude_ok()
elif mode == "dort":
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4); open(sys.argv[1], 'w').write('survivant')", sys.argv[2]])
    time.sleep(60)
elif mode == "enfant-en-fond":
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3); open(sys.argv[1], 'w').write('survivant')", sys.argv[2]])
    claude_ok()
elif mode == "ajoute-hook":
    ecrire(".git/hooks/pre-commit", "#!/bin/sh\necho piégé\n"); claude_ok()
elif mode == "modifie-config":
    open(".git/config", "a").write("[alias]\n\tci = !echo piégé\n"); claude_ok()
elif mode == "modifie-hook":
    open(".git/hooks/pre-push", "a").write("echo piégé\n"); claude_ok()
elif mode == "supprime-hook":
    os.remove(".git/hooks/pre-push"); claude_ok()
elif mode == "supervision":
    ecrire("rapports/supervision-lancee.txt", "oui\n"); claude_ok()
elif mode.startswith("supervision-refus"):
    ecrire(sys.argv[2], sys.argv[3])
    if mode == "supervision-refus-sale":
        ecrire("notes.txt", "touché hors périmètre\n")
    print(json.dumps({"type": "result", "subtype": "error_max_turns" if mode == "supervision-refus-erreur" else "success",
                      "is_error": mode == "supervision-refus-is-error", "permission_denials": [REFUS]}))
    if mode == "supervision-refus-exit":
        sys.exit(2)
elif mode == "env":
    ecrire("rapports/env-vu.txt", os.environ.get("DELTA_CHAINE_PID", "") + "|" + os.environ.get("PATH", "") + "|" + os.environ.get("GIT_OPTIONAL_LOCKS", "-")); claude_ok()
else:
    sys.exit(99)
'''


class Depot(type(Path())):
    """Chemin du dépôt de test, qui porte aussi l'aide `sh` et le faux agent."""


@pytest.fixture
def depot(tmp_path):
    racine = Depot(tmp_path / "depot")
    origin = tmp_path / "origin.git"
    racine.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    sh = lambda *a, cwd=racine: subprocess.run(a, cwd=cwd, check=True, capture_output=True, env=env)
    sh("git", "init", "-q", "-b", "main")
    sh("git", "init", "-q", "--bare", str(origin), cwd=tmp_path)
    (racine / ".gitignore").write_text("rapports/\nraw/\n__pycache__/\n.venv/\n")
    for f in ("docs/data/claude/index.json", "docs/data/actu/index.json", "docs/data/openai/index.json", "docs/data/kb/claude/x.json",
              "docs/data/kb/openai/x.json", "docs/data/versions.json", "docs/data/etat.json", "state/claude.json", "state/actu.json",
              "state/openai.json", "notes.txt", "CONTEXTE.md"):
        (racine / f).parent.mkdir(parents=True, exist_ok=True)
        (racine / f).write_text("{}\n")
    (racine / "scripts").mkdir()
    shutil.copy(RACINE / "scripts" / "garde.py", racine / "scripts" / "garde.py")
    (tmp_path / "faux_agent.py").write_text(FAUX_AGENT)
    sh("git", "add", "-A")
    sh("git", "commit", "-qm", "init")
    sh("git", "remote", "add", "origin", str(origin))
    sh("git", "push", "-q", "origin", "HEAD:refs/heads/main")
    sh("git", "fetch", "-q", "origin")
    (racine / "rapports").mkdir()
    usage = racine / "rapports" / "usage.json"
    usage.write_text(json.dumps({"claude": {"session_5h": {"pct": 5}, "semaine": {"pct": 20}}, "chatgpt": {"semaine": {"pct": 10}}}))
    racine.faux = tmp_path / "faux_agent.py"
    racine.sh = sh
    return racine


@pytest.fixture
def cfg(tmp_path):
    c = orc.charger_config()
    c["chaine"]["arret_delai_s"] = 1
    return c


def etape(depot, nom, mode, *args, agent="claude", delai=20, garde="delta", kb=None, supervision=False, checkout=(), clean=(), attendus=()):
    return orc.Etape(nom=nom, agent=agent, commande=[sys.executable, str(depot.faux), mode, *args], delai_s=delai,
                     garde=None if supervision else garde, kb=kb, supervision=supervision, checkout=list(checkout), clean=list(clean),
                     commits_attendus=list(attendus))


def chaine(depot, cfg, etapes, **kw):
    return orc.Chaine(depot, cfg, etapes, jour=JOUR, **kw)


def journal(depot):
    f = depot / "rapports" / "passages.log"
    return [l.split(" | ") for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def codes(depot):
    """{périmètre: code} des lignes `orchestrateur`."""
    return {l[2]: int(l[5]) for l in journal(depot) if l[1] == "orchestrateur"}


def ahead(depot):
    return int(depot.sh("git", "rev-list", "--count", "origin/main..HEAD").stdout.decode().strip())


DELTA_CLAUDE = ("docs/data/claude",)


# --- succès --------------------------------------------------------------------------------------------------

def test_chaine_reussie_toutes_les_etapes_dans_l_ordre(depot, cfg):
    etapes = [
        etape(depot, "delta", "ok", "docs/data/claude", "a.json", checkout=DELTA_CLAUDE),
        etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "b.json", agent="codex", garde="codex-delta"),
        etape(depot, "delta-kb", "ok", "docs/data/kb/claude", "c.json", garde="delta-kb", kb="claude"),
        etape(depot, "codex-delta-kb", "ok-codex", "docs/data/kb/openai", "d.json", agent="codex", garde="codex-delta-kb", kb="openai"),
        etape(depot, "supervision", "supervision", supervision=True),
    ]
    assert chaine(depot, cfg, etapes, compte_lots=lambda r, p: 3).executer() == 0
    assert codes(depot) == {"delta": 0, "codex-delta": 0, "delta-kb": 0, "codex-delta-kb": 0, "supervision": 0, "chaine": 0}
    assert [l[2] for l in journal(depot)] == ["delta", "codex-delta", "delta-kb", "codex-delta-kb", "supervision", "chaine"]
    assert ahead(depot) == 0 and not depot.sh("git", "status", "--porcelain").stdout
    assert (depot / "rapports" / "supervision-lancee.txt").exists()
    # le commit de chaque étape est dans la ligne du journal, la sortie dans rapports/auto/
    lignes = {l[2]: l for l in journal(depot)}
    assert lignes["delta"][4] != "aucun" and lignes["supervision"][4] == "aucun"
    assert (depot / "rapports" / "auto" / "2026-10-02-delta.log").exists()


def test_l_environnement_est_fixe_et_ne_fuit_pas(depot, cfg, monkeypatch):
    monkeypatch.setenv("SECRET_DE_TEST", "ne-doit-pas-passer")
    e = etape(depot, "supervision", "env", supervision=True)
    chaine(depot, cfg, [e]).executer()
    pid, path, verrous = (depot / "rapports" / "env-vu.txt").read_text().split("|")
    assert pid == str(os.getpid()) and verrous == "0", "GIT_OPTIONAL_LOCKS=0 pour la supervision"
    assert path.startswith(os.path.expanduser("~/.local/bin")) and "SECRET" not in path
    assert "ne-doit-pas-passer" not in "".join(p.read_text() for p in (depot / "rapports" / "auto").glob("*.log"))
    assert "SECRET_DE_TEST" not in orc.environnement(cfg)


# --- échec, arrêt propre limité aux chemins de l'étape ---------------------------------------------------------

def test_echec_arret_propre_limite_aux_chemins_de_l_etape(depot, cfg):
    etapes = [etape(depot, "delta", "echec", "docs/data/claude", checkout=["docs/data/claude"], clean=["docs/data/claude"]),
              etape(depot, "supervision", "supervision", supervision=True)]
    assert chaine(depot, cfg, etapes).executer() == 1
    assert (depot / "docs/data/claude/index.json").read_text() == "{}\n", "fichier suivi remis en place"
    assert not (depot / "docs/data/claude/nouveau.json").exists(), "fichier non suivi de l'étape supprimé"
    assert (depot / "notes.txt").read_text() == "touché hors périmètre\n", "un fichier hors des chemins de l'étape n'est jamais touché"
    # l'arbre reste sale à cause de notes.txt : la chaîne le dit (126) au lieu de le nettoyer
    assert codes(depot)["delta"] == orc.CODE_ETAT and codes(depot)["chaine"] == 1
    log = (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()
    assert "arrêt propre : git checkout -- docs/data/claude" in log and "git clean -f -- docs/data/claude" in log


def test_echec_simple_code_de_sortie_et_chaine_arretee(depot, cfg):
    depot.sh("git", "checkout", "-q", "--", "notes.txt")
    e1 = etape(depot, "delta", "echec", "docs/data/claude", checkout=["docs/data/claude", "notes.txt"], clean=["docs/data/claude"])
    e2 = etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "z.json", agent="codex", garde="codex-delta")
    etapes = [e1, e2, etape(depot, "supervision", "supervision", supervision=True)]
    assert chaine(depot, cfg, etapes).executer() == 1
    assert codes(depot)["delta"] == 3, "code de sortie de l'agent, arbre remis en place"
    assert codes(depot)["codex-delta"] == orc.CODE_NON_LANCEE, "chaîne arrêtée : étape suivante non lancée"
    assert ahead(depot) == 0 and not (depot / "docs/data/openai/z.json").exists()
    assert (depot / "rapports" / "supervision-lancee.txt").exists(), "la supervision est lancée même après un échec"


def test_supervision_lancee_meme_apres_une_garde_qui_arrete(depot, cfg):
    (depot / ".git" / "index.lock").write_text("")  # verrou git : la garde (code 10) arrête la chaîne
    etapes = [etape(depot, "delta", "ok", "docs/data/claude", "a.json"), etape(depot, "supervision", "supervision", supervision=True)]
    assert chaine(depot, cfg, etapes).executer() == 1
    assert codes(depot)["delta"] == 10 and (depot / "rapports" / "supervision-lancee.txt").exists()
    assert (depot / ".git" / "index.lock").exists(), "jamais supprimé par l'orchestrateur (D21)"


# --- délai dépassé, processus enfants ---------------------------------------------------------------------------

def test_delai_depasse_tue_tout_le_groupe_de_processus(depot, cfg, tmp_path):
    survivant = tmp_path / "survivant.txt"
    e = etape(depot, "delta", "dort", str(survivant), delai=1)
    t0 = time.time()
    assert chaine(depot, cfg, [e]).executer() == 1
    assert time.time() - t0 < 15
    assert codes(depot)["delta"] == orc.CODE_DELAI
    time.sleep(5)  # l'enfant aurait écrit son fichier au bout de 4 s s'il avait survécu
    assert not survivant.exists()


def test_enfant_en_arriere_plan_apres_une_etape_reussie_est_tue(depot, cfg, tmp_path):
    survivant = tmp_path / "survivant2.txt"
    assert chaine(depot, cfg, [etape(depot, "delta", "enfant-en-fond", str(survivant))]).executer() == 0
    time.sleep(4.5)
    assert not survivant.exists()


def test_binaire_introuvable_est_une_erreur_explicite(depot, cfg):
    e = orc.Etape(nom="delta", agent="claude", commande=["/nulle/part/claude", "-p", "x"], delai_s=5, garde="delta")
    assert chaine(depot, cfg, [e]).executer() == 1 and codes(depot)["delta"] == orc.CODE_BINAIRE


# --- intégrité de git : hooks et config (Codex a .git en écriture) ----------------------------------------------

def chaine_deux_etapes_puis_supervision(depot, cfg, mode):
    etapes = [etape(depot, "delta", mode), etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "b.json", agent="codex", garde="codex-delta"),
              etape(depot, "supervision", "supervision", supervision=True)]
    return chaine(depot, cfg, etapes).executer()


@pytest.mark.parametrize("mode, fichier", [("ajoute-hook", "hooks/pre-commit"), ("modifie-config", "config"),
                                           ("modifie-hook", "hooks/pre-push"), ("supprime-hook", "hooks/pre-push")])
def test_hook_ou_config_modifie_arrete_la_chaine_code_126(depot, cfg, mode, fichier):
    (depot / ".git" / "hooks").mkdir(exist_ok=True)
    if mode in ("modifie-hook", "supprime-hook"):
        (depot / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\n")  # hook préexistant
    assert chaine_deux_etapes_puis_supervision(depot, cfg, mode) == 1
    assert codes(depot)["delta"] == orc.CODE_ETAT == 126
    assert codes(depot)["codex-delta"] == orc.CODE_NON_LANCEE, "la chaîne s'arrête"
    assert (depot / "rapports" / "supervision-lancee.txt").exists(), "la supervision reste lancée"
    log = (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()
    assert "hooks ou config git modifiés" in log and fichier in log and "rien n'est rétabli" in log
    if mode == "ajoute-hook":
        assert (depot / ".git" / "hooks" / "pre-commit").exists(), "l'orchestrateur ne supprime ni ne rétablit rien"


def test_hooks_et_config_inchanges_ne_changent_rien(depot, cfg):
    (depot / ".git" / "hooks").mkdir(exist_ok=True)
    (depot / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\n")
    assert chaine_deux_etapes_puis_supervision(depot, cfg, "ok-sans-commit") == 0
    assert codes(depot)["delta"] == 0 and codes(depot)["codex-delta"] == 0


def test_empreinte_git_noms_et_contenus(depot):
    (depot / ".git" / "hooks").mkdir(exist_ok=True)
    base = orc.empreinte_git(depot)
    assert "config" in base and orc.empreinte_git(depot) == base
    (depot / ".git" / "hooks" / "post-commit").write_text("a")
    ajout = orc.empreinte_git(depot)
    assert orc.differences_git(base, ajout) == ["hooks/post-commit"]
    (depot / ".git" / "hooks" / "post-commit").write_text("b")
    assert orc.differences_git(ajout, orc.empreinte_git(depot)) == ["hooks/post-commit"], "le contenu compte, pas seulement le nom"
    (depot / ".git" / "hooks" / "sous").mkdir()
    (depot / ".git" / "hooks" / "sous" / "x").write_text("c")
    assert "hooks/sous/x" in orc.empreinte_git(depot), "sous-dossiers compris"
    # un fichier suivi ou non suivi du dépôt n'entre pas dans l'empreinte
    (depot / "notes.txt").write_text("autre")
    assert "notes.txt" not in orc.empreinte_git(depot)


def test_supervision_est_prevenue_du_code_126_git():
    t = (RACINE / "prompts" / "supervision.md").read_text(encoding="utf-8")
    assert "hooks ou config git modifiés" in t and ".git/hooks/" in t and ".git/config" in t


# --- adoptions déclarées : comptées parmi les lots dus ---------------------------------------------------------

def base_kb(racine, statut):
    d = racine / "docs" / "data" / "kb" / "claude"
    d.mkdir(parents=True, exist_ok=True)
    entree = {"id": "claude-code-commandes-foo", "categorie": "commandes", "nom": "/foo", "commentee": True, "retiree": False,
              "statut_usage": statut, "historique": []}
    (d / "commandes.json").write_text(json.dumps({"perimetre": "claude", "categorie": "commandes", "entrees": [entree]}), encoding="utf-8")


def progression(racine, ids):
    lignes = "\n".join(f"| `{i}` | note |" for i in ids)
    (racine / "PROGRESSION.md").write_text(f"# Progression\n\n## Adoptions\n\n| Id de l'entrée | Note |\n|---|---|\n{lignes}\n\n## Autre\n", encoding="utf-8")


def test_adoption_declaree_en_attente_compte_comme_lot_du(tmp_path):
    base_kb(tmp_path, "inconnu")
    assert orc.lots_dus(tmp_path, "claude") == 0, "rien n'est dû sans adoption déclarée"
    progression(tmp_path, ["claude-code-commandes-foo"])
    assert orc.lots_dus(tmp_path, "claude") == 1, "adoption déclarée, pas encore appliquée : l'étape kb doit partir"
    assert orc.adoptions_en_attente(tmp_path, "openai", {}) == 0, "une adoption d'un autre périmètre ne compte pas"


def test_adoption_deja_appliquee_ou_id_inconnu_ne_compte_pas(tmp_path):
    base_kb(tmp_path, "utilise")
    progression(tmp_path, ["claude-code-commandes-foo", "claude-code-commandes-inexistante"])
    assert orc.lots_dus(tmp_path, "claude") == 0


def test_lots_dus_ne_modifie_jamais_la_base(tmp_path):
    base_kb(tmp_path, "inconnu")
    progression(tmp_path, ["claude-code-commandes-foo"])
    avant = (tmp_path / "docs/data/kb/claude/commandes.json").read_bytes()
    orc.lots_dus(tmp_path, "claude")
    assert (tmp_path / "docs/data/kb/claude/commandes.json").read_bytes() == avant


# --- critères de succès d'une étape Claude ---------------------------------------------------------------------

ATTENDUS = ("delta(claude):",)


@pytest.mark.parametrize("preexistant", [False, True])
def test_refus_supervision_avec_rapport_ecrit_pendant_etape_est_un_avertissement(depot, cfg, preexistant):
    rapport = depot / "rapports" / f"{JOUR}_0416-supervision.md"
    if preexistant:
        rapport.write_text("ancien rapport\n")
        ancien = time.time() - 3600
        os.utime(rapport, (ancien, ancien))
    e = etape(depot, "supervision", "supervision-refus", str(rapport), "RAS\n", supervision=True)
    assert chaine(depot, cfg, [e]).executer() == 0
    assert codes(depot) == {"supervision": 0, "supervision-refus": 125, "chaine": 0}
    assert [l[2] for l in journal(depot)] == ["supervision", "supervision-refus", "chaine"]
    assert all(l[4] == "aucun" for l in journal(depot)), "la supervision ne commite jamais"
    assert rapport.read_text() == "RAS\n"
    log = (depot / "rapports" / "auto" / f"{JOUR}-supervision.log").read_text()
    assert "ok avec avertissement : 1 permission(s) refusée(s), non fatale(s)" in log


@pytest.mark.parametrize("ancien_rapport", [False, True], ids=["sans-rapport", "rapport-anterieur"])
def test_refus_supervision_sans_rapport_ecrit_pendant_etape_reste_fatal(depot, cfg, ancien_rapport):
    if ancien_rapport:
        rapport = depot / "rapports" / f"{JOUR}_0416-supervision.md"
        rapport.write_text("rapport antérieur\n")
        ancien = time.time() - 3600
        os.utime(rapport, (ancien, ancien))
    e = etape(depot, "supervision", "refus", supervision=True)
    c = chaine(depot, cfg, [e])
    assert c.executer() == 1
    assert codes(depot) == {"supervision": 125, "chaine": 1}
    assert "aucun rapport de supervision écrit pendant l'étape" in c.issues[0].detail
    log = (depot / "rapports" / "auto" / f"{JOUR}-supervision.log").read_text()
    assert "aucun rapport de supervision écrit pendant l'étape" in log


@pytest.mark.parametrize("nom, contenu", [
    (f"{JOUR}_0416-supervision.md", ""),
    ("2026-10-01_0416-supervision.md", "rapport d'un autre jour\n"),
    (f"{JOUR}_heure-supervision.md", "heure mal formée\n"),
    (f"{JOUR}_0416-delta.md", "rapport d'une autre étape\n"),
])
def test_refus_supervision_rapport_vide_ou_mal_nomme_ne_suffit_pas(depot, cfg, nom, contenu):
    e = etape(depot, "supervision", "supervision-refus", str(depot / "rapports" / nom), contenu, supervision=True)
    c = chaine(depot, cfg, [e])
    assert c.executer() == 1
    assert codes(depot) == {"supervision": 125, "chaine": 1}
    assert "aucun rapport de supervision écrit pendant l'étape" in c.issues[0].detail


@pytest.mark.parametrize("mode, code", [
    ("supervision-refus-sale", 126),
    ("supervision-refus-erreur", 125),
    ("supervision-refus-is-error", 125),
    ("supervision-refus-exit", 125),
])
def test_refus_supervision_rapport_ne_masque_pas_un_echec(depot, cfg, mode, code):
    rapport = depot / "rapports" / f"{JOUR}_0416-supervision.md"
    e = etape(depot, "supervision", mode, str(rapport), "rapport écrit\n", supervision=True)
    assert chaine(depot, cfg, [e]).executer() == 1
    assert codes(depot) == {"supervision": code, "chaine": 1}


def test_refus_sans_commit_reste_fatal_code_125(depot, cfg):
    """Le cas du 04:02 : après un refus, la skill s'arrête proprement ; subtype success ne suffit pas, rien n'a été produit."""
    assert chaine(depot, cfg, [etape(depot, "delta", "refus", attendus=ATTENDUS)]).executer() == 1
    assert codes(depot)["delta"] == orc.CODE_PERMISSION == 125
    assert "ls /etc" in (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()
    assert "l'étape n'a pas produit son résultat" in (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()


def test_refus_avec_commit_attendu_pousse_est_un_avertissement(depot, cfg):
    e = etape(depot, "delta", "refus-commit", "docs/data/claude", "a.json", attendus=ATTENDUS)
    assert chaine(depot, cfg, [e, etape(depot, "supervision", "supervision", supervision=True)]).executer() == 0
    assert codes(depot) == {"delta": 0, "delta-refus": 125, "supervision": 0, "chaine": 0}, "ligne d'avertissement, chaîne sans échec"
    lignes = {l[2]: l for l in journal(depot)}
    assert lignes["delta"][4] != "aucun" and lignes["delta-refus"][4] == "aucun"
    log = (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()
    assert "ok avec avertissement : 1 permission(s) refusée(s), non fatale(s)" in log and "sed -n" in log
    assert ahead(depot) == 0 and (depot / "docs/data/claude/a.json").exists()


def test_refus_avec_commit_d_un_autre_sujet_reste_fatal(depot, cfg):
    """Un commit d'autrui (un pull de l'étape) ou un mauvais sujet ne vaut pas résultat de l'étape."""
    e = etape(depot, "delta", "refus-mauvais-sujet", "docs/data/claude", "a.json", attendus=ATTENDUS)
    assert chaine(depot, cfg, [e]).executer() == 1 and codes(depot)["delta"] == 125
    assert "commit(s) attendu(s) absent(s) : delta(claude):" in (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()


def test_refus_sans_commit_attendu_declare_reste_fatal(depot, cfg):
    e = etape(depot, "delta", "refus-commit", "docs/data/claude", "a.json")  # aucun commits_attendus
    assert chaine(depot, cfg, [e]).executer() == 1 and codes(depot)["delta"] == 125


def test_refus_avec_arbre_sale_donne_126_pas_un_avertissement(depot, cfg):
    e = etape(depot, "delta", "refus-sale", "docs/data/claude", "a.json", attendus=ATTENDUS, checkout=["docs/data/claude"])
    assert chaine(depot, cfg, [e]).executer() == 1
    assert codes(depot)["delta"] == orc.CODE_ETAT and "delta-refus" not in codes(depot)


def test_refus_avec_commit_non_pousse_donne_15(depot, cfg):
    e = etape(depot, "delta", "refus-non-pousse", "docs/data/claude", "a.json", attendus=ATTENDUS)
    assert chaine(depot, cfg, [e]).executer() == 1
    assert codes(depot)["delta"] == 15 and "delta-refus" not in codes(depot)


def test_refus_et_resultat_en_erreur_reste_fatal_125(depot, cfg):
    assert chaine(depot, cfg, [etape(depot, "delta", "refus-echec", attendus=ATTENDUS)]).executer() == 1
    assert codes(depot)["delta"] == 125
    assert "permission(s) refusée(s)" in (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()


def test_la_chaine_continue_apres_un_avertissement_de_refus(depot, cfg):
    etapes = [etape(depot, "delta", "refus-commit", "docs/data/claude", "a.json", attendus=ATTENDUS),
              etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "b.json", agent="codex", garde="codex-delta")]
    assert chaine(depot, cfg, etapes).executer() == 0
    assert codes(depot)["codex-delta"] == 0 and (depot / "docs/data/openai/b.json").exists()


def test_refus_permission_lit_les_commandes_et_les_fichiers():
    j = json.dumps({"permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "ls /etc"}},
                                           {"tool_name": "Write", "tool_input": {"file_path": "raw/x.json"}}]})
    assert orc.refus_permission(orc.Resultat(0, j, "", False, 1)) == ["ls /etc", "raw/x.json"]
    assert orc.refus_permission(orc.Resultat(0, "pas du json", "", False, 1)) == []


def test_sortie_claude_illisible_fait_echouer_l_etape(depot, cfg):
    assert chaine(depot, cfg, [etape(depot, "delta", "pas-json")]).executer() == 1
    assert codes(depot)["delta"] != 0


def test_evaluer_claude_exige_success_et_aucun_is_error():
    ok = orc.Resultat(0, json.dumps({"subtype": "success", "is_error": False, "permission_denials": []}), "", False, 1)
    assert orc.evaluer_claude(ok)[0] == 0
    for d in ({"subtype": "error_max_turns", "is_error": False, "permission_denials": []},
              {"subtype": "success", "is_error": True, "permission_denials": []}):
        assert orc.evaluer_claude(orc.Resultat(0, json.dumps(d), "", False, 1))[0] == 1
    assert orc.evaluer_claude(orc.Resultat(2, json.dumps({"subtype": "success", "is_error": False}), "", False, 1))[0] == 2


# --- état final : jamais de push, jamais d'index.lock supprimé, arbre propre ------------------------------------

def test_commit_non_pousse_arrete_la_chaine_code_15(depot, cfg):
    etapes = [etape(depot, "delta", "non-pousse", "docs/data/claude", "a.json"),
              etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "b.json", agent="codex", garde="codex-delta"),
              etape(depot, "supervision", "supervision", supervision=True)]
    assert chaine(depot, cfg, etapes).executer() == 1
    assert codes(depot)["delta"] == 15 and codes(depot)["codex-delta"] == orc.CODE_NON_LANCEE
    assert ahead(depot) == 1, "l'orchestrateur ne pousse jamais : le commit reste local"
    assert (depot / "rapports" / "supervision-lancee.txt").exists()


def test_chaine_arretee_sur_15_au_depart_une_etape_ne_pousse_pas_le_commit_d_une_autre(depot, cfg):
    depot.sh("git", "commit", "-q", "--allow-empty", "-m", "local non validé")  # déjà présent avant la chaîne
    etapes = [etape(depot, "delta", "ok", "docs/data/claude", "a.json"), etape(depot, "supervision", "supervision", supervision=True)]
    assert chaine(depot, cfg, etapes).executer() == 1
    assert codes(depot)["delta"] == 15, "la garde arrête la chaîne avant toute étape"
    assert not (depot / "docs/data/claude/a.json").exists() and ahead(depot) == 1


def test_index_lock_laisse_par_une_etape_n_est_jamais_supprime(depot, cfg):
    assert chaine(depot, cfg, [etape(depot, "delta", "verrou-git")]).executer() == 1
    assert codes(depot)["delta"] == orc.CODE_ETAT and (depot / ".git" / "index.lock").exists()


def test_arbre_sale_hors_des_chemins_meme_apres_succes_arrete_la_chaine(depot, cfg):
    assert chaine(depot, cfg, [etape(depot, "delta", "sale-hors-chemins", checkout=["docs/data/claude"])]).executer() == 1
    assert codes(depot)["delta"] == orc.CODE_ETAT
    assert (depot / "notes.txt").read_text() == "touché hors périmètre\n"



# --- garde : étapes sautées, quota ------------------------------------------------------------------------------

def test_quota_claude_saute_les_etapes_claude_et_pas_codex(depot, cfg):
    (depot / "rapports" / "usage.json").write_text(json.dumps({"claude": {"session_5h": {"pct": 95}, "semaine": {"pct": 20}},
                                                               "chatgpt": {"semaine": {"pct": 100}}}))
    etapes = [etape(depot, "delta", "ok", "docs/data/claude", "a.json"),
              etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "b.json", agent="codex", garde="codex-delta")]
    assert chaine(depot, cfg, etapes).executer() == 0, "une étape sautée par la garde (11) n'est pas un échec"
    assert codes(depot)["delta"] == 11 and codes(depot)["codex-delta"] == 0, "aucun arrêt Codex sur seuil, même à 100 %"
    assert not (depot / "docs/data/claude/a.json").exists() and (depot / "docs/data/openai/b.json").exists()


def test_passage_du_jour_deja_fait_est_saute_code_12(depot, cfg):
    f = depot / "docs" / "data" / "openai" / f"{JOUR.isoformat()}.json"
    f.write_text(json.dumps({"genere_le": "2026-10-02T04:30:00+02:00"}))
    depot.sh("git", "add", str(f))
    depot.sh("git", "commit", "-qm", "openai du jour")
    depot.sh("git", "push", "-q", "origin", "HEAD:refs/heads/main")
    e = etape(depot, "codex-delta", "ok-codex", "docs/data/openai", "b.json", agent="codex", garde="codex-delta")
    assert chaine(depot, cfg, [e]).executer() == 0 and codes(depot)["codex-delta"] == 12


# --- étapes kb ----------------------------------------------------------------------------------------------------

def test_etapes_kb_sautees_sans_lot_du_ligne_a_zero(depot, cfg):
    etapes = [etape(depot, "delta-kb", "ok", "docs/data/kb/claude", "c.json", garde="delta-kb", kb="claude"),
              etape(depot, "codex-delta-kb", "ok-codex", "docs/data/kb/openai", "d.json", agent="codex", garde="codex-delta-kb", kb="openai")]
    assert chaine(depot, cfg, etapes, compte_lots=lambda r, p: 0).executer() == 0
    assert codes(depot) == {"delta-kb": orc.CODE_SANS_LOT, "codex-delta-kb": orc.CODE_SANS_LOT, "chaine": 0}
    assert not (depot / "docs/data/kb/claude/c.json").exists()
    lignes = [l for l in journal(depot) if l[1] == "orchestrateur" and l[2] != "chaine"]
    assert all(l[3] == "0 éléments (0 fort)" and l[4] == "aucun" for l in lignes)


def test_lots_dus_lit_la_vraie_base(depot):
    """lots_dus s'appuie sur catalogue (lot perimees et lots ordinaires) : sur la base réelle du dépôt, un entier positif ou nul."""
    n = orc.lots_dus(RACINE, "claude")
    assert isinstance(n, int) and n >= 0


# --- journal ---------------------------------------------------------------------------------------------------------

def test_journal_format_et_ajout_seulement(depot, cfg):
    f = depot / "rapports" / "passages.log"
    f.write_text("2026-10-01_0707 | delta-ia | claude | 1 éléments (0 fort) | 6876aea | 0\n")
    chaine(depot, cfg, [etape(depot, "delta", "ok-sans-commit")]).executer()
    lignes = f.read_text().splitlines()
    assert lignes[0] == "2026-10-01_0707 | delta-ia | claude | 1 éléments (0 fort) | 6876aea | 0", "jamais réécrit"
    for l in lignes[1:]:
        champs = l.split(" | ")
        assert len(champs) == 6 and champs[1] == "orchestrateur" and champs[3] == "0 éléments (0 fort)"
    assert [l.split(" | ")[2] for l in lignes[1:]] == ["delta", "chaine"]


def test_l_orchestrateur_ne_touche_jamais_a_raw(depot, cfg):
    (depot / "raw" / "historique" / "2026-10-01").mkdir(parents=True)
    h = depot / "raw" / "historique" / "2026-10-01" / "claude-nouveautes-070000.json"
    h.write_text("{}")
    avant = h.stat().st_mtime_ns
    chaine(depot, cfg, [etape(depot, "delta", "echec", "docs/data/claude", checkout=["docs/data/claude"], clean=["docs/data/claude"])]).executer()
    assert h.exists() and h.stat().st_mtime_ns == avant


# --- configuration réelle : syntaxe vérifiée sur les --help des versions installées ------------------------------

def test_commandes_reelles_syntaxe_et_interdits():
    cfg = orc.charger_config()
    etapes = {e.nom: e for e in orc.construire_etapes(cfg, RACINE)}
    assert list(etapes) == ["delta", "codex-delta", "delta-kb", "codex-delta-kb", "supervision"]
    tout = " ".join(" ".join(e.commande) for e in etapes.values())
    for interdit in ("--dangerously", "bypassPermissions", "--approve-for-me", "danger-full-access", "--allow-dangerously-skip-permissions"):
        assert interdit not in tout, interdit
    for nom in ("delta", "delta-kb", "supervision"):
        c = etapes[nom].commande
        assert c[1] == "-p" and "--permission-mode" in c and c[c.index("--permission-mode") + 1] == "dontAsk"
        assert c[c.index("--permission-prompts") + 1] == "none" and "--strict-mcp-config" in c
        assert c[c.index("--output-format") + 1] == "json"
    assert etapes["delta"].commande[etapes["delta"].commande.index("--setting-sources") + 1] == "project"
    sup = etapes["supervision"].commande
    assert sup[sup.index("--setting-sources") + 1] == "" and sup[sup.index("--settings") + 1].endswith(".claude/supervision.settings.json")
    assert sup[2] == (RACINE / "prompts" / "supervision.md").read_text(encoding="utf-8")
    for nom in ("codex-delta", "codex-delta-kb"):
        c = etapes[nom].commande
        assert c[1:3] == ["exec", "--ignore-user-config"] and c[0] == "/usr/lib/chatgpt/resources/codex"
        assert 'default_permissions="delta_auto"' in c and 'approval_policy="never"' in c
        assert 'permissions.delta_auto.network.enabled=true' in c and 'permissions.delta_auto.extends=":workspace"' in c
        assert 'permissions.delta_auto.filesystem={":workspace_roots"={".git"="write"}}' in c
    assert etapes["delta"].commande[-6:] == ["--model", "sonnet", "--effort", "high", "--setting-sources", "project"]
    assert etapes["delta-kb"].commande[etapes["delta-kb"].commande.index("--model") + 1] == "opus"
    assert all(e.delai_s == 45 * 60 for n, e in etapes.items() if n != "supervision") and etapes["supervision"].delai_s == 15 * 60


def test_arret_propre_declare_comme_en_d68():
    cfg = orc.charger_config()
    e = {x.nom: x for x in orc.construire_etapes(cfg, RACINE)}
    assert e["delta"].checkout == ["docs/data/versions.json", "docs/data/etat.json", "docs/data/claude", "docs/data/actu",
                                   "docs/data/kb/claude", "state/claude.json", "state/actu.json"]
    assert e["delta"].clean == ["docs/data/claude", "docs/data/actu"]
    assert e["codex-delta"].checkout == ["docs/data/openai", "docs/data/kb/openai", "state/openai.json"]
    assert e["delta-kb"].checkout == e["delta-kb"].clean == ["docs/data/kb/claude"]
    assert e["codex-delta-kb"].checkout == e["codex-delta-kb"].clean == ["docs/data/kb/openai"]
    assert e["supervision"].checkout == [] and e["supervision"].clean == []
    for n in ("delta", "codex-delta", "delta-kb", "codex-delta-kb"):  # jamais raw/, rapports/, PROGRESSION, CONTEXTE, SPEC, REGLES, scripts
        assert all(c.startswith(("docs/data/", "state/")) for c in e[n].checkout + e[n].clean)


def test_supervision_settings_lecture_seule():
    s = json.loads((RACINE / ".claude" / "supervision.settings.json").read_text(encoding="utf-8"))["permissions"]
    for r in s["allow"]:
        assert r.startswith(("Bash(git log", "Bash(git status", "Bash(git rev-parse", "Bash(git rev-list", "Bash(find rapports", "Bash(tail -n",
                             "Bash(date +", "Edit(rapports/*-supervision.md)")), r
    assert "Edit(rapports/*-supervision.md)" in s["allow"] and len([r for r in s["allow"] if r.startswith("Edit(")]) == 1
    assert {"Bash(git push *)", "Bash(git commit *)", "Bash(find * -exec *)", "Bash(find * -delete*)", "Bash(git * --output*)"} <= set(s["deny"])
    assert not any("python" in r or "passages" in r or r.startswith("Bash(git add") for r in s["allow"])


def test_nouvelles_regles_du_projet_sans_joker_dangereux():
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    for r in ("Bash(.venv/bin/python scripts/catalogue.py lots *)", "Bash(.venv/bin/python scripts/catalogue.py a-commenter *)",
              "Bash(.venv/bin/python scripts/catalogue.py adoptions *)", "Bash(.venv/bin/python scripts/catalogue.py reevaluations *)",
              "Bash(git add docs/data/kb/claude)", 'Bash(git commit -m "delta-kb(claude): *")'):
        assert r in s["allow"], r
    assert not any("bypassPermissions" in r or "dangerously" in r for r in s["allow"] + s["deny"])


@pytest.mark.parametrize("fichier", [".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta/SKILL.md", ".agents/skills/delta-kb/SKILL.md"])
def test_skills_ont_leur_section_mode_automatique_d70(fichier):
    t = (RACINE / fichier).read_text(encoding="utf-8")
    assert "## Mode automatique (D70)" in t and "--etape" in t and "Aucune question" in t
    assert "orchestrateur remet lui-même en place" in t, "le nettoyage est celui de l'orchestrateur, pas d'un LLM"
    assert "un seul push" in t.lower() or "`git push` une seule fois" in t


def test_delta_n_exclut_plus_le_kb_en_automatique():
    t = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "ne tourne jamais en mode automatique" not in t and "étape suivante de la chaîne D70" in t


# --- passage-auto.sh : verrou de la chaîne ---------------------------------------------------------------------------

# Le faux binaire lit sa durée de sommeil dans un fichier : l'environnement des étapes est fixé par l'orchestrateur, jamais hérité.
FAUX_BIN = '#!/bin/sh\nsleep "$(cat "$(dirname "$0")/sommeil" 2>/dev/null || echo 0)"\necho \'{"type":"result","subtype":"success","is_error":false,"permission_denials":[]}\'\n'


@pytest.fixture
def depot_sh(depot, tmp_path):
    """Le dépôt de test reçoit scripts/, un .venv/bin/python (celui des tests) et une configuration dont les binaires sont faux."""
    shutil.copytree(RACINE / "scripts", depot / "scripts", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (depot / ".venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, depot / ".venv" / "bin" / "python")
    faux = tmp_path / "faux-bin.sh"
    faux.write_text(FAUX_BIN)
    faux.chmod(0o755)
    depot.sommeil = tmp_path / "sommeil"
    (depot / "prompts").mkdir(exist_ok=True)
    (depot / "prompts" / "supervision.md").write_text("supervision")
    toml = (RACINE / "scripts" / "orchestrateur.toml").read_text(encoding="utf-8")
    toml = toml.replace('bin = "~/.local/bin/claude"', f'bin = "{faux}"').replace('bin = "/usr/lib/chatgpt/resources/codex"', f'bin = "{faux}"')
    toml = toml.replace("delai_min = 45", "delai_min = 1")
    (tmp_path / "faux.toml").write_text(toml)
    depot.sh("git", "add", "-A")
    depot.sh("git", "commit", "-qm", "scripts")
    depot.sh("git", "push", "-q", "origin", "HEAD:refs/heads/main")
    depot.toml = tmp_path / "faux.toml"
    return depot


def test_passage_auto_une_seule_chaine_a_la_fois(depot_sh):
    r = depot_sh
    env = dict(os.environ)
    r.sommeil.write_text("10")
    cmd = [str(r / "scripts" / "passage-auto.sh"), "--config", str(r.toml), "--etapes", "delta"]
    premiere = subprocess.Popen(cmd, cwd=r, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    verrou = r / ".git" / "delta-passage.lock"
    for _ in range(100):
        if verrou.exists() and verrou.read_text().strip():
            break
        time.sleep(0.1)
    pid = int(verrou.read_text().strip())
    assert pid == premiere.pid, "le PID écrit est celui de l'orchestrateur (exec garde le PID du script)"
    seconde = subprocess.run(cmd, cwd=r, env=env, capture_output=True, text=True)
    assert seconde.returncode == 14 and "déjà en cours" in seconde.stderr
    # une relance manuelle de la garde pendant la chaîne s'arrête net (14) ; un appel de la chaîne (même PID) passe
    manuel = subprocess.run([sys.executable, str(r / "scripts" / "garde.py"), "--racine", str(r), "--date", JOUR.isoformat()],
                            capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "DELTA_CHAINE_PID"})
    assert manuel.returncode == 14
    de_la_chaine = subprocess.run([sys.executable, str(r / "scripts" / "garde.py"), "--racine", str(r), "--date", JOUR.isoformat()],
                                  capture_output=True, text=True, env={**os.environ, "DELTA_CHAINE_PID": str(pid)})
    assert "cet appel en fait partie" in de_la_chaine.stdout
    out, err = premiere.communicate(timeout=60)
    assert premiere.returncode == 0, err
    # le verrou est relâché à la fin : la chaîne suivante part
    r.sommeil.write_text("0")
    troisieme = subprocess.run(cmd, cwd=r, env=env, capture_output=True, text=True)
    assert troisieme.returncode == 0, troisieme.stderr


def test_passage_auto_option_liste_n_appelle_rien(depot_sh):
    r = subprocess.run([str(depot_sh / "scripts" / "passage-auto.sh"), "--config", str(depot_sh.toml), "--liste"], cwd=depot_sh,
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.count("\n") == 5 and "supervision" in r.stdout, "paliers 2 et 3 : quatre étapes et la supervision"
    assert r.stdout.startswith("delta (délai 1 min)")  # la configuration de test raccourcit les délais


# --- paliers de déploiement : étapes actives par configuration (01/10/2026) ------------------------------------------

TOUTES = ["delta", "codex-delta", "delta-kb", "codex-delta-kb", "supervision"]


def noms(cfg_modif=None, option=None):
    cfg = orc.charger_config()
    if cfg_modif is not None:
        cfg["chaine"]["etapes_actives"] = cfg_modif
    return [e.nom for e in orc.etapes_a_lancer(cfg, orc.construire_etapes(cfg, RACINE), option)]


def test_paliers_2_et_3_actives_d_un_coup_le_02_10():
    assert orc.charger_config()["chaine"]["etapes_actives"] == ["delta", "codex-delta", "delta-kb", "codex-delta-kb"]
    assert noms() == TOUTES
    assert noms(["delta"]) == ["delta", "supervision"], "le palier 1 reste un retour arrière d'une ligne"


def test_paliers_2_et_3_sans_toucher_au_code():
    assert noms(["delta", "codex-delta"]) == ["delta", "codex-delta", "supervision"]
    assert noms(["delta", "codex-delta", "delta-kb", "codex-delta-kb"]) == TOUTES
    assert noms(["codex-delta", "delta"]) == ["delta", "codex-delta", "supervision"], "l'ordre de la chaîne ne dépend pas de la liste"


def test_liste_vide_ne_lance_que_la_supervision_et_sans_liste_tout_tourne():
    assert noms([]) == ["supervision"]
    cfg = orc.charger_config()
    del cfg["chaine"]["etapes_actives"]
    assert [e.nom for e in orc.etapes_a_lancer(cfg, orc.construire_etapes(cfg, RACINE))] == TOUTES


def test_option_etapes_prime_sur_la_configuration_pour_les_essais():
    assert noms(option="codex-delta") == ["codex-delta"]
    assert noms(option="delta,supervision") == ["delta", "supervision"]


def test_etape_inconnue_ou_supervision_dans_la_liste_est_refusee():
    cfg = orc.charger_config()
    etapes = orc.construire_etapes(cfg, RACINE)
    for mauvaise in (["delta", "inconnue"], ["supervision"]):
        cfg["chaine"]["etapes_actives"] = mauvaise
        with pytest.raises(ValueError):
            orc.etapes_a_lancer(cfg, etapes)
    with pytest.raises(ValueError):
        orc.etapes_a_lancer(cfg, etapes, "inconnue")


def test_orchestrateur_refuse_une_configuration_incorrecte_code_2(depot_sh):
    toml = depot_sh.toml.read_text().replace('etapes_actives = ["delta", "codex-delta", "delta-kb", "codex-delta-kb"]', 'etapes_actives = ["delta", "nimporte"]')
    assert "nimporte" in toml
    depot_sh.toml.write_text(toml)
    r = subprocess.run([str(depot_sh / "scripts" / "passage-auto.sh"), "--config", str(depot_sh.toml), "--liste"], cwd=depot_sh,
                       capture_output=True, text=True)
    assert r.returncode == 2 and "nimporte" in r.stderr


def test_le_fichier_documente_les_trois_paliers():
    t = (RACINE / "scripts" / "orchestrateur.toml").read_text(encoding="utf-8")
    for attendu in ("palier 1, nuit de réception", "palier 2, jours 1 et 2", "palier 3, après deux jours propres",
                    'etapes_actives = ["delta", "codex-delta", "delta-kb", "codex-delta-kb"]', "sans toucher au code", "TOUJOURS en dernier"):
        assert attendu in t, attendu


def test_timer_a_04h00_et_fenetre_sans_commit_documentee():
    timer = (RACINE / "deploy" / "systemd" / "delta-passage.timer.exemple").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 04:00:00" in timer and "Persistent=true" in timer and "04:30" not in timer
    for f in ("CLAUDE.md", "AGENTS.md"):
        t = (RACINE / f).read_text(encoding="utf-8")
        assert "de 03 h 30 à 08 h 00" in t and "04 h 00" in t and "heures fixées par Sylvain" not in t, f


def test_supervision_connait_les_etapes_actives():
    t = (RACINE / "prompts" / "supervision.md").read_text(encoding="utf-8")
    assert "`etapes_actives` de `scripts/orchestrateur.toml`" in t and "une étape inactive n'a aucune ligne" in t


# --- correctif du refus de 04:02 (02/10/2026) -----------------------------------------------------------------------

def test_commits_attendus_declares_par_etape():
    e = {x.nom: x for x in orc.construire_etapes(orc.charger_config(), RACINE)}
    assert e["delta"].commits_attendus == ["delta(claude):", "delta(actu):"]
    assert e["codex-delta"].commits_attendus == ["delta(openai):"]
    assert e["delta-kb"].commits_attendus == ["delta-kb(claude):"] and e["codex-delta-kb"].commits_attendus == ["delta-kb(openai):"]
    assert e["supervision"].commits_attendus == []


def test_settings_projet_lectures_git_sans_sed_ni_git_diff():
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    for r in ("Bash(git log *)", "Bash(git show *)", "Bash(git status)", "Bash(git status --short)"):
        assert r in s["allow"], r
    assert "Bash(git * --output*)" in s["deny"], "git log et git show acceptent --output=fichier"
    assert not any(r.startswith("Bash(sed") or "sed -n" in r for r in s["allow"]), "pas de sed : sed -n -i et sed -n 'w f' écrivent"
    assert not any(r.startswith("Bash(git diff") for r in s["allow"]), "git diff accepte --output="


@pytest.mark.parametrize("fichier", [".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta/SKILL.md",
                                     ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md", "prompts/codex-delta-kb.md"])
def test_skills_reprennent_un_refus_de_lecture_au_lieu_d_arreter(fichier):
    t = (RACINE / fichier).read_text(encoding="utf-8")
    assert "Un refus de lecture ne tue pas le passage" in t and "UNE fois" in t
    assert "deuxième refus pour le même besoin" in t and "en écriture" in t
    assert "outil refusé" in t or "commande refusée" in t


def test_skills_claude_lisent_la_base_avec_read():
    for f in (".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md"):
        t = (RACINE / f).read_text(encoding="utf-8")
        assert "`Read` avec `offset` et `limit`" in t and "jamais de boucle shell" in t, f
        if f == ".claude/skills/delta/SKILL.md":
            assert "Toute retouche du fichier du jour, de `index.json` ou d'un autre JSON" in t
            assert "Edit (ou Write pour un fichier entier)" in t
            assert "jamais avec `.venv/bin/python -` / heredoc ni avec `python -c`" in t
            assert "Seule exception" in t and "calcul `id_web`" in t
            assert "une commande simple par appel, sans boucle" in t


def test_supervision_sait_lire_la_ligne_refus():
    t = (RACINE / "prompts" / "supervision.md").read_text(encoding="utf-8")
    assert "<étape>-refus" in t and "AVERTISSEMENT" in t and "125 permission refusée, fatale" in t


def test_supervision_impose_une_commande_simple_et_lit_les_fichiers_avec_read():
    t = (RACINE / "prompts" / "supervision.md").read_text(encoding="utf-8")
    assert "une commande simple par appel" in t and "ls raw/" not in t
    assert "`ls`, `grep`, `cat` et `sed` ne sont pas autorisés" in t
    assert "Un refus ne se retente pas" in t and "sans boucle" in t
    for point in ("5. Fraîcheur", "7. Échéances"):
        ligne = next(l for l in t.splitlines() if l.startswith(point))
        assert "Read" in ligne and "chemin exact" in ligne
    assert "`limit` court" in t
