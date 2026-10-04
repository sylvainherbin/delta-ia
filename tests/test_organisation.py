"""D77 : lecture OPÉRER simulée, vue réduite et absence de traces dans les données publiques."""

import copy
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import organisation
import valider
from conftest import ecrire_quotidien

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def vues():
    # Structure vérifiée avec `operer --json qui` et `operer --json etat` ; valeurs fictives.
    return {
        "qui": {
            "vue": "qui", "roles": [
                {"role": "chef-exemple", "dossier": "/home/factice/projets/exemple/", "modele": "opus",
                 "effort": "medium", "presence": "présente", "genre": "tmux", "nom": "session-factice",
                 "socket": "socket-factice", "unite": "claude-session@factice.service", "tmux": "tmux-factice",
                 "session": "session-factice", "session_figee": "session-figee-factice",
                 "source": "/home/factice/cc-socks/source", "reglages": {"prive": "reglages-factices"}},
                {"role": "auditeur", "dossier": None, "modele": None, "effort": None, "presence": "inconnue"},
                {"role": "sans-dossier"},
            ], "fichier_reglages": "/home/factice/reglages.json",
        },
        "etat": {
            "vue": "etat", "elements": [
                {"categorie": "missions", "id": "m-000000000001", "projet": "exemple", "etat": "EN_COURS",
                 "executant": "claude:session-factice", "prochaine_action": "action-privee"},
                {"categorie": "missions", "id": "m-000000000002", "projet": "exemple", "etat": "EN_COURS",
                 "executant": "codex:session-codex-factice"},
                {"categorie": "missions", "id": "m-000000000003", "projet": "exemple", "etat": "A_RELIRE",
                 "executant": "claude:autre-session"},
                {"categorie": "missions", "id": "m-000000000004", "projet": "autre", "etat": "TERMINEE",
                 "executant": None},
                {"categorie": "missions", "id": "m-000000000005", "projet": "autre", "etat": "EN_COURS",
                 "executant": "humain:nom-prive"},
                {"categorie": "echeances", "id": "echeance-factice", "texte": "texte-prive", "role": "chef-exemple",
                 "projet": "projet-hors-missions", "etat": "EN_COURS", "executant": "codex:session-factice"},
                {"categorie": "deblocages", "episode": {"texte": "episode-prive", "session": "session-factice"}},
            ],
            "totaux": {"missions": 5, "remises_bloquees": 0, "echeances": 1, "incidents": 0,
                       "alertes_desktop": 0, "messages": 0, "deblocages": 1},
            "propositions": [{"texte": "proposition-privee"}], "escape_auto": {"texte": "escape-prive"},
        },
    }


def simuler(monkeypatch, vues, panne=None, vue_en_echec="qui"):
    appels = []

    def lancer(args, **options):
        assert args[:2] == ["operer", "--json"]
        assert options == {"capture_output": True, "text": True, "encoding": "utf-8", "timeout": 20, "shell": False}
        vue = args[2]
        appels.append(vue)
        if panne is not None and vue == vue_en_echec:
            if isinstance(panne, Exception):
                raise panne
            return panne
        return subprocess.CompletedProcess(args, 0, json.dumps(vues[vue]), "")

    monkeypatch.setattr(organisation.subprocess, "run", lancer)
    return appels


def test_vue_reduite_correcte(monkeypatch, vues):
    avant = copy.deepcopy(vues)
    appels = simuler(monkeypatch, vues)
    releve = organisation.relever()
    assert appels == ["qui", "etat"]
    assert datetime.fromisoformat(releve.pop("releve_le")).tzinfo is not None
    assert releve == {
        "statut": "ok",
        "roles": [
            {"role": "chef-exemple", "projet": "exemple", "modele": "opus", "effort": "medium", "presence": "présente"},
            {"role": "auditeur", "projet": None, "modele": None, "effort": None, "presence": "inconnue"},
            {"role": "sans-dossier", "projet": None, "modele": None, "effort": None, "presence": None},
        ],
        "projets": {
            "autre": {"missions": {"TERMINEE": 1, "EN_COURS": 1}, "executants": []},
            "exemple": {"missions": {"EN_COURS": 2, "A_RELIRE": 1}, "executants": ["claude", "codex"]},
        },
        "totaux": vues["etat"]["totaux"],
    }
    assert vues == avant


