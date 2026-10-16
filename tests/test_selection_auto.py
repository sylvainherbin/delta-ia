"""Production S1, publication dans un distant local jetable et unités systemd (sans installation)."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import selection_auto as auto
import retour as retour_cli
from deltalib import selection as sel
from test_selection import depot, douze, lancer

RACINE = Path(__file__).resolve().parent.parent
LUNDI = date(2026, 10, 19)
SEMAINE = "2026-W43"


def git(racine, *args):
    return subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def publication(tmp_path, monkeypatch):
    # Ni réseau, ni configuration personnelle (signature, helpers ou hooks) dans ces dépôts d'essai.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    racine = depot(tmp_path, douze())
    shutil.copyfile(RACINE / ".gitignore", racine / ".gitignore")
    (racine / "scripts").mkdir()
    (racine / "scripts/valider.py").write_text("raise SystemExit(0)\n")
    git(racine, "init", "-b", "main")
    git(racine, "config", "user.name", "Test S1")
    git(racine, "config", "user.email", "s1@example.test")
    git(racine, "add", ".")
    git(racine, "commit", "-m", "Base de test")
    distant = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(distant)], check=True, capture_output=True)
    git(racine, "remote", "add", "origin", str(distant))
    git(racine, "push", "-u", "origin", "main")
    return racine, distant


def fichiers(racine):
    return [racine / sel.DOSSIER / f"{SEMAINE}.{ext}" for ext in ("json", "md")]


def test_production_publication_et_relance_sans_nouveau_commit(publication):
    racine, distant = publication
    auto.executer(racine, LUNDI)
    doc = json.loads(fichiers(racine)[0].read_text())
    assert doc["semaine"] == SEMAINE and doc["jour"] == "2026-10-19"
    assert len(doc["entrees"]) == 5
    assert git(racine, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() == [
        f"rapports/selection/{SEMAINE}.json", f"rapports/selection/{SEMAINE}.md"]
    assert git(distant, "rev-parse", "main") == git(racine, "rev-parse", "HEAD")
    avant = git(racine, "rev-parse", "HEAD")
    auto.executer(racine, date(2026, 10, 20))
    assert git(racine, "rev-parse", "HEAD") == avant
    assert not git(racine, "status", "--porcelain")


@pytest.mark.parametrize("etat", ["non-suivi", "index", "modifie", "bref-manquant"])
def test_publication_prend_en_charge_la_semaine_anterieure(publication, etat):
    racine, distant = publication
    assert lancer(racine, "--json") == 0  # même appel que la Console, semaine W42
    dossier = racine / sel.DOSSIER
    anciens = [f"rapports/selection/2026-W42.{ext}" for ext in ("json", "md")]
    if etat in ("index", "modifie"):
        git(racine, "add", "--", *anciens)
    if etat == "modifie":
        git(racine, "commit", "-m", "Ancienne sélection publiée")
        git(racine, "push", "origin", "main")
        assert lancer(racine, "--json", "--refaire", "--taille", "3") == 0
    if etat == "bref-manquant":
        (dossier / "2026-W42.md").unlink()
    figee = (dossier / "2026-W42.json").read_bytes()

    auto.executer(racine, LUNDI)

    assert git(distant, "rev-parse", "main") == git(racine, "rev-parse", "HEAD")
    assert set(git(racine, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == {
        *anciens, *(f"rapports/selection/{SEMAINE}.{ext}" for ext in ("json", "md"))}
    assert (dossier / "2026-W42.json").read_bytes() == figee
    assert git(distant, "show", "main:rapports/selection/2026-W42.json") == figee.decode().strip()
    assert git(distant, "show", "main:rapports/selection/2026-W42.md") == sel.rendre_markdown(
        json.loads(figee)).strip()
    assert not git(racine, "status", "--porcelain")


def test_semaine_courante_deja_publiee_et_ancienne_encore_locale(publication):
    racine, distant = publication
    auto.executer(racine, LUNDI)
    assert lancer(racine, "--json") == 0
    auto.executer(racine, LUNDI)
    assert git(racine, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() == [
        "rapports/selection/2026-W42.json", "rapports/selection/2026-W42.md"]
    assert git(distant, "rev-parse", "main") == git(racine, "rev-parse", "HEAD")
    assert not git(racine, "status", "--porcelain")


def test_aucune_production_avant_le_19(publication):
    racine, distant = publication
    avant = git(distant, "rev-parse", "main")
    auto.executer(racine, date(2026, 10, 18))
    assert not (racine / sel.DOSSIER).exists()
    assert git(distant, "rev-parse", "main") == avant


def test_horloge_de_paris_meme_si_le_jour_utc_est_encore_dimanche(monkeypatch):
    class Horloge:
        @staticmethod
        def now(fuseau):
            return datetime(2026, 10, 18, 22, 45, tzinfo=timezone.utc).astimezone(fuseau)

    appels = []
    monkeypatch.setattr(auto, "datetime", Horloge)
    monkeypatch.setattr(auto, "executer", lambda racine, jour: appels.append(jour))
    assert auto.main([]) == 0
    assert appels == [LUNDI]


@pytest.mark.parametrize("etat", ["non-suivi", "modifie", "index", "commit", "branche"])
def test_refus_de_publier_du_travail_etranger(publication, etat):
    racine, distant = publication
    avant = git(distant, "rev-parse", "main")
    if etat == "branche":
        git(racine, "checkout", "-b", "mission")
    elif etat == "modifie":
        (racine / "profil.yaml").write_text("priorites: []\n")
    else:
        (racine / "autre.txt").write_text("travail étranger")
        if etat in ("index", "commit"):
            git(racine, "add", "autre.txt")
        if etat == "commit":
            git(racine, "commit", "-m", "Étranger")
    with pytest.raises(RuntimeError):
        auto.executer(racine, LUNDI)
    assert not (racine / sel.DOSSIER).exists()
    assert git(distant, "rev-parse", "main") == avant


def test_ancienne_selection_ne_permet_pas_de_publier_un_fichier_etranger(publication):
    racine, distant = publication
    assert lancer(racine, "--json") == 0
    (racine / "profil.yaml").write_text("priorites: []\n")
    avant = git(distant, "rev-parse", "main")
    with pytest.raises(RuntimeError, match="hors sélection"):
        auto.executer(racine, LUNDI)
    assert git(racine, "rev-parse", "HEAD") == avant
    assert git(distant, "rev-parse", "main") == avant
    assert not fichiers(racine)[0].exists()


@pytest.mark.parametrize("nom", ["2026-W42.json.bak", "2026-W42.txt", "notes.md", "retours.yaml", "retours.yaml.lock"])
def test_domaine_ne_couvre_pas_tout_le_dossier(publication, nom):
    racine, distant = publication
    dossier = racine / sel.DOSSIER
    dossier.mkdir(parents=True)
    chemin = dossier / nom
    chemin.write_text("[]\n")
    # Même un fichier privé indexé par erreur ne doit pas être publié.
    git(racine, "add", "-f", "--", str(chemin.relative_to(racine)))
    avant = git(distant, "rev-parse", "main")
    with pytest.raises(RuntimeError, match="hors sélection"):
        auto.executer(racine, LUNDI)
    assert git(racine, "rev-parse", "HEAD") == git(distant, "rev-parse", "main") == avant


def test_validation_en_echec_ne_commite_ni_ne_pousse(publication):
    racine, distant = publication
    (racine / "scripts/valider.py").write_text("raise SystemExit(1)\n")
    git(racine, "add", "scripts/valider.py")
    git(racine, "commit", "-m", "Validation défaillante de test")
    git(racine, "push", "origin", "main")
    avant = git(racine, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="valider.py"):
        auto.executer(racine, LUNDI)
    assert git(racine, "rev-parse", "HEAD") == git(distant, "rev-parse", "main") == avant


@pytest.mark.parametrize("ancienne", [False, True])
def test_reprise_du_seul_commit_apres_echec_push(publication, ancienne):
    racine, distant = publication
    if ancienne:
        assert lancer(racine, "--json") == 0
    hook = distant / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match="push"):
        auto.executer(racine, LUNDI)
    commit = git(racine, "rev-parse", "HEAD")
    assert commit != git(distant, "rev-parse", "main")
    hook.unlink()
    auto.executer(racine, LUNDI)
    assert git(distant, "rev-parse", "main") == git(racine, "rev-parse", "HEAD") == commit


def test_reprise_refuse_un_commit_au_bon_titre_avec_fichier_etranger(publication):
    racine, distant = publication
    assert lancer(racine, "--json", jour=LUNDI.isoformat()) == 0
    (racine / "profil.yaml").write_text("priorites: []\n")
    git(racine, "add", "--", "profil.yaml", *(str(f.relative_to(racine)) for f in fichiers(racine)))
    git(racine, "commit", "-m", f"delta(selection): {SEMAINE} — sélection hebdomadaire")
    avant = git(distant, "rev-parse", "main")
    with pytest.raises(RuntimeError, match="commit local non publié"):
        auto.executer(racine, LUNDI)
    assert git(distant, "rev-parse", "main") == avant


def test_reprise_verifie_aussi_le_bref_ancien(publication):
    racine, distant = publication
    assert lancer(racine, "--json") == 0
    assert lancer(racine, "--json", jour=LUNDI.isoformat()) == 0
    (racine / sel.DOSSIER / "2026-W42.md").write_text("bref incohérent\n")
    git(racine, "add", "--", str(sel.DOSSIER))
    git(racine, "commit", "-m", f"delta(selection): {SEMAINE} — sélection hebdomadaire")
    avant = git(distant, "rev-parse", "main")
    with pytest.raises(RuntimeError, match="bref incohérent"):
        auto.executer(racine, LUNDI)
    assert git(distant, "rev-parse", "main") == avant


def test_divergence_apres_commit_refusee(publication, tmp_path):
    racine, distant = publication
    hook = distant / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError):
        auto.executer(racine, LUNDI)
    hook.unlink()
    autre = tmp_path / "autre"
    subprocess.run(["git", "clone", "-b", "main", str(distant), str(autre)], check=True, capture_output=True)
    git(autre, "config", "user.name", "Test")
    git(autre, "config", "user.email", "test@example.test")
    (autre / "nouveau").write_text("avancée distante")
    git(autre, "add", "nouveau")
    git(autre, "commit", "-m", "Autre travail distant")
    git(autre, "push", "origin", "main")
    avant = git(distant, "rev-parse", "main")
    with pytest.raises(RuntimeError, match="divergence"):
        auto.executer(racine, LUNDI)
    assert git(distant, "rev-parse", "main") == avant


def test_avance_rapide_et_sans_distant(publication):
    racine, distant = publication
    git(racine, "commit", "--allow-empty", "-m", "Avancée distante")
    git(racine, "push", "origin", "main")
    # Le recul est limité au dépôt de test pour simuler une copie locale en retard.
    git(racine, "reset", "--hard", "HEAD^")
    auto.executer(racine, LUNDI)
    assert git(racine, "rev-parse", "HEAD") == git(distant, "rev-parse", "main")
    git(racine, "remote", "remove", "origin")
    auto.executer(racine, date(2026, 10, 26))
    assert (racine / sel.DOSSIER / "2026-W44.json").exists()


def test_retour_console_ne_bloque_pas_et_reste_prive(publication):
    racine, distant = publication
    assert lancer(racine, "--json") == 0
    dossier = racine / sel.DOSSIER
    ident = json.loads((dossier / "2026-W42.json").read_text())["entrees"][0]["id"]
    assert retour_cli.main(["--racine", str(racine), "--jour", "2026-10-16", ident, "utile", "--json"]) == 0
    prive = {nom: (dossier / nom).read_bytes() for nom in ("retours.yaml", "retours.yaml.lock")}
    for nom in prive:
        assert git(racine, "check-ignore", str(sel.DOSSIER / nom))
    auto.executer(racine, LUNDI)
    assert git(distant, "rev-parse", "main") == git(racine, "rev-parse", "HEAD")
    assert not git(racine, "status", "--porcelain")
    for nom, contenu in prive.items():
        assert (dossier / nom).read_bytes() == contenu
        assert nom not in git(distant, "ls-tree", "-r", "--name-only", "main")
    assert ident not in {e["id"] for e in json.loads(fichiers(racine)[0].read_text())["entrees"]}


def test_verrou_attend_la_chaine_avant_publication(publication):
    racine, distant = publication
    with (racine / ".git/delta-passage.lock").open("a") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        code = ("import sys; from pathlib import Path; from datetime import date; "
                "import selection_auto as a; print('prêt', flush=True); "
                "a.executer(Path(sys.argv[1]), date(2026,10,19))")
        env = {**os.environ, "PYTHONPATH": str(RACINE / "scripts")}
        proc = subprocess.Popen([sys.executable, "-B", "-c", code, str(racine)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert proc.stdout.readline().strip() == "prêt"
            time.sleep(0.2)
            assert proc.poll() is None and not (racine / sel.DOSSIER).exists()
            fcntl.flock(verrou, fcntl.LOCK_UN)
            _, err = proc.communicate(timeout=15)
            assert proc.returncode == 0, err
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    assert git(distant, "rev-parse", "main") == git(racine, "rev-parse", "HEAD")


def test_unites_calendrier_et_premiere_echeance():
    timer = (RACINE / "deploy/systemd/delta-ia-selection.timer").read_text()
    service = (RACINE / "deploy/systemd/delta-ia-selection.service").read_text()
    assert "Persistent=true" in timer and "TZ=Europe/Paris" in service
    assert "selection_auto.py" in service and "TimeoutStartSec=4h15min" in service
    calendrier = next(l.split("=", 1)[1] for l in timer.splitlines() if l.startswith("OnCalendar="))
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze absent")
    for base, attendu in (("2026-10-15 12:00:00", "2026-10-19 06:30:00 CEST"),
                          ("2026-10-20 12:00:00", "2026-10-26 06:30:00 CET")):
        res = subprocess.run(["systemd-analyze", "calendar", f"--base-time={base}", calendrier],
                             capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Europe/Paris"})
        assert attendu in res.stdout
