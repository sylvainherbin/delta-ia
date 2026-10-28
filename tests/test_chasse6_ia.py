"""Mission 02q : diagnostics TAP réels et traversée après les correctifs 3b/3c.

La cible TAP est la fonction verdict de preuve-p15c.sh, extraite à l'identique.
Node produit tous les journaux ; aucun TAP synthétique, modèle ou réseau.
Les contrôles de supervision utilisent uniquement des fichiers et droits réels.
"""

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from datetime import date

import pytest

import orchestrateur as orc


RACINE = Path(__file__).resolve().parents[1]
RECETTE = RACINE / "mcp/preuve-p15c.sh"


class DiagnosticDuTemoinSuivant(AssertionError):
    """02q-F1 : le diagnostic capturé suivant est attribué au rouge précédent."""


@pytest.fixture
def tap(tmp_path):
    source = RECETTE.read_text(encoding="utf-8")
    fonction = re.search(r"^verdict\(\) \{\n[\s\S]*?^JS\n\}", source, re.MULTILINE)
    assert fonction, "fonction verdict réelle requise"
    noms = [re.search(rf"^{cle}='([^']+)'$", source, re.MULTILINE).group(1)
            for cle in ("r176", "r178")]
    node = shutil.which("node")
    assert node, "Node requis pour produire le TAP natif"
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = {"PATH": os.defpath, "HOME": str(home), "TMPDIR": str(tmp_path),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    # Le préchargement éventuel du lanceur ne donne aucun accès à l'environnement
    # personnel ; il interdit les transports réseau dans les enfants Node.
    if os.environ.get("NODE_OPTIONS"):
        env["NODE_OPTIONS"] = os.environ["NODE_OPTIONS"]
    return tmp_path, fonction.group(0), noms, node, env


def produire_tap(tap, famille, position, *, rouge=True):
    dossier, _, noms, node, env = tap
    capturer = {
        "import": '''let erreur;
try { await import("./dependance-absente.mjs"); } catch (e) { erreur = e; }
assert.equal(erreur?.code, "ERR_MODULE_NOT_FOUND");
console.error(erreur);''',
        "exports": '''let erreur;
try { await import("fixture-02q/interdit.mjs"); } catch (e) { erreur = e; }
assert.equal(erreur?.code, "ERR_PACKAGE_PATH_NOT_EXPORTED");
console.error(erreur);''',
    }[famille]
    if famille == "exports":
        paquet = dossier / "node_modules/fixture-02q"
        paquet.mkdir(parents=True)
        (paquet / "package.json").write_text('{"name":"fixture-02q","exports":{}}\n', encoding="utf-8")
        (paquet / "interdit.mjs").write_text("export default 42;\n", encoding="utf-8")
    fichiers = []
    for i, nom in enumerate(noms):
        fichier = dossier / f"{i}.test.mjs"
        fichier.write_text(
            'import { test } from "node:test";\n'
            'import assert from "node:assert/strict";\n'
            f'test({json.dumps(nom)}, async () => {{\n'
            + (capturer + "\n" if i == position else "")
            + ('assert.fail("assertion métier attendue");\n' if rouge else 'assert.equal(2 + 2, 4);\n')
            + '});\n', encoding="utf-8")
        fichiers.append(str(fichier))
    r = subprocess.run([node, "--test", "--test-reporter=tap", "--test-concurrency=1", *fichiers],
                       cwd=dossier, env=env, text=True, capture_output=True, timeout=60)
    (dossier / "natif.tap").write_text(r.stdout + r.stderr, encoding="utf-8")
    assert r.returncode == int(rouge), r.stdout + r.stderr
    for compteur in ("tests 2", f"pass {0 if rouge else 2}", f"fail {2 if rouge else 0}",
                     "cancelled 0", "skipped 0", "todo 0"):
        assert re.search(rf"^# {compteur}$", r.stdout, re.MULTILINE), r.stdout
    resultats = list(re.finditer(r"^(ok|not ok) \d+ - (.+)$", r.stdout, re.MULTILINE))
    assert [(r[1], r[2]) for r in resultats] == [("not ok" if rouge else "ok", n) for n in noms]
    erreur = "ERR_MODULE_NOT_FOUND" if famille == "import" else "ERR_PACKAGE_PATH_NOT_EXPORTED"
    diagnostic = re.search(rf"^# Error \[{erreur}\]:", r.stdout, re.MULTILINE)
    assert diagnostic, r.stdout
    # Chaque fichier est exécuté séquentiellement. Le commentaire du second
    # appartient à ce second test, mais précède sa ligne de résultat TAP.
    assert diagnostic.start() < resultats[position].start(), r.stdout
    if position:
        assert resultats[0].start() < diagnostic.start(), r.stdout
    if rouge:
        assert len(re.findall(r"^  failureType: 'testCodeFailure'$", r.stdout, re.MULTILINE)) == 2
        assert len(re.findall(r"^  code: 'ERR_ASSERTION'$", r.stdout, re.MULTILINE)) == 2
        assert "hookFailed" not in r.stdout
    return r


def valider(tap, execution, echecs):
    dossier, fonction, noms, node, env = tap
    journal = dossier / "natif.tap"
    assert journal.read_text(encoding="utf-8") == execution.stdout + execution.stderr
    r = subprocess.run(["bash", "-c", 'noeud="$1"\n' + fonction
                        + '\nverdict "$2" 2 "$3" "${@:4}"',
                        "chasse6", node, str(journal), str(echecs), *noms],
                       cwd=dossier, env=env, text=True, capture_output=True, timeout=60)
    (dossier / "verdict.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    return r


@pytest.mark.parametrize("famille", ["import", "exports"])
def test_chasse6_commentaire_capture_avant_le_premier_rouge_accepte(tap, famille):
    """Contrôle : mêmes deux assertions et diagnostic, placé avant le premier résultat."""
    r = produire_tap(tap, famille, 0)
    validation = valider(tap, r, 2)
    assert validation.returncode == 0, validation.stderr


# Contrat : mcp/test/preuve-p15c.test.js accepte « deux assertions rouges
# nommées » et un compte rendu d'import capturé ; tests/test_chasse3c_ia.py
# établit que console.error d'une erreur traitée n'est pas un échec d'import.
# fcd6050 borne le diagnostic par les résultats suivants, sans retirer leurs
# commentaires PRÉCÉDANT le résultat. Deux vraies assertions deviennent refusées.
@pytest.mark.parametrize("famille", ["import", "exports"])
def test_chasse6_commentaire_capture_du_second_rouge_accepte(tap, famille):
    r = produire_tap(tap, famille, 1)
    validation = valider(tap, r, 2)
    if validation.returncode != 0:
        raise DiagnosticDuTemoinSuivant(
            "02q-F1 : deux ERR_ASSERTION réelles ; le commentaire de l'erreur "
            "capturée par le second témoin fait rejeter le premier :\n" + validation.stderr)


@pytest.mark.parametrize("famille", ["import", "exports"])
def test_chasse6_commentaire_capture_du_second_vert_accepte(tap, famille):
    r = produire_tap(tap, famille, 1, rouge=False)
    validation = valider(tap, r, 0)
    assert validation.returncode == 0, validation.stderr


@pytest.mark.parametrize("obstacle", ["aucun", "lien", "sans-traversee"])
def test_chasse6_traversee_mixte_et_refus_des_obstacles(tmp_path, obstacle):
    """O_PATH conserve le refus des liens et exige les vrais droits de traversée."""
    ancetre = tmp_path / "ancetre"
    racine = ancetre / "depot"
    rapports = racine / "rapports"
    rapports.mkdir(parents=True)
    rapports.chmod(0o700)
    chemin = racine
    if obstacle == "lien":
        alias = tmp_path / "alias"
        alias.symlink_to(ancetre, target_is_directory=True)
        chemin = alias / "depot"
    mode = 0o600 if obstacle == "sans-traversee" else 0o111
    try:
        racine.chmod(0o100)
        ancetre.chmod(mode)
        if os.geteuid() == 0 or os.access(ancetre, os.R_OK) != bool(mode & 0o400):
            pytest.skip("cet utilisateur contourne les droits POSIX à vérifier")
        assert stat.S_IMODE(ancetre.stat().st_mode) == mode
        assert os.access(ancetre, os.X_OK) == (obstacle != "sans-traversee")
        texte = "# Supervision\n\n" + "Résultat valide des contrôles locaux. " * 8
        sortie = json.dumps({"is_error": False, "result": texte})
        debut = time.time() - 1
        if obstacle != "sans-traversee":
            controle = chemin / "rapports" / "controle.md"
            controle.write_text(texte, encoding="utf-8")
            assert controle.read_text(encoding="utf-8") == texte
            controle.unlink()
        else:
            with pytest.raises(PermissionError):
                (chemin / "rapports" / "controle.md").write_text(texte, encoding="utf-8")
        attendu = obstacle == "aucun"
        assert orc.enregistrer_rapport_supervision(chemin, date(2026, 10, 28), debut, sortie) is attendu
        assert orc.rapport_supervision_ecrit(chemin, date(2026, 10, 28), debut) is attendu
        if obstacle == "lien":
            assert list(rapports.iterdir()) == [], "le lien refusé ne doit produire aucun rapport"
    finally:
        ancetre.chmod(0o700)
        racine.chmod(0o700)
