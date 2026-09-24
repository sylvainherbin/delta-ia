"""D54 à D56 : versions installées, dernière version publiée connue de Delta, contrôle de versions.json."""

import json
from pathlib import Path

import pytest

import valider
import versions as v


def test_comparer():
    assert v.comparer("2.1.280", "2.1.280") == "a_jour"
    assert v.comparer("2.1.281", "2.1.280") == "a_jour"
    assert v.comparer("0.155.0-alpha.16", "0.156.1") == "en_retard"
    assert v.comparer("0.156.1-alpha.1", "0.156.1") == "en_retard"
    assert v.comparer("26.917.51856", "26.908", composantes=2) == "a_jour"
    assert v.comparer("26.901.1", "26.908", composantes=2) == "en_retard"
    assert v.comparer(None, "1.0.0") == "inconnu" and v.comparer("1.0.0", None) == "inconnu"


def test_versions_publiees_depuis_etat_brut_et_quotidiens(tmp_path):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir(); (tmp_path / "docs" / "data" / "openai").mkdir(parents=True)
    (tmp_path / "state" / "openai.json").write_text(json.dumps({"vus": {
        "rust-v0.155.1": {"source_id": "codex-cli-releases"}, "rust-v0.156.1": {"source_id": "codex-cli-releases"},
        "oa-codex/2026-09-11-app": {"source_id": "openai-changelog-codex-app"}}}))
    (tmp_path / "raw" / "openai-nouveautes.json").write_text(json.dumps({"nouveautes": [
        {"id": "oa-codex/2026-09-25-app", "source_id": "openai-changelog-codex-app", "version": "26.925"}]}))
    (tmp_path / "docs" / "data" / "openai" / "2026-09-23.json").write_text(json.dumps({"elements": [
        {"ids_bruts": ["oa-codex/2026-09-11-app"], "version": "26.908"}, {"ids_bruts": ["rust-v0.157.0"], "version": "0.157.0"}]}))
    assert v.versions_publiees(tmp_path, "codex-cli-releases", r"rust-v(\d+\.\d+\.\d+)", "openai") == ["0.155.1", "0.156.1", "0.157.0"]
    assert v.versions_publiees(tmp_path, "openai-changelog-codex-app", r"oa-codex/.*-app", "openai") == ["26.908", "26.925"]


def test_app_chatgpt_lue_dans_le_flux_codex_app(monkeypatch):
    from conftest import FauxClient, RACINE
    monkeypatch.setattr(v, "claude_code", lambda: ("2.1.280", "claude --version", None))
    monkeypatch.setattr(v, "codex_app", lambda: ("0.155.0-alpha.16.4", "codex --version", None))
    monkeypatch.setattr(v, "codex_terminal", lambda: ("0.155.1", "codex --version", None))
    monkeypatch.setattr(v, "paquet_dpkg", lambda nom: ("26.917.51856", f"dpkg-query -W {nom}", None))
    lignes = {l["outil"]: l for l in v.detecter(RACINE, client=FauxClient())}
    app = lignes["ChatGPT Desktop"]
    assert app["derniere_publiee"] == "26.908" and app["statut"] == "a_jour" and app["source_derniere"] == "openai-changelog-codex-app"
    assert "Correspondance déduite, non documentée par OpenAI" in app["note"]


def test_app_chatgpt_flux_en_echec(monkeypatch):
    from conftest import FauxClient, RACINE
    from deltalib.modeles import ErreurReseau
    monkeypatch.setattr(v, "paquet_dpkg", lambda nom: ("26.917.51856", f"dpkg-query -W {nom}", None))
    monkeypatch.setattr(v, "claude_code", lambda: (None, "x", "absent"))
    monkeypatch.setattr(v, "codex_app", lambda: (None, "x", "absent"))
    monkeypatch.setattr(v, "codex_terminal", lambda: (None, "x", "absent"))
    url = "https://learn.chatgpt.com/docs/changelog/codex-app.json"
    app = {l["outil"]: l for l in v.detecter(RACINE, client=FauxClient({url: ErreurReseau("HTTP 503")}))}["ChatGPT Desktop"]
    assert app["statut"] == "inconnu" and app["derniere_publiee"] is None and "HTTP 503" in app["raison"]
    app = {l["outil"]: l for l in v.detecter(RACINE, client=FauxClient({url: ('{"items": []}', "application/json")}))}["ChatGPT Desktop"]
    assert app["statut"] == "inconnu" and "FormatInattendu" in app["raison"]