def test_champs_et_contenus_exclus(monkeypatch, vues):
    simuler(monkeypatch, vues)
    texte = json.dumps(organisation.relever(), ensure_ascii=False)
    for champ in ("id", "socket", "unite", "tmux", "session", "source", "nom", "texte", "episode", "dossier",
                  "session_figee", "reglages", "propositions", "escape_auto"):
        assert f'"{champ}"' not in texte
    for valeur in ("m-00000000000", "/home/", "session-factice", "socket-factice", "tmux-factice",
                   "session-codex-factice", "session-figee-factice", "autre-session", "nom-prive",
                   "action-privee", "texte-prive", "episode-prive", "reglages-factices", "cc-socks", "claude-session@",
                   "echeance-factice", "projet-hors-missions", "proposition-privee", "escape-prive"):
        assert valeur not in texte


@pytest.mark.parametrize("vue_en_echec", ["qui", "etat"])
@pytest.mark.parametrize("panne, raison", [
    (FileNotFoundError("/chemin/prive"), "absent"),
    (subprocess.CompletedProcess([], 7, "sortie-privee", "erreur-privee"), "code de sortie 7"),
    (subprocess.TimeoutExpired("operer", 20, output="sortie-privee"), "délai de 20 s dépassé"),
    (subprocess.CompletedProcess([], 0, "JSON cassé : sortie-privee", ""), "JSON illisible"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "sortie-privee"), "JSON illisible"),
    (PermissionError("/chemin/prive"), "exécution impossible"),
])
def test_echec_remplace_le_releve_et_sort_a_zero(tmp_path, monkeypatch, capsys, vues, vue_en_echec, panne, raison):
    chemin = tmp_path / "raw" / "organisation.json"
    chemin.parent.mkdir()
    chemin.write_text('{"statut":"ok","roles":["ancien-releve"]}', encoding="utf-8")
    appels = simuler(monkeypatch, vues, panne, vue_en_echec)
    assert organisation.main(["--racine", str(tmp_path)]) == 0
    releve = json.loads(chemin.read_text(encoding="utf-8"))
    assert set(releve) == {"statut", "raison", "releve_le"}
    assert releve["statut"] == "echec" and raison in releve["raison"]
    assert datetime.fromisoformat(releve["releve_le"]).tzinfo is not None
    sortie = capsys.readouterr()
    assert sortie.out == f"! AVERTISSEMENT : organisation OPÉRER non lue ({releve['raison']})\n"
    assert sortie.err == ""
    assert appels == (["qui"] if vue_en_echec == "qui" else ["qui", "etat"])
    assert all(prive not in json.dumps(releve) + sortie.out for prive in ("prive", "ancien-releve"))


@pytest.mark.parametrize("vue, contenu", [
    ("qui", []), ("qui", {}), ("qui", {"vue": "qui", "roles": None}),
    ("qui", {"vue": "qui", "roles": [None]}),
    ("qui", {"vue": "qui", "roles": [{"role": "test", "dossier": {"session": "prive"}}]}),
    ("etat", {"vue": "etat", "elements": {}, "totaux": {}}),
    ("etat", {"vue": "etat", "elements": [], "totaux": None}),
    ("etat", {"vue": "etat", "elements": [{"categorie": "missions"}], "totaux": {}}),
])
def test_structure_invalide_reste_un_echec_non_bloquant(tmp_path, monkeypatch, vues, vue, contenu):
    vues[vue] = contenu
    simuler(monkeypatch, vues)
    assert organisation.main(["--racine", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "raw" / "organisation.json").read_text())["statut"] == "echec"


