"""D65 : état volatil des outils -> docs/data/etat.json, et son contrôle."""

import json
from pathlib import Path

import etat
import valider


def maison_factice(tmp_path):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"model": "opus", "env": {"SECRET": "x"}}))
    (tmp_path / ".codex" / "config.toml").write_text(
        'model = "gpt-6-sol"\nmodel_reasoning_effort = "medium"\n\n[mcp_servers.node_repl]\ncommand = "/opt/app/node_repl"\n'
        'args = ["--token", "abc"]\nenv = { CLE = "sk-abcdefghijklmnopqrstuv" }\n\n[mcp_servers.distant]\nurl = "https://exemple.test/mcp?token=abc"\n')
    (tmp_path / ".codex" / "audit.config.toml").write_text('model = "gpt-6-sol"\nmodel_reasoning_effort = "xhigh"\n')
    (tmp_path / ".codex" / "casse.config.toml").write_text("model = \n")
    (tmp_path / ".codex" / "AGENTS.md").write_text("règle\n")
    return tmp_path


def faux_mcp(dossier, exe):
    return {"elements": [{"nom": "delta-ia", "origine": "serveur local", "cible": "https://delta-mcp-ruddy.vercel.app/mcp",
                          "transport": "http", "statut": "Connected"}], "source": f"claude mcp list (dans {dossier})", "raison": None}


def test_releve_sans_secret_et_raisons(tmp_path):
    e = etat.relever(maison_factice(tmp_path), lister_mcp=faux_mcp)
    cc, cx = e["outils"]["Claude Code"], e["outils"]["Codex"]
    assert cc["modele_par_defaut"]["valeur"] == "opus"
    assert cc["effort_par_defaut"]["valeur"] is None and "effortLevel" in cc["effort_par_defaut"]["raison"]
    assert cx["modele_par_defaut"]["valeur"] == "gpt-6-sol" and cx["niveau_de_service"]["valeur"] is None
    profils = {p["nom"]: p for p in cx["profils"]["elements"]}
    assert profils["audit"]["effort"]["valeur"] == "xhigh"
    assert profils["casse"]["modele"]["valeur"] is None and "TOML invalide" in profils["casse"]["modele"]["raison"]
    serveurs = {s["nom"]: s for s in cx["serveurs_mcp"]["elements"]}
    assert serveurs["node_repl"] == {"nom": "node_repl", "transport": "stdio", "cible": "node_repl"}
    assert serveurs["distant"]["cible"] == "https://exemple.test/mcp"
    texte = json.dumps(e)
    assert "sk-" not in texte and "abc" not in texte and "SECRET" not in texte and "/opt/app" not in texte
    glob_ = {g["nom"]: g for g in e["instructions_globales"]}
    assert glob_["AGENTS.md global"]["present"] and not glob_["CLAUDE.md global"]["present"]


def test_ligne_claude_mcp_list():
    m = etat._RE_LIGNE_MCP.match("delta-ia: https://delta-mcp-ruddy.vercel.app/mcp (HTTP) - ✔ Connected")
    assert m and m.group("nom") == "delta-ia" and m.group("transport") == "HTTP"
    m = etat._RE_LIGNE_MCP.match("claude.ai Canva: https://mcp.canva.com/mcp - ! Needs authentication")
    assert m and m.group("nom") == "claude.ai Canva" and m.group("statut") == "! Needs authentication"


def _valider(tmp_path, contenu):
    (tmp_path / "docs" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "data" / "etat.json").write_text(contenu if isinstance(contenu, str) else json.dumps(contenu))
    r = valider.Rapport()
    valider.verifier_etat(tmp_path, r)
    return r.erreurs


def test_valider_etat(tmp_path):
    e = etat.relever(maison_factice(tmp_path / "m"), lister_mcp=faux_mcp)
    assert _valider(tmp_path, e) == []
    e["outils"]["Claude Code"]["modele_par_defaut"] = {"valeur": None, "source": "x", "raison": None}
    assert any("sans `raison`" in x for x in _valider(tmp_path, e))
    assert any("champ sensible" in x for x in _valider(tmp_path, '{"releve_le": "2026-09-24T00:00:00", "env": {}}'))
    assert any("URL avec paramètres" in x for x in _valider(tmp_path, '{"u": "https://x.test/a?token=1"}'))
    assert any("champs attendus" in x for x in _valider(tmp_path, {"releve_le": "x"}))


def test_etat_dans_skill_et_spec():
    import fetch
    racine = Path(fetch.RACINE)
    skill = (racine / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/etat.py" in skill and "docs/data/etat.json" in skill
    assert skill.index("scripts/versions.py") < skill.index("scripts/etat.py")
    assert "docs/data/etat.json" in (racine / "SPEC.md").read_text(encoding="utf-8")
    assert "docs/data/etat.json" in (racine / "prompts" / "codex-delta.md").read_text(encoding="utf-8")
