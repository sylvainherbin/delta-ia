"""D94 : carte fichiers → tests (scripts/carte.py), sur un mini-dépôt fictif puis sur le dépôt réel."""

from __future__ import annotations

import pytest

import carte
from conftest import RACINE


@pytest.fixture
def mini(tmp_path):
    def ecrire(rel, texte=""):
        chemin = tmp_path / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(texte, encoding="utf-8")
    ecrire("scripts/deltalib/__init__.py")
    ecrire("scripts/deltalib/modeles.py", "X = 1\n")
    ecrire("scripts/deltalib/kb/__init__.py")
    ecrire("scripts/deltalib/kb/markdown.py", "from deltalib.modeles import X\n")
    ecrire("scripts/fetch.py", "from deltalib.modeles import X\n")
    ecrire("scripts/passage.py", "import fetch\nfrom deltalib import modeles\n")
    ecrire("scripts/outil.py", "def f(): ...\n")
    ecrire("tests/conftest.py")
    ecrire("tests/test_fetch.py", "import fetch\n")
    ecrire("tests/test_passage.py", "import passage\n")
    ecrire("tests/test_kb.py", "from deltalib.kb import markdown\n")
    ecrire("tests/test_site.py", "CHEMIN = 'docs/assets/app.js'\n")
    ecrire("tests/test_verifier.py")
    ecrire("tests/test_carte.py")
    ecrire("tests/test_skill_verify.py")
    return carte.generer(tmp_path)


def test_graphe_des_imports_inclut_les_paquets_et_les_sous_modules(mini):
    assert "scripts/deltalib/modeles.py" in mini["imports"]["scripts/passage.py"]  # from deltalib import modeles
    assert "scripts/deltalib/__init__.py" in mini["imports"]["scripts/deltalib/kb/markdown.py"]
    assert mini["imports"]["tests/test_kb.py"].count("scripts/deltalib/kb/markdown.py") == 1


def test_module_ordinaire_tests_directs_et_dependants_directs(mini):
    sel = carte.selectionner(mini, ["scripts/fetch.py"])
    assert sel["tests"] == ["tests/test_fetch.py", "tests/test_passage.py"]  # passage importe fetch
    assert sel["valider"] is False


def test_module_central_sans_ses_dependants_avec_valider(mini):
    sel = carte.selectionner(mini, ["scripts/deltalib/modeles.py"])
    assert sel["valider"] is True
    assert sel["tests"] == []  # aucun test n'importe modeles directement : pas d'élargissement aux dépendants
    sel = carte.selectionner(mini, ["scripts/deltalib/kb/markdown.py"])
    assert sel["tests"] == ["tests/test_kb.py"]


def test_test_modifie_se_designe_lui_meme(mini):
    assert carte.selectionner(mini, ["tests/test_passage.py"])["tests"] == ["tests/test_passage.py"]


def test_fichier_hors_graphe_cite_par_un_test(mini):
    sel = carte.selectionner(mini, ["docs/assets/app.js"])
    assert sel["tests"] == ["tests/test_site.py"] and sel["valider"] is False


def test_fichier_inconnu_tests_de_meme_nom_ou_outillage_et_valider(mini):
    sel = carte.selectionner(mini, ["prompts/inconnu.md"])
    assert sel["valider"] is True
    assert sel["tests"] == sorted(carte.OUTILLAGE)  # aucun test de même nom : outillage, jamais la suite complète
    sel = carte.selectionner(mini, ["docs/passage.md"])
    assert sel["tests"] == ["tests/test_passage.py"]  # le nom désigne test_passage


def test_nom_generique_ne_designe_pas_les_tests_qui_le_citent(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("T = 'SKILL.md'\n")
    mini = carte.generer(tmp_path)
    assert carte.selectionner(mini, [".claude/skills/x/SKILL.md"])["tests"] == []


def test_socle_des_tests_outillage_seul(mini):
    sel = carte.selectionner(mini, ["tests/conftest.py", "requirements.txt"])
    assert sel["tests"] == sorted(carte.OUTILLAGE) and sel["valider"] is False


def test_donnees_valider_seul(mini):
    sel = carte.selectionner(mini, ["docs/data/claude/2026-10-08.json", "state/claude.json"])
    assert sel == {"tests": [], "valider": True, "raisons": sel["raisons"]}


def test_ne_selectionne_jamais_un_fichier_absent(mini):
    # OUTILLAGE cite test_verifier, test_carte, test_skill_verify : tous présents ici ; en retirer un ne le sélectionne pas
    mini["textes"].pop("tests/test_carte.py")
    assert "tests/test_carte.py" not in carte.selectionner(mini, ["tests/conftest.py"])["tests"]


# --- dépôt réel : la carte tient sur les fichiers qui comptent ---------------------------------------------------------

@pytest.fixture(scope="module")
def reel():
    return carte.generer(RACINE)


def test_reel_bibliotheque_centrale_reste_ciblee(reel):
    tous = set(reel["textes"])
    for fichier in ("scripts/deltalib/modeles.py", "scripts/deltalib/etat.py", "scripts/deltalib/kb/markdown.py"):
        sel = carte.selectionner(reel, [fichier])
        assert sel["valider"] is True and sel["tests"] and set(sel["tests"]) < tous, fichier


def test_reel_module_de_scripts_trouve_ses_tests(reel):
    assert "tests/test_valider.py" in carte.selectionner(reel, ["scripts/valider.py"])["tests"]
    assert "tests/test_verifier.py" in carte.selectionner(reel, ["scripts/verifier.py"])["tests"]
    assert "tests/test_carte.py" in carte.selectionner(reel, ["scripts/carte.py"])["tests"]


def test_reel_skill_verify_et_site(reel):
    assert "tests/test_skill_verify.py" in carte.selectionner(reel, ["/".join((".claude", "skills", "verify", "SKILL.md"))])["tests"]
    assert "tests/test_site.py" in carte.selectionner(reel, ["/".join(("docs", "assets", "app.js"))])["tests"]


def test_reel_aucune_selection_n_est_la_suite_complete(reel):
    tous = set(reel["textes"])
    for fichier in ("tests/conftest.py", "SPEC.md", "pytest.ini", ".github/workflows/tests.yml", "sources.yaml", "scripts/deltalib/modeles.py"):
        assert set(carte.selectionner(reel, [fichier])["tests"]) < tous, fichier
