"""Séquence des unités rejouée sur un faux dépôt, sans systemd ni import du code sale."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

import orchestrateur as orc

RACINE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("nom", ["commun", "selection"])
@pytest.mark.parametrize("etat", ["propre", "modifie", "index", "non_suivi"])
def test_arret_avant_import_du_module_sale(tmp_path, nom, etat):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "piege.py").write_text("# fixture ordinaire\n")
    (scripts / f"{nom}_auto.py").write_text("import piege\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "XDG_STATE_HOME": str(tmp_path / "etat-xdg")}
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    git("init", "-q")
    git("add", "scripts")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial")
    _reference(tmp_path, env)
    if etat != "propre":
        (scripts / "piege.py").write_text("from pathlib import Path\nPath('IMPORTE').write_text('fixture')\n")
        if etat == "index":
            git("add", "scripts/piege.py")
        elif etat == "non_suivi":
            git("rm", "--cached", "scripts/piege.py")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "retirer du suivi")
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    pre = [l.partition("=")[2] for l in unite.splitlines() if l.startswith("ExecStartPre=")]
    # S'il manque, le simulateur lance directement ExecStart : le témoin importe le piège.
    code = 0
    for ligne in pre:
        resultat = subprocess.run(shlex.split(ligne), cwd=tmp_path, env=env, capture_output=True, text=True)
        code = resultat.returncode
        if code:
            assert "ARBRE_CODE_SALE" in resultat.stderr
            break
    if code == 0:
        subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path, env=env, check=True)
    assert code == (0 if etat == "propre" else 126)
    assert not (tmp_path / "IMPORTE").exists()


def _env_unite(unite: str, tmp_path: Path) -> dict:
    """Environnement que systemd donne à ExecStart : lignes Environment= de l'unité, %h et %t remplacés par des dossiers de test."""
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path / "home"),
           "XDG_STATE_HOME": str(tmp_path / "etat-xdg")}  # jamais le vrai ~/.local/state
    for ligne in unite.splitlines():
        if ligne.startswith("Environment="):
            for affectation in shlex.split(ligne.partition("=")[2]):
                cle, _, valeur = affectation.partition("=")
                env[cle] = valeur.replace("%h", str(tmp_path / "home")).replace("%t", str(tmp_path / "run"))
    return env


def _depot_scripts(tmp_path: Path, nom: str) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\nrapports/\n")  # comme le dépôt : __pycache__/ échappe à git status
    (scripts / "piege.py").write_text("# fixture ordinaire\n")
    (scripts / f"{nom}_auto.py").write_text("import piege\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (["init", "-q"], ["add", ".gitignore", "scripts"],
                 ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial"]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    return scripts


def _reference(tmp_path: Path, env: dict) -> Path:
    """SUITE 4, point 2 : référence de l'empreinte git écrite comme l'orchestrateur à la fin d'une chaîne propre, au chemin
    que l'unité lira avec cet environnement."""
    f = orc.fichier_reference_git(env)
    assert str(f).startswith(str(tmp_path)) and orc.ecrire_reference_git(tmp_path, f) is None
    return f


def _pre(unite: str, tmp_path: Path, env: dict) -> list:
    return [subprocess.run(shlex.split(l.partition("=")[2]), cwd=tmp_path, env=env, capture_output=True, text=True)
            for l in unite.splitlines() if l.startswith("ExecStartPre=")]


@pytest.mark.parametrize("nom", ["commun", "selection"])
def test_pyc_piege_dans_l_arbre_n_est_pas_charge(tmp_path, nom):
    """B2 : un .pyc valide pour la source propre (même mtime, même taille) mais compilé d'un code piégé, posé dans
    scripts/__pycache__/ (ignoré par git) : PYTHONPYCACHEPREFIX de l'unité le fait ignorer."""
    import importlib.util
    import marshal
    scripts = _depot_scripts(tmp_path, nom)
    st = (scripts / "piege.py").stat()
    code = compile("from pathlib import Path\nPath('IMPORTE').write_text('pyc')\n", str(scripts / "piege.py"), "exec")
    pyc = scripts / "__pycache__" / f"piege.{sys.implementation.cache_tag}.pyc"
    pyc.parent.mkdir()
    pyc.write_bytes(importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little") + (int(st.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
                    + (st.st_size & 0xFFFFFFFF).to_bytes(4, "little") + marshal.dumps(code))
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    env = _env_unite(unite, tmp_path)
    _reference(tmp_path, env)
    assert all(r.returncode == 0 for r in _pre(unite, tmp_path, env)), "arbre propre pour git : le piège passe le contrôle"
    temoin = subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path,
                            env={k: v for k, v in env.items() if k != "PYTHONPYCACHEPREFIX"}, check=True)
    assert temoin.returncode == 0 and (tmp_path / "IMPORTE").exists(), "témoin : sans le préfixe, le .pyc piégé est chargé"
    (tmp_path / "IMPORTE").unlink()
    subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path, env=env, check=True)
    assert env["PYTHONPYCACHEPREFIX"] == str(tmp_path / "run" / "delta-ia-pycache")
    assert not (tmp_path / "IMPORTE").exists()


