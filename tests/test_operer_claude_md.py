"""Missions OPÉRER : exécution comme une mission de Delta (décision de Sylvain, 03/10/2026)."""

from conftest import RACINE


def test_missions_operer_dans_claude_md():
    claude = (RACINE / "CLAUDE.md").read_text(encoding="utf-8")
    assert "[OPÉRER]" in claude
    assert "comme une mission de Delta" in claude
    assert "operer ack <id>" in claude
    assert "accord direct de Sylvain" not in claude  # phrase retirée le 06/10/2026 (D83)
