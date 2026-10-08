"""Skill de projet `verify` : contrôle avant commit de code, sans effet sur les passages ni sur les commits de données."""

from conftest import RACINE

SKILL = RACINE / ".claude" / "skills" / "verify" / "SKILL.md"


def test_skill_verify_existe_avec_son_frontmatter():
    assert SKILL.is_file()
    texte = SKILL.read_text(encoding="utf-8")
    assert texte.startswith("---\n")
    entete = texte.split("---\n", 2)[1]
    assert "name: verify" in entete.splitlines()
    assert "description:" in entete
    # Claude doit pouvoir la lancer lui-même avant un commit.
    assert "disable-model-invocation" not in entete


def test_skill_verify_exempte_passages_et_donnees():
    texte = SKILL.read_text(encoding="utf-8")
    for motif in ("/delta", "/delta-kb", "$delta", "$delta-kb", "docs/data/", "state/", "rapports/"):
        assert motif in texte
    assert "Hors champ" in texte


def test_skill_verify_lance_pytest_et_valider():
    texte = SKILL.read_text(encoding="utf-8")
    # la suite complète (pytest -q puis valider.py ×3) reste le repli, via verifier.py
    assert "pytest -q" in texte and "valider.py" in texte
    for perimetre in ("claude", "openai", "actu"):
        assert perimetre in texte
    assert ".venv/bin/python scripts/verifier.py" in texte


def test_skill_verify_applique_ci_preuve():
    """D94 : ciblé local, push de branche, CI verte sur le hash exact, contrôle machine, fusion --ff-only, repli."""
    texte = SKILL.read_text(encoding="utf-8")
    ordre = ["verifier.py --cible", "git push origin operer/", "verifier.py --ci operer/", "verifier.py --local", "git merge --ff-only"]
    positions = [texte.index(motif) for motif in ordre]
    assert positions == sorted(positions)
    assert "headSha" in texte and "hash exact" in texte
    assert "jamais `--force`" in texte
    assert "Repli" in texte and "suite complète locale" in texte
    assert "ne lance jamais la suite complète" in texte


def test_skill_verify_fusionne_sans_pull_rebase_avant_le_push():
    texte = SKILL.read_text(encoding="utf-8")
    assert "git fetch origin && git merge --ff-only operer/<nom> && git push origin main" in texte
    # un `pull --rebase` entre la fusion et le push changerait le hash testé par la CI : seulement cité pour l'interdire
    assert "Pas de `git pull --rebase` entre la fusion et le push" in texte
    assert "git pull --rebase && git push" not in texte
    assert "git rebase --abort" in texte