@pytest.mark.parametrize("nom", ["commun", "selection"])
def test_temoin_d_incident_arrete_avant_le_python_du_venv(tmp_path, nom):
    """B2 : témoin d'incident git présent (un .pth ou un hook peut avoir été posé) : ExecStartPre rend 126 avant ExecStart."""
    _depot_scripts(tmp_path, nom)
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    env = _env_unite(unite, tmp_path)
    _reference(tmp_path, env)
    assert all(r.returncode == 0 for r in _pre(unite, tmp_path, env))
    (tmp_path / "rapports" / "auto").mkdir(parents=True)
    (tmp_path / "rapports" / "auto" / "incident-git.json").write_text("{}\n")
    codes = [(r.returncode, r.stderr) for r in _pre(unite, tmp_path, env)]
    assert any(c == 126 and "INCIDENT_GIT" in e for c, e in codes)


def _faux_git(tmp_path: Path, env: dict) -> Path:
    """git du PATH de l'unité (%h/.local/bin en tête) qui laisse une trace avant d'appeler le vrai : un hook ou un réglage
    posé s'exécuterait à ce moment-là."""
    trace = tmp_path / "git-lance"
    bin_ = tmp_path / "home" / ".local" / "bin"
    bin_.mkdir(parents=True, exist_ok=True)
    (bin_ / "git").write_text(f"#!/bin/sh\necho \"$@\" >> '{trace}'\nexec /usr/bin/git \"$@\"\n")
    (bin_ / "git").chmod(0o755)
    env.setdefault("PATH", f"{bin_}:/usr/bin:/bin")  # unité sans Environment=PATH : celui de systemd --user, sans ~/.local/bin
    if not env["PATH"].startswith(str(bin_)):
        env["PATH"] = f"{bin_}:{env['PATH']}"
    return trace


def _sequence(unite: str, tmp_path: Path, env: dict) -> list:
    """ExecStartPre dans l'ordre, comme systemd : le premier code non nul arrête l'unité."""
    faits = []
    for l in unite.splitlines():
        if l.startswith("ExecStartPre="):
            faits.append(subprocess.run(shlex.split(l.partition("=")[2]), cwd=tmp_path, env=env, capture_output=True, text=True))
            if faits[-1].returncode:
                break
    return faits


UNITES = ["deploy/systemd/delta-ia-commun.service", "deploy/systemd/delta-ia-selection.service"]
MODELES = ["deploy/systemd/delta-etat-fournisseurs.service.exemple", "deploy/systemd/delta-reglages-pont.service.exemple",
           "deploy/relais/delta-ia-relais.service.exemple"]  # SUITE 3, B2b : modèles du dépôt, unités installées non touchées