def test_detecter_sans_outils_ni_source(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "claude_code", lambda: (None, "claude --version", "exécutable `claude` introuvable"))
    monkeypatch.setattr(v, "codex_app", lambda: ("0.155.0-alpha.16.4", "codex --version", None))
    monkeypatch.setattr(v, "codex_terminal", lambda: ("0.155.1", "codex --version", None))
    monkeypatch.setattr(v, "paquet_dpkg", lambda nom: ("26.917.51856" if nom == "chatgpt" else None, f"dpkg-query -W {nom}",
                                                        None if nom == "chatgpt" else "paquet non installé"))
    lignes = {l["outil"]: l for l in v.detecter(tmp_path)}
    assert set(lignes) == {"Claude Code", "Codex (app ChatGPT)", "Codex CLI (terminal, non utilisée)", "ChatGPT Desktop", "Claude Desktop"}
    assert lignes["Claude Code"]["version"] is None and lignes["Claude Code"]["raison"] and lignes["Claude Code"]["statut"] == "inconnu"
    cli = lignes["Codex CLI (terminal, non utilisée)"]
    assert cli["derniere_publiee"] is None and cli["statut"] == "non_utilise", "pas de source : rien à afficher, jamais d'alerte"
    assert lignes["ChatGPT Desktop"]["statut"] == "inconnu" and "sources.yaml" in lignes["ChatGPT Desktop"]["raison"]
    assert lignes["Claude Desktop"]["source_derniere"] is None


def test_main_ecrit_versions_json_valide(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(v, "claude_code", lambda: ("2.1.280", "claude --version", None))
    monkeypatch.setattr(v, "codex_app", lambda: ("0.155.0-alpha.16.4", "codex --version", None))
    monkeypatch.setattr(v, "codex_terminal", lambda: ("0.155.1", "codex --version", None))
    monkeypatch.setattr(v, "paquet_dpkg", lambda nom: ("1.0.0", f"dpkg-query -W {nom}", None))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "claude.json").write_text(json.dumps({"vus": {"claude-code-2.1.280": {"source_id": "claude-code-changelog"}}}))
    assert v.main(["--racine", str(tmp_path)]) == 0
    lignes = json.loads((tmp_path / "docs" / "data" / "versions.json").read_text())
    assert lignes[0] == {**lignes[0], "outil": "Claude Code", "derniere_publiee": "2.1.280", "statut": "a_jour", "source_derniere": "claude-code-changelog"}
    r = valider.Rapport()
    valider.verifier_versions(tmp_path, r)
    assert r.ok, r.erreurs
    assert v.main(["--racine", str(tmp_path / "vide"), "--dry-run"]) == 0 and not (tmp_path / "vide").exists()


@pytest.mark.parametrize("modif, attendu", [
    (lambda l: l.update(statut="peut-etre"), "statut inconnu"),
    (lambda l: l.update(version=None, statut="inconnu"), "sans `raison`"),
    (lambda l: l.update(derniere_publiee=None), "doit être `inconnu`"),
    (lambda l: l.update(source_derniere=None), "sans `source_derniere`"),
    (lambda l: l.pop("methode"), "champs attendus"),
])
def test_versions_json_invalide(tmp_path, modif, attendu):
    l = {"outil": "Claude Code", "version": "2.1.280", "detectee_le": "2026-09-23T16:00:00+00:00", "methode": "claude --version",
         "derniere_publiee": "2.1.280", "source_derniere": "claude-code-changelog", "statut": "a_jour"}
    modif(l)
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "docs" / "data" / "versions.json").write_text(json.dumps([l]))
    r = valider.Rapport()
    valider.verifier_versions(tmp_path, r)
    assert any(attendu in e for e in r.erreurs), r.erreurs


