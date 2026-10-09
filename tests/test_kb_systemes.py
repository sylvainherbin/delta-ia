"""D108 : les entrées propres à un système exclu sont écartées d'après le nom et le texte, sans marqueur de section."""

import json
from pathlib import Path

import pytest

from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.documentation import charger_documentation
from deltalib.kb.extracteurs import EXTRACTEURS
from deltalib.kb.modeles import EntreeExtraite
from deltalib.kb.systemes import ecarter, systeme_exclu_de

KB = Path(__file__).parent / "fixtures" / "kb"
REELLES = {e["id"]: e for e in json.loads((KB / "entrees_systemes.json").read_text(encoding="utf-8"))}  # entrées publiées le 09/10/2026

WINDOWS = {  # nom ou « Windows only » dans la documentation
    "codex-parametres-features-prefer-mxc", "codex-commandes-sandbox-add-read-dir", "codex-commandes-setup-default-sandbox",
    "claude-code-parametres-claude-code-git-bash-path", "claude-code-parametres-claude-code-powershell-respect-execution-policy",
}
MACOS = {"codex-skills-page-extend-record-and-replay"}
DEUX = {"claude-code-parametres-desktop", "chatgpt-fonctionnalites-page-computer-use"}  # « Available on macOS and … Windows »
RESTENT = {  # simple mention d'un système, ou texte multi-systèmes : l'entrée reste
    "codex-parametres-features-unified-exec", "claude-code-parametres-claude-code-plugin-dirs", "claude-code-raccourcis-alt-d",
    "claude-code-parametres-sandbox-allowappleevents", "codex-parametres-codex-app-path", "codex-commandes-app", "claude-code-raccourcis-ctrl-w",
}


def sys_de(ident, exclus):
    e = REELLES[ident]
    return systeme_exclu_de(e["nom"], e["description_source"], exclus)


def test_fixture_couvre_tous_les_cas():
    assert set(REELLES) == WINDOWS | MACOS | DEUX | RESTENT


def test_profil_par_defaut_windows_et_macos():
    exclus = ["windows", "macos"]
    assert {i for i in REELLES if sys_de(i, exclus)} == WINDOWS | MACOS | DEUX
    assert sys_de("codex-parametres-features-prefer-mxc", exclus) == "windows"


def test_profil_windows_seul_garde_macos():
    exclus = ["windows"]
    assert {i for i in REELLES if sys_de(i, exclus)} == WINDOWS
    assert sys_de("codex-skills-page-extend-record-and-replay", exclus) is None
    assert sys_de("chatgpt-fonctionnalites-page-computer-use", exclus) is None  # cite macOS, non exclu : multi-systèmes


def test_aucun_systeme_exclu_ne_change_rien():
    assert not any(sys_de(i, []) for i in REELLES)


@pytest.mark.parametrize("nom, texte, exclus, attendu", [
    ("features.prefer_mxc", "Prefer the new runtime.", ["windows"], "windows"),   # jeton du nom
    ("windows_sandbox", "Sandbox mode.", ["windows"], "windows"),
    ("keychain_mode", "Where secrets are stored.", ["macos"], "macos"),
    ("keychain_mode", "Where secrets are stored.", ["windows"], None),
    ("x", "Windows only: path to the shell.", ["windows", "macos"], "windows"),
    ("x", "Windows-only option.", ["windows"], "windows"),
    ("x", "Only available on macOS.", ["macos"], "macos"),
    ("x", "Works on Windows and Linux.", ["windows"], None),   # multi-systèmes
    ("x", "Windows only, or Linux with WSL.", ["windows"], None),
    ("x", "On Windows, set this to 1.", ["windows"], None),    # simple mention : ambiguë
    ("x", "Set a shell.", ["windows", "macos"], None),
    ("machine", "Machine name.", ["macos"], None),            # « mac » n'est pas un jeton de « machine »
    ("x", "Linux only: use bubblewrap.", ["linux"], "linux"),   # linux par le même mécanisme
    ("x", "Linux only: use bubblewrap.", ["windows"], None),
    ("x", "Windows only.", ["linux"], None),
])
def test_detection_nom_et_texte(nom, texte, exclus, attendu):
    assert systeme_exclu_de(nom, texte, exclus) == attendu


def test_prefer_mxc_extrait_puis_ecarte_puis_retire():
    """Le bloc de la documentation Codex passe l'extracteur `configtable` (pas de motif dans `exclure`) ; D108 l'écarte, puis il est retiré."""
    doc = {d.id: d for d in charger_documentation(RACINE / "sources.yaml")}["oa-config"]
    page = (KB / "oa_config.md").read_text(encoding="utf-8")
    bloc = ('    {\n      key: "features.prefer_mxc",\n      type: "boolean",\n      description:\n        "Prefer MXC for local Windows execution '
            'when native capabilities and policy allow it; otherwise retain the configured legacy sandbox and setup.",\n    },\n')
    page = page.replace('    {\n      key: "model",', bloc + '    {\n      key: "model",', 1)
    extraites = EXTRACTEURS[doc.extracteur](doc, {"page": page})
    assert "features.prefer_mxc" in [e.nom for e in extraites]
    gardees, ecartees = ecarter(extraites, ["windows", "macos"])
    assert [(s, e.nom) for s, e in ecartees] == [("windows", "features.prefer_mxc")]
    assert len(gardees) == len(extraites) - 1
    publiees, _ = cat.fusionner({}, extraites, {doc.id}, jour="2026-10-09")  # déjà publiée
    publiees, modif = cat.fusionner(publiees, gardees, {doc.id}, jour="2026-10-10")
    assert modif["retirees"] == ["codex-parametres-features-prefer-mxc"]
    assert publiees["codex-parametres-features-prefer-mxc"]["retiree"] is True  # retirée, pas supprimée


def test_resume_compte_avant_apres_par_systeme():
    def e(nom, texte):
        return EntreeExtraite(produit="codex", categorie="parametres", nom=nom, usage=nom, description_source=texte, url="u", libelle="l", origine="o")
    entrees = [e(f"k{i}", "Windows only.") for i in range(12)] + [e("m", "macOS only."), e("garde", "Set a value.")]
    gardees, ecartees = ecarter(entrees, ["windows", "macos"])
    r = cat.resume_ecartees(ecartees, len(gardees))
    assert r["avant"] == 14 and r["apres"] == 1 and r["par_systeme"] == {"windows": 12, "macos": 1}
    assert len(r["premieres"]) == 10 and r["premieres"][0] == {"systeme": "windows", "id": "codex-parametres-k0"}