@pytest.mark.parametrize("chemin", UNITES + MODELES)
def test_temoin_d_incident_avant_tout_git(tmp_path, chemin):
    """SUITE 3, B1 : le témoin est le premier ExecStartPre ; tant qu'il existe, git n'est pas lancé (un hook ou un réglage
    git posé, cause du témoin, s'exécuterait au premier git)."""
    _depot_scripts(tmp_path, "commun")
    unite = (RACINE / chemin).read_text()
    env = _env_unite(unite, tmp_path)
    trace = _faux_git(tmp_path, env)
    _reference(tmp_path, env)
    (tmp_path / "rapports" / "auto").mkdir(parents=True)
    (tmp_path / "rapports" / "auto" / "incident-git.json").write_text("{}\n")
    faits = _sequence(unite, tmp_path, env)
    assert len(faits) == 1 and faits[0].returncode == 126 and "INCIDENT_GIT" in faits[0].stderr, "le témoin est le premier contrôle"
    assert not trace.exists(), "aucun git avant le témoin"
    (tmp_path / "rapports" / "auto" / "incident-git.json").unlink()
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env)), "témoin levé : l'unité part"
    # SUITE 4, point 1 : les modèles ne lancent plus aucun git ; seules les deux unités gardent git status (après l'empreinte)
    assert trace.exists() == (chemin in UNITES), "modèles : aucun git dans les gardes"


def _faux_fsmonitor(tmp_path: Path) -> Path:
    """core.fsmonitor du dépôt de test : un script qui laisse une trace. git l'exécute à la lecture de l'index (status,
    ls-files), hors de tout bac à sable ; une étape qui écrit .git/config peut le poser."""
    trace = tmp_path / "fsmonitor-lance"
    script = tmp_path / "fsmonitor.sh"
    script.write_text(f"#!/bin/sh\necho \"$@\" >> '{trace}'\nexit 0\n")
    script.chmod(0o755)
    env_git = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "config", "core.fsmonitor", str(script)], cwd=tmp_path, env=env_git, check=True, capture_output=True)
    subprocess.run(["git", "status", "--porcelain=v1"], cwd=tmp_path, env=env_git, capture_output=True)
    assert trace.exists(), "témoin : le faux fsmonitor est exécuté par un git ordinaire"
    trace.unlink()
    return trace


@pytest.mark.parametrize("chemin", MODELES)
def test_modele_ne_lance_jamais_le_fsmonitor(tmp_path, chemin):
    """SUITE 4, point 1 : un core.fsmonitor posé n'est jamais exécuté par la garde d'un modèle, ni quand elle refuse
    (binaire sous scripts/) ni quand elle laisse partir l'unité."""
    scripts = _depot_scripts(tmp_path, "commun")
    trace = _faux_fsmonitor(tmp_path)
    unite = (RACINE / chemin).read_text()
    env = _env_unite(unite, tmp_path)
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env))
    _pyc_sans_source(scripts / "zoneinfo.pyc")
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and "scripts/zoneinfo.pyc" in faits[-1].stderr
    assert not trace.exists(), "aucun git, donc aucun fsmonitor"


