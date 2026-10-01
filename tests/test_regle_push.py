"""Règle de push en session de développement : l'OK du chef Delta-IA vaut push (autorisation permanente de Sylvain, 02/10/2026)."""

from conftest import RACINE

PHRASE = "push après l'OK du chef Delta-IA (autorisation permanente de Sylvain du 02/10/2026)"


def test_phrase_dans_claude_md_et_spec():
    claude = (RACINE / "CLAUDE.md").read_text(encoding="utf-8")
    spec = (RACINE / "SPEC.md").read_text(encoding="utf-8")
    assert PHRASE in claude and spec.count(PHRASE) == 2, "SPEC §6 et D9"
    assert "push seulement sur accord" not in claude + spec


def test_le_reste_de_la_regle_est_garde():
    claude = (RACINE / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`git add <chemins>` explicites, jamais `git add -A`, jamais `--force`" in claude
    assert "un seul push, après les tests et `valider.py`" in claude
    spec = (RACINE / "SPEC.md").read_text(encoding="utf-8")
    assert "un seul push, jamais `--force`, après les tests et `valider.py`" in spec
    assert "Sans dépôt distant : ni pull ni push" in claude
