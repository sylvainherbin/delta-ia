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
    assert ".venv/bin/pytest -q" in texte
    for perimetre in ("claude", "openai", "actu"):
        assert f"scripts/valider.py --perimetre {perimetre}" in texte