def _journal(tmp_path: Path) -> list:
    f = tmp_path / "rapports" / "passages.log"
    return [l.split(" | ") for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


@pytest.mark.parametrize("nom", ["commun", "selection"])
def test_unite_compare_l_empreinte_git_avant_son_git_status(tmp_path, nom):
    """SUITE 4, point 2 : un core.fsmonitor posé SANS témoin (étape qui a écrit .git/config) n'est jamais exécuté. Avant
    son git status, l'unité compare sans git .git/config, info/attributes, info/exclude et hooks/ à la référence que
    l'orchestrateur écrit hors de l'arbre ; absente ou différente : 126 et une ligne au journal. Le git status lui-même
    porte -c core.fsmonitor=false."""
    _depot_scripts(tmp_path, nom)
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    env = _env_unite(unite, tmp_path)
    ancienne = orc.empreinte_git_demarrage(tmp_path)
    trace = _faux_fsmonitor(tmp_path)  # posé sans témoin ; témoin : un git ordinaire l'exécute

    # 1. référence absente (première installation, ou effacée) : 126, sans git
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and "EMPREINTE_GIT" in faits[-1].stderr and "référence absente" in faits[-1].stderr
    assert not trace.exists()
    (ligne,) = _journal(tmp_path)
    assert ligne[1:6] == ["orchestrateur", f"{nom}-git", "0 éléments (0 fort)", "aucun", "126"] and "EMPREINTE_GIT" in ligne[6]

    # 2. référence d'avant le fsmonitor : .git/config différent, 126, sans git
    f = orc.fichier_reference_git(env)
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(ancienne), encoding="utf-8")
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and "différent de la référence : config" in faits[-1].stderr
    assert not trace.exists() and len(_journal(tmp_path)) == 2

    # 3. référence qui contient le fsmonitor (écrite après lui) : le git status part, sous -c core.fsmonitor=false
    _reference(tmp_path, env)
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env))
    assert not trace.exists(), "git status sous -c core.fsmonitor=false : le fsmonitor n'est pas exécuté"
    assert len(_journal(tmp_path)) == 2

    # 4. hook ajouté après la référence : 126, sans git
    (tmp_path / ".git" / "hooks" / "post-index-change").write_text("#!/bin/sh\n")
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and "différent de la référence : hooks" in faits[-1].stderr
    (tmp_path / ".git" / "hooks" / "post-index-change").unlink()

    # 5. chemin par défaut, sans XDG_STATE_HOME : ~/.local/state du HOME de l'unité, le même pour l'orchestrateur
    sans_xdg = {k: v for k, v in env.items() if k != "XDG_STATE_HOME"}
    assert orc.fichier_reference_git(sans_xdg) == tmp_path / "home" / ".local" / "state" / "delta-ia" / "empreinte-git.json"
    assert _sequence(unite, tmp_path, sans_xdg)[-1].returncode == 126
    _reference(tmp_path, sans_xdg)
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, sans_xdg))

    # 6. .git qui n'est pas un dossier (worktree lié) : 126
    (tmp_path / ".git").rename(tmp_path / "vrai.git")
    (tmp_path / ".git").write_text("gitdir: vrai.git\n")
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and ".git n est pas un dossier" in faits[-1].stderr
    assert not trace.exists()


def _pyc_sans_source(chemin: Path) -> None:
    """Module compilé sans source, par l'interpréteur des tests : importé depuis scripts/ avant la bibliothèque standard."""
    import py_compile
    source = chemin.parent.parent / f"{chemin.stem}-source.py"
    source.write_text("from pathlib import Path\nPath('IMPORTE').write_text('pyc sans source')\n")
    py_compile.compile(str(source), cfile=str(chemin), doraise=True)
    source.unlink()


@pytest.mark.parametrize("nom", ["commun", "selection"])
def test_pyc_sans_source_ignore_par_git_arrete_avant_tout_import(tmp_path, nom):
    """SUITE 3, B2a : scripts/zoneinfo.pyc sans source, ignoré par git (*.pyc), n'apparaît pas à git status mais serait
    importé à la place de la bibliothèque standard. Le contrôle d'arbre refuse tout fichier ignoré sous scripts/, hors
    __pycache__/."""
    scripts = _depot_scripts(tmp_path, nom)
    (scripts / f"{nom}_auto.py").write_text("import zoneinfo\n")
    env_git = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qam", "zoneinfo"],
                   cwd=tmp_path, env=env_git, check=True, capture_output=True)
    _pyc_sans_source(scripts / "zoneinfo.pyc")
    statut = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=tmp_path, env=env_git,
                            capture_output=True, text=True, check=True)
    assert statut.stdout == "", "invisible à git status"
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    env = _env_unite(unite, tmp_path)
    _reference(tmp_path, env)
    subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path, env=env, check=True)
    assert (tmp_path / "IMPORTE").exists(), "témoin : sans contrôle, le .pyc sans source est importé (même sous le préfixe)"
    (tmp_path / "IMPORTE").unlink()
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and "ARBRE_CODE_SALE" in faits[-1].stderr and "scripts/zoneinfo.pyc" in faits[-1].stderr
    assert not (tmp_path / "IMPORTE").exists()
    # __pycache__/ reste toléré : PYTHONPYCACHEPREFIX l'écarte (test_pyc_piege_dans_l_arbre_n_est_pas_charge)
    (scripts / "zoneinfo.pyc").unlink()
    (scripts / "__pycache__").mkdir()
    (scripts / "__pycache__" / "piege.cpython-0.pyc").write_bytes(b"")
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env))


