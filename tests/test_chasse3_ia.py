"""Mission 9i : témoins de relecture sur d9dac06, sans correction de production.

Les deux défauts concernent les preuves et leur stabilité, pas le serveur déployé.
Toutes les écritures des sous-processus restent sous tmp_path dans le worktree.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import test_site_l3 as site


RACINE = Path(__file__).resolve().parent.parent


class PhaseRougeIncompatible(AssertionError):
    """La recette rejette les témoins courants, après préparation vérifiée."""


class TemoinFraicheurInvalide(AssertionError):
    """Le test audité rejette l'affichage correct d'un périmètre ancien."""


def phase_rouge_p15d(tmp_path, *, temoin_historique=False):
    """Exécute le début exact de P15d, en s'arrêtant avant sa suite MCP complète."""
    script = RACINE / "mcp/preuve-p15d.sh"
    source = script.read_text(encoding="utf-8")
    borne = '\n"$noeud" --test --test-reporter=tap --test-reporter-destination="$copie/verts.log"'
    assert source.count(borne) == 1
    prefixe = source.split(borne, 1)[0]
    racine = tmp_path / "racine"
    fichiers = [
        "mcp/preuve-p15d.sh", "mcp/preuve-p15c.sh", "mcp/api/mcp.js",
        "mcp/lib/consultation.js", "mcp/lib/textes.js",
        "mcp/test/mcp.test.js", "mcp/test/textes.test.js",
        "mcp/mesures/2026-10-28-surface.json",
    ]
    for rel in fichiers:
        cible = racine / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RACINE / rel, cible)
    if temoin_historique:
        ancien = subprocess.run(
            ["git", "show", "8a513c8:mcp/test/textes.test.js"], cwd=RACINE,
            check=True, capture_output=True,
        )
        (racine / "mcp/test/textes.test.js").write_bytes(ancien.stdout)
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=RACINE,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    temporaires = tmp_path / "tmp"
    temporaires.mkdir()
    sans_reseau = tmp_path / "sans-reseau.mjs"
    sans_reseau.write_text(
        'globalThis.fetch = () => { throw new Error("Mission 9i : réseau interdit"); };\n',
        encoding="utf-8",
    )
    env = dict(os.environ, GIT_DIR=git_dir, GIT_WORK_TREE=str(racine),
               TMPDIR=str(temporaires), NODE_OPTIONS=f"--import={sans_reseau}")
    # Un sous-runner Node doit réellement collecter ses tests, même sous node --test.
    env.pop("NODE_TEST_CONTEXT", None)
    preuve = tmp_path / "preuve"
    retour = subprocess.run(
        ["bash", "-c", prefixe, str(racine / "mcp/preuve-p15d.sh"), str(preuve)],
        cwd=racine, env=env, capture_output=True, text=True, timeout=120,
    )
    log = (preuve / "rouge-5a66288.log").read_text(encoding="utf-8")
    (tmp_path / "phase-rouge.log").write_text(retour.stdout + retour.stderr, encoding="utf-8")
    return retour, log


def test_chasse3_p15d_phase_rouge_avec_son_temoin_historique(tmp_path):
    retour, log = phase_rouge_p15d(tmp_path, temoin_historique=True)
    assert retour.returncode == 0, retour.stdout + retour.stderr
    assert re.search(r"^# tests 4$", log, re.MULTILINE)
    assert re.search(r"^# fail 4$", log, re.MULTILINE)
    assert "hookFailed" not in log


# Régression 9i-F1 : le rejeu doit survivre à l'évolution des témoins courants.
def test_chasse3_p15d_phase_rouge_rejouable_sur_la_tete(tmp_path):
    retour, log = phase_rouge_p15d(tmp_path)
    if retour.returncode != 0:
        assert re.search(r"^# tests 5$", log, re.MULTILINE), log
        assert re.search(r"^# fail 5$", log, re.MULTILINE), log
        assert "hookFailed" in log and "une seule borne de références à modifier" in log
        raise PhaseRougeIncompatible(
            "9i-F1 : la phase rouge de P15d s'arrête : 5 tests / 5 hookFailed, "
            "au lieu des 4 échecs attendus ; aucune assertion métier exécutée\n"
            + retour.stderr[:400]
        )


def preparer_horloge(tmp_path, monkeypatch, *, desynchronisee):
    docs = tmp_path / "docs"
    remplacer = {}
    for perimetre in ("claude", "openai", "actu"):
        rel = f"data/{perimetre}/index.json"
        index = json.loads((site.DOCS / rel).read_text(encoding="utf-8"))
        index["maj_le"] = (
            "2026-10-26T09:00:00+00:00" if desynchronisee and perimetre == "claude"
            else "2026-10-28T09:00:00+00:00"
        )
        cible = docs / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(index), encoding="utf-8")
        remplacer[rel] = index
    executer_reel = site.executer

    def avec_index(**entree):
        return executer_reel(**entree, remplacer=remplacer)

    monkeypatch.setattr(site, "DOCS", docs)
    monkeypatch.setattr(site, "executer", avec_index)


def test_chasse3_horloge_temoin_avec_passages_alignes(tmp_path, monkeypatch):
    preparer_horloge(tmp_path, monkeypatch, desynchronisee=False)
    site.test_horloge_fixee_decide_de_la_banniere_de_fraicheur()


# Régression 9i-F2 : l'alerte réelle à 49 h reste visible, et le scénario
# frais/tardif possède ses propres passages, même si les index sont décalés.
def test_chasse3_horloge_temoin_avec_passages_desynchronises(tmp_path, monkeypatch):
    preparer_horloge(tmp_path, monkeypatch, desynchronisee=True)
    texte = site.executer(langue="fr", ancres=["#aujourdhui"], horloge=site.horloge_des_donnees())["etapes"][0]["texte"]
    assert texte.startswith("Claude Code n'a pas tourné depuis 49 h"), texte[:120]
    try:
        site.test_horloge_fixee_decide_de_la_banniere_de_fraicheur()
    except AssertionError as erreur:
        raise TemoinFraicheurInvalide(
            "9i-F2 : le témoin de fraîcheur rejette des index valides décalés de 48 h, "
            f"alors que le site affiche correctement : {texte[:100]}"
        ) from erreur
