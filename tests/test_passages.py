"""D63 amendée le 29/09/2026 : scripts/passages.py ajoute une ligne à rapports/passages.log, sans jamais réécrire."""

import json
from datetime import datetime

import pytest

import passages


def test_format_ligne():
    t = passages.ligne("delta-ia", "claude", 3, 1, "abc1234", 0, quand=datetime(2026, 9, 29, 7, 5))
    assert t == "2026-09-29_0705 | delta-ia | claude | 3 éléments (1 fort) | abc1234 | 0"


def test_ajout_sans_reecriture(tmp_path, capsys):
    f = tmp_path / "rapports" / "passages.log"
    f.parent.mkdir()
    f.write_text("ligne ancienne\n", encoding="utf-8")
    assert passages.main(["--racine", str(tmp_path), "--agent", "delta-ia", "--perimetre", "claude",
                          "--elements", "2", "--forts", "0", "--commit", "aucun", "--garde", "12"]) == 0
    assert passages.main(["--racine", str(tmp_path), "--agent", "codex", "--perimetre", "openai",
                          "--elements", "1", "--forts", "1", "--commit", "0123abcd"]) == 0
    lignes = f.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "ligne ancienne" and len(lignes) == 3
    assert lignes[1].endswith(" | delta-ia | claude | 2 éléments (0 fort) | aucun | 12")
    assert lignes[2].endswith(" | codex | openai | 1 éléments (1 fort) | 0123abcd | 0")
    assert capsys.readouterr().out.splitlines()[-1] == lignes[2]


@pytest.mark.parametrize("args", [
    ["--agent", "a|b", "--perimetre", "claude", "--elements", "1", "--forts", "0", "--commit", "aucun"],
    ["--agent", "delta-ia", "--perimetre", "claude", "--elements", "1", "--forts", "2", "--commit", "aucun"],
    ["--agent", "delta-ia", "--perimetre", "claude", "--elements", "1", "--forts", "0", "--commit", "HEAD"],
])
def test_argument_invalide_rien_ecrit(tmp_path, args):
    assert passages.main(["--racine", str(tmp_path), *args]) == 2
    assert not (tmp_path / "rapports" / "passages.log").exists()


def test_d63_mode_auto_autorise_le_journal():
    from conftest import RACINE
    s = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert "Bash(.venv/bin/python scripts/passages.py *)" in s["allow"]
    skill = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    sec = skill[skill.index("## Mode automatique (D68)"):skill.index("## 0. Préparation")]
    assert "scripts/passages.py" in sec
    for f in ("CLAUDE.md", "AGENTS.md", ".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md",
              ".agents/skills/delta/SKILL.md", ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md",
              "prompts/codex-delta-kb.md"):
        texte = (RACINE / f).read_text(encoding="utf-8")
        assert "D63, amendée le 29/09/2026" in texte and "passages.log" in texte, f