@pytest.mark.parametrize("chemin", MODELES)
def test_modele_refuse_un_fichier_ignore_sous_scripts(tmp_path, chemin):
    """SUITE 3, B2b : les autres lanceurs du dépôt ont la même garde que les deux unités : un .pyc sans source ignoré
    sous scripts/ arrête l'unité avant ExecStart ; __pycache__/ est écarté par PYTHONPYCACHEPREFIX."""
    scripts = _depot_scripts(tmp_path, "commun")
    unite = (RACINE / chemin).read_text()
    env = _env_unite(unite, tmp_path)
    assert env["PYTHONPYCACHEPREFIX"] == str(tmp_path / "run" / "delta-ia-pycache")
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env)), "arbre sans fichier ignoré : l'unité part"
    _pyc_sans_source(scripts / "zoneinfo.pyc")
    faits = _sequence(unite, tmp_path, env)
    assert faits[-1].returncode == 126 and "ARBRE_CODE_SALE" in faits[-1].stderr and "scripts/zoneinfo.pyc" in faits[-1].stderr
    # SUITE 4, point 1 : les autres binaires importables, même dans un sous-dossier ; __pycache__/ toléré
    (scripts / "zoneinfo.pyc").unlink()
    (scripts / "sous").mkdir()
    for nom in ("x.pyo", "_json.cpython-312-x86_64-linux-gnu.so", "y.pyd"):
        (scripts / "sous" / nom).write_bytes(b"")
        faits = _sequence(unite, tmp_path, env)
        assert faits[-1].returncode == 126 and f"scripts/sous/{nom}" in faits[-1].stderr, nom
        (scripts / "sous" / nom).unlink()
    (scripts / "sous" / "__pycache__").mkdir()
    (scripts / "sous" / "__pycache__" / "z.cpython-0.pyc").write_bytes(b"")
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env))


def _code_python(ligne: str) -> str:
    """Code passé à `python3 -I -S -c` dans une ligne ExecStartPre= ou dans passage-auto.sh."""
    args = shlex.split(ligne.partition("=")[2] if ligne.startswith("ExecStartPre=") else ligne.removeprefix("if ! ").removesuffix("; then"))
    assert args[:4] == ["/usr/bin/python3", "-I", "-S", "-c"], ligne[:80]
    return args[4]