def test_versions_dans_la_skill_delta():
    from pathlib import Path
    import fetch
    racine = Path(fetch.RACINE)
    skill = (racine / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/versions.py" in skill and "docs/data/versions.json" in skill
    assert "docs/data/versions.json" in (racine / "SPEC.md").read_text(encoding="utf-8")


def test_note_app_construite_avec_les_valeurs_detectees(monkeypatch):
    from conftest import FauxClient, RACINE
    monkeypatch.setattr(v, "claude_code", lambda: (None, "x", "absent"))
    monkeypatch.setattr(v, "codex_app", lambda: (None, "x", "absent"))
    monkeypatch.setattr(v, "codex_terminal", lambda: (None, "x", "absent"))
    monkeypatch.setattr(v, "paquet_dpkg", lambda nom: ("26.917.62051", f"dpkg-query -W {nom}", None))
    app = {l["outil"]: l for l in v.detecter(RACINE, client=FauxClient())}["ChatGPT Desktop"]
    assert "26.917.62051 -> 26.917" in app["note"] and "(ex. 26.908)" in app["note"] and "51856" not in app["note"]
    assert "51856" not in (Path(v.__file__)).read_text(encoding="utf-8")
    assert "introuvable" in v.note_app((None, "x", "absent"), [])


def test_deux_codex_embarque_et_cli_non_utilisee(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "claude_code", lambda: ("2.1.280", "claude --version", None))
    monkeypatch.setattr(v, "codex_app", lambda: ("0.155.0-alpha.16.4", "/usr/lib/chatgpt/resources/codex --version", None))
    monkeypatch.setattr(v, "codex_terminal", lambda: ("0.155.1", "codex --version (npm global, nvm)", None))
    monkeypatch.setattr(v, "paquet_dpkg", lambda nom: ("26.917.71314", f"dpkg-query -W {nom}", None))
    monkeypatch.setattr(v, "versions_app_chatgpt", lambda racine, client=None: (["26.908"], None))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "openai.json").write_text(json.dumps({"vus": {"rust-v0.156.1": {"source_id": "codex-cli-releases"}}}))
    lignes = {l["outil"]: l for l in v.detecter(tmp_path)}
    app = lignes["Codex (app ChatGPT)"]
    assert app["statut"] == "embarque" and app["derniere_publiee"] is None and app["source_derniere"] is None
    assert "26.917.71314" in app["note"] and "non comparé" in app["note"] and "raison" not in app
    cli = lignes["Codex CLI (terminal, non utilisée)"]
    assert cli["statut"] == "non_utilise" and cli["derniere_publiee"] == "0.156.1", "stable donnée pour information, sans en_retard"
    assert "non utilisée [déclaré]" in cli["note"] and "dernière stable publiée 0.156.1" in cli["note"]
    assert [l["outil"] for l in v.detecter(tmp_path)][:3] == ["Claude Code", "Codex (app ChatGPT)", "Codex CLI (terminal, non utilisée)"]
    # CLI absente : inconnu, avec raison
    monkeypatch.setattr(v, "codex_terminal", lambda: (None, "codex --version", "introuvable"))
    cli = {l["outil"]: l for l in v.detecter(tmp_path)}["Codex CLI (terminal, non utilisée)"]
    assert cli["statut"] == "inconnu" and cli["raison"] == "introuvable"
    r = valider.Rapport()
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "docs" / "data" / "versions.json").write_text(json.dumps(v.detecter(tmp_path)))
    valider.verifier_versions(tmp_path, r)
    assert r.ok, r.erreurs


def test_codex_terminal_exclut_l_exe_de_l_app(tmp_path, monkeypatch):
    app = tmp_path / "app" / "codex"; app.parent.mkdir(); app.write_text("#!/bin/sh\necho codex-cli 0.155.0-alpha.16.4\n"); app.chmod(0o755)
    npm = tmp_path / "nvm" / "codex"; npm.parent.mkdir(); npm.write_text("#!/bin/sh\necho codex-cli 0.155.1\n"); npm.chmod(0o755)
    monkeypatch.setattr(v, "_exe_codex_app", lambda: str(app))
    monkeypatch.setattr(v.shutil, "which", lambda n: str(app) if n == "codex" else None)
    monkeypatch.setattr(v.glob, "glob", lambda motif: [str(npm)])
    assert v.codex_app()[0] == "0.155.0-alpha.16.4"
    assert v.codex_terminal()[0] == "0.155.1", "le codex de l'app, même dans le PATH, n'est pas la CLI autonome"


@pytest.mark.parametrize("modif, attendu", [
    (lambda l: l.update(derniere_publiee="0.156.1", source_derniere="codex-cli-releases"), "`embarque` : non comparé"),
    (lambda l: l.pop("note"), "`note` obligatoires"),
])
def test_versions_json_embarque_invalide(tmp_path, modif, attendu):
    l = {"outil": "Codex (app ChatGPT)", "version": "0.155.0-alpha.16.4", "detectee_le": "2026-09-24T16:00:00+00:00",
         "methode": "codex --version", "derniere_publiee": None, "source_derniere": None, "statut": "embarque", "note": "n"}
    modif(l)
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "docs" / "data" / "versions.json").write_text(json.dumps([l]))
    r = valider.Rapport()
    valider.verifier_versions(tmp_path, r)
    assert any(attendu in e for e in r.erreurs), r.erreurs