def test_ecriture_atomique(tmp_path, monkeypatch, vues):
    simuler(monkeypatch, vues)
    chemin = tmp_path / "raw" / "organisation.json"
    chemin.parent.mkdir()
    chemin.write_text("ancien relevé", encoding="utf-8")
    remplacer = Path.replace
    remplacements = []

    def verifier_avant_remplacement(temporaire, destination):
        assert destination == chemin and temporaire.parent == chemin.parent
        assert chemin.read_text(encoding="utf-8") == "ancien relevé"
        assert json.loads(temporaire.read_text(encoding="utf-8"))["statut"] == "ok"
        remplacements.append(destination)
        return remplacer(temporaire, destination)

    monkeypatch.setattr(Path, "replace", verifier_avant_remplacement)
    assert organisation.main(["--racine", str(tmp_path)]) == 0
    assert remplacements == [chemin]
    assert json.loads(chemin.read_text(encoding="utf-8"))["statut"] == "ok"
    assert list(chemin.parent.iterdir()) == [chemin]


def test_cli_avec_faux_operer_dans_path(tmp_path, monkeypatch, vues):
    binaires = tmp_path / "bin"
    binaires.mkdir()
    appels = tmp_path / "appels.txt"
    executable = binaires / "operer"
    executable.write_text(
        f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n"
        f"with Path({str(appels)!r}).open('a') as f: f.write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"assert sys.argv[1] == '--json'\nprint(json.dumps({vues!r}[sys.argv[2]]))\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaires))
    commande = [sys.executable, str(RACINE / "scripts" / "organisation.py"), "--racine", str(tmp_path / "releve")]
    resultat = subprocess.run(commande, capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 0, resultat.stderr
    assert appels.read_text() == "--json qui\n--json etat\n"
    chemin = tmp_path / "releve" / "raw" / "organisation.json"
    assert json.loads(chemin.read_text())["statut"] == "ok"
    executable.unlink()
    resultat = subprocess.run(commande, capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 0, resultat.stderr
    assert json.loads(chemin.read_text())["statut"] == "echec"
    assert "! AVERTISSEMENT" in resultat.stdout


@pytest.mark.parametrize("contenu, motif", [
    ("m-000000000001", "m-[0-9a-f]{12}"), ("cc-socks", "cc-socks"), ("claude-session@", "claude-session@"),
])
@pytest.mark.parametrize("chemin", ["etat.json", "claude/notes.txt", "kb/openai/notes.json"])
def test_controle_refuse_chaque_motif_dans_tout_docs_data(tmp_path, contenu, motif, chemin):
    cible = tmp_path / "docs" / "data" / chemin
    cible.parent.mkdir(parents=True)
    cible.write_text(contenu, encoding="utf-8")
    rapport = valider.Rapport()
    valider.verifier_organisation_privee(tmp_path, rapport)
    assert len(rapport.erreurs) == 1
    assert f"docs/data/{chemin}" in rapport.erreurs[0] and motif in rapport.erreurs[0]


@pytest.mark.parametrize("contenu", ["m-000000000001", "cc-socks", "claude-session@"])
def test_cli_validation_refuse_une_trace_dans_un_autre_perimetre(tmp_path, capsys, contenu):
    (tmp_path / "CONTEXTE.md").write_text((RACINE / "CONTEXTE.md").read_text(encoding="utf-8"), encoding="utf-8")
    ecrire_quotidien(tmp_path, "openai", {}, "2026-10-04")
    args = ["--racine", str(tmp_path), "--perimetre", "openai"]
    assert valider.main(args) == 0
    cible = tmp_path / "docs" / "data" / "claude" / "notes.txt"
    cible.parent.mkdir()
    cible.write_text(contenu, encoding="utf-8")
    assert valider.main(args) == 1
    assert "docs/data/claude/notes.txt" in capsys.readouterr().err
    assert valider.main([*args, "--kb"]) == 1
    assert "docs/data/claude/notes.txt" in capsys.readouterr().err


@pytest.mark.parametrize("perimetre", ["claude", "openai", "actu"])
def test_donnees_actuelles_passent(perimetre):
    assert valider.main(["--racine", str(RACINE), "--perimetre", perimetre]) == 0