def test_tout_lanceur_du_depot_porte_la_garde():
    """Tout modèle d'unité du dépôt qui lance du code de scripts/ porte témoin d'abord, PYTHONPYCACHEPREFIX et le parcours
    de scripts/ ; delta-passage passe par passage-auto.sh, qui porte la même garde avant l'exec. SUITE 4, point 1 : le
    parcours est le même code partout, et aucune garde ne lance git, hors le git status des deux unités (dernier contrôle)."""
    import re
    lance_git = lambda code: re.search(r"['\"]git['\"]", code)  # les gardes appellent git par subprocess.run(['git', …])
    vus, parcours = [], set()
    for f in sorted((RACINE / "deploy").rglob("*.service*")):
        unite = f.read_text()
        start = next(l for l in unite.splitlines() if l.startswith("ExecStart="))
        if start.endswith("/scripts/passage-auto.sh"):
            sh = (RACINE / "scripts" / "passage-auto.sh").read_text()
            avant = sh[:sh.index('exec "$PYTHON"')]
            code = [l for l in avant.splitlines() if l.strip() and not l.lstrip().startswith("#")]
            assert not [l for l in code if re.search(r"(^|[\s;(|&$])git(\s|$)", l)], "aucun git dans passage-auto.sh avant l'exec"
            ligne = next(l for l in code if "os.walk" in l)
            parcours.add(_code_python(ligne))
            assert sh.index('if [ -e "$RACINE/rapports/auto/incident-git.json" ]') < sh.index(ligne) < sh.index('exec "$PYTHON"')
            assert "export PYTHONPYCACHEPREFIX=" in sh
            continue
        pre = [l for l in unite.splitlines() if l.startswith("ExecStartPre=")]
        assert pre and "incident-git.json" in pre[0] and not lance_git(_code_python(pre[0])), f.name
        assert "os.walk('scripts'" in pre[1], f"{f.name} : parcours juste après le témoin"
        parcours.add(_code_python(pre[1]))
        avec_git = [l for l in pre if lance_git(_code_python(l))]
        if str(f.relative_to(RACINE)) in UNITES:
            assert avec_git == [pre[-1]] and "'status', '--porcelain=v1'" in pre[-1], f.name
            # SUITE 4, point 2 : juste avant, l'empreinte sans git ; le git status neutralise fsmonitor et hooks
            assert "empreinte-git.json" in pre[-2] and not lance_git(_code_python(pre[-2])), f.name
            assert "['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', 'status'" in pre[-1], f.name
        else:
            assert avec_git == [], f"{f.name} : aucun git dans un modèle"
        assert "Environment=PYTHONPYCACHEPREFIX=%t/delta-ia-pycache" in unite, f.name
        vus.append(str(f.relative_to(RACINE)))
    assert sorted(vus) == sorted(UNITES + MODELES)
    assert len(parcours) == 1, "un seul code de parcours"
    assert "ls-files" not in next(iter(parcours))


def test_aucune_unite_ne_redemarre_sur_une_garde():
    """SUITE 4, point 4 : toute unité ou tout modèle du dépôt qui redémarre (Restart=) ne boucle pas sur le 126 d'une
    garde. RestartPreventExitStatus=126 couvre le processus principal ; les gardes sont des ExecStartPre, sur lesquels
    il est sans effet (systemd.service(5)) : la limite de démarrages de [Unit] doit être atteinte par la boucle elle-même
    (StartLimitBurst redémarrages espacés de RestartSec tiennent dans StartLimitIntervalSec)."""
    redemarrent = []
    for f in sorted((RACINE / "deploy").rglob("*.service*")):
        texte = f.read_text()
        unit, _, service = texte.partition("[Service]")
        valeurs = lambda bloc, cle: [l.strip().partition("=")[2] for l in bloc.splitlines() if l.strip().startswith(cle + "=")]
        restart = valeurs(service, "Restart")
        if not restart or restart[-1] == "no":
            continue
        redemarrent.append(str(f.relative_to(RACINE)))
        assert "126" in (valeurs(service, "RestartPreventExitStatus") or [""])[-1].split(), f.name
        intervalle, rafale = valeurs(unit, "StartLimitIntervalSec"), valeurs(unit, "StartLimitBurst")
        assert intervalle and rafale, f"{f.name} : limite de démarrages absente de [Unit]"
        pause = float((valeurs(service, "RestartSec") or ["0.1"])[-1])  # 100 ms par défaut
        assert int(rafale[-1]) * pause < float(intervalle[-1]) and float(intervalle[-1]) > 0, f.name
    assert "deploy/relais/delta-ia-relais.service.exemple" in redemarrent
