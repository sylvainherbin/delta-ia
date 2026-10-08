"""D65 : état volatil des outils -> docs/data/etat.json, et son contrôle."""

import json
import subprocess
from pathlib import Path

import pytest

import etat
import organisation
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


@pytest.fixture
def etat_factice(tmp_path, monkeypatch):
    releve = etat.relever(maison_factice(tmp_path / "maison"), lister_mcp=faux_mcp)
    monkeypatch.setattr(etat, "relever", lambda: releve)
    return releve


@pytest.mark.parametrize("panne", [
    None,
    FileNotFoundError("chemin-prive"),
    subprocess.CompletedProcess([], 7, "sortie-privee", "erreur-privee"),
    subprocess.TimeoutExpired("operer", 20, output="sortie-privee"),
    subprocess.CompletedProcess([], 0, "JSON cassé : sortie-privee", ""),
])
def test_main_lit_organisation_apres_etat_sans_alterer_son_json(tmp_path, monkeypatch, capsys, etat_factice, panne):
    chemin_etat = tmp_path / "docs" / "data" / "etat.json"
    attendu = (json.dumps({"pertinent_pour_profil": False, **etat_factice}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    chemin_organisation = tmp_path / "raw" / "organisation.json"
    chemin_organisation.parent.mkdir()
    chemin_organisation.write_text('{"statut":"ok","roles":["ancien-releve"]}', encoding="utf-8")
    appels = []

    def lancer(args, **options):
        assert chemin_etat.read_bytes() == attendu, "le relevé D65 doit être écrit avant la lecture OPÉRER"
        assert args == ["operer", "--json", "qui" if not appels else "etat"]
        assert options == {"capture_output": True, "text": True, "encoding": "utf-8", "timeout": 120, "shell": False}
        appels.append(args[-1])
        if args[-1] == "qui":
            vue = {"vue": "qui", "roles": []}
        elif panne is not None:
            if isinstance(panne, Exception):
                raise panne
            return panne
        else:
            vue = {"vue": "etat", "elements": [], "totaux": {"missions": 0}}
        return subprocess.CompletedProcess(args, 0, json.dumps(vue), "")

    monkeypatch.setattr(organisation.subprocess, "run", lancer)
    assert etat.main(["--racine", str(tmp_path)]) == 0
    assert appels == ["qui", "etat"]
    assert chemin_etat.read_bytes() == attendu
    releve = json.loads(chemin_organisation.read_text(encoding="utf-8"))
    assert releve["statut"] == ("ok" if panne is None else "echec")
    sortie = capsys.readouterr()
    assert ("! AVERTISSEMENT" in sortie.out) == (panne is not None)
    assert all(prive not in json.dumps(releve) + sortie.out + sortie.err for prive in ("prive", "ancien-releve"))


def test_main_garde_son_code_si_organisation_ne_s_ecrit_pas(tmp_path, monkeypatch, capsys, etat_factice):
    def echec(racine):
        raise OSError("disque plein")

    monkeypatch.setattr(organisation, "ecrire_releve", echec)
    assert etat.main(["--racine", str(tmp_path)]) == 0
    assert "! AVERTISSEMENT : organisation OPÉRER non écrite (disque plein)" in capsys.readouterr().out
    assert (tmp_path / "docs" / "data" / "etat.json").exists()


def test_dry_run_ne_lit_pas_organisation_et_n_ecrit_rien(tmp_path, monkeypatch, capsys, etat_factice):
    def interdit(*args, **kwargs):
        pytest.fail("--dry-run ne doit pas lire OPÉRER")

    monkeypatch.setattr(organisation, "ecrire_releve", interdit)
    assert etat.main(["--dry-run", "--racine", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"pertinent_pour_profil": False, **etat_factice}
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "docs").exists()


# ---------- D93 : bloc `comptes` (quotas D71 de rapports/usage.json) ----------
USAGE = {"releve_le": "2026-10-08T09:32:55.668Z", "source": "console-mur 0.0.0",
         "claude": {"session_5h": {"pct": 12, "remise_a_zero": "2026-10-08T10:00:01.012Z"},
                    "semaine": {"pct": 85, "remise_a_zero": "2026-10-11T16:00:01.012Z"},
                    "semaine_fable": {"pct": 0, "remise_a_zero": "2026-10-11T16:00:00.000Z"}},
         "chatgpt": {"semaine": {"pct": 5, "remise_a_zero": "2026-10-14T05:29:59.000Z", "releve_le": "2026-10-08T09:32:40.508Z"}},
         "machine": {"cpu_pct": 100, "disque_libre_go": 850.4}, "wifi": {"signal_pct": 44}}


def _usage(tmp_path, contenu):
    (tmp_path / "rapports").mkdir(exist_ok=True)
    (tmp_path / "rapports" / "usage.json").write_text(contenu if isinstance(contenu, str) else json.dumps(contenu))
    return tmp_path


def test_comptes_recopie_les_quatre_quotas_sans_machine_ni_wifi(tmp_path):
    c = etat.comptes(_usage(tmp_path, USAGE))
    assert c["statut"] == "ok" and c["releve_le"] == USAGE["releve_le"]
    assert list(c["quotas"]) == ["claude_session_5h", "claude_semaine", "claude_semaine_fable", "chatgpt_semaine"]
    assert c["quotas"]["claude_semaine"] == {"pct": 85, "remise_a_zero": "2026-10-11T16:00:01.012Z", "releve_le": USAGE["releve_le"]}
    assert c["quotas"]["chatgpt_semaine"]["releve_le"] == "2026-10-08T09:32:40.508Z"
    texte = json.dumps(c)
    assert "machine" not in texte and "wifi" not in texte and "cpu" not in texte and "disque" not in texte
    assert _valider(tmp_path, {"releve_le": "2026-10-08T00:00:00+00:00", "outils": {}, "mcp_claude_code": {},
                               "instructions_globales": [], "comptes": c}) == []


def test_comptes_fichier_absent_ou_illisible_donne_inconnu(tmp_path):
    for contenu in (None, "{pas du json", "[]", {"claude": {}}):
        racine = tmp_path / str(abs(hash(str(contenu))))
        racine.mkdir()
        if contenu is not None:
            _usage(racine, contenu)
        c = etat.comptes(racine)
        assert c["statut"] == "inconnu" and c["raison"] and set(c) == {"statut", "raison"}
        assert _valider(tmp_path, {"releve_le": "2026-10-08T00:00:00+00:00", "outils": {}, "mcp_claude_code": {},
                                   "instructions_globales": [], "comptes": c}) == []


def test_comptes_valeur_invalide_est_null_avec_raison(tmp_path):
    u = json.loads(json.dumps(USAGE))
    u["claude"]["semaine"]["pct"] = 140
    u["claude"]["semaine_fable"]["pct"] = "beaucoup"
    u["claude"]["session_5h"]["remise_a_zero"] = "demain"
    u["chatgpt"]["semaine"]["pct"] = 33.4
    c = etat.comptes(_usage(tmp_path, u))
    q = c["quotas"]
    assert q["claude_semaine"]["pct"] is None and "0 à 100" in q["claude_semaine"]["raison"]
    assert q["claude_semaine_fable"]["pct"] is None
    assert q["claude_session_5h"]["pct"] == 12 and q["claude_session_5h"]["remise_a_zero"] is None
    assert q["chatgpt_semaine"]["pct"] == 33


def test_valider_comptes(tmp_path):
    base = {"releve_le": "2026-10-08T00:00:00+00:00", "outils": {}, "mcp_claude_code": {}, "instructions_globales": []}
    ok = etat.comptes(_usage(tmp_path, USAGE))

    def avec(modif):
        c = json.loads(json.dumps(ok))
        modif(c)
        return _valider(tmp_path, {**base, "comptes": c})
    assert avec(lambda c: None) == []
    assert any("entier de 0 à 100" in x for x in avec(lambda c: c["quotas"]["claude_semaine"].update(pct=101)))
    assert any("entier de 0 à 100" in x for x in avec(lambda c: c["quotas"]["claude_semaine"].update(pct=12.5)))
    assert any("entier de 0 à 100" in x for x in avec(lambda c: c["quotas"]["claude_semaine"].update(pct=True)))
    assert any("sans `raison`" in x for x in avec(lambda c: c["quotas"]["claude_semaine"].update(pct=None)))
    assert avec(lambda c: c["quotas"]["claude_semaine"].update(pct=None, raison="absent")) == []
    assert any("ISO 8601" in x for x in avec(lambda c: c["quotas"]["claude_semaine"].update(remise_a_zero="demain")))
    assert avec(lambda c: c["quotas"]["claude_semaine"].update(remise_a_zero=None)) == []
    assert any("exactement" in x for x in avec(lambda c: c["quotas"].pop("chatgpt_semaine")))
    assert any("machine ni de wifi" in x for x in avec(lambda c: c.update(machine={"cpu_pct": 1})))
    assert any("statut" in x for x in avec(lambda c: c.update(statut="peut-être")))
    assert any("sans `raison`" in x for x in _valider(tmp_path, {**base, "comptes": {"statut": "inconnu"}}))
    assert any("aucune valeur devinée" in x for x in _valider(tmp_path, {**base, "comptes": {"statut": "inconnu", "raison": "x", "quotas": {}}}))
    # comptes absent : accepté (profil sans relevés de la machine)
    assert _valider(tmp_path, base) == []
