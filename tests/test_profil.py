"""D79 : profil.yaml, champ pertinent_pour_profil, exclusions de systèmes de la base."""

import json
from pathlib import Path

import pytest

import etat as etat_mod
import versions as versions_mod
from deltalib import profil
from deltalib.kb import extracteurs

RACINE = Path(__file__).resolve().parent.parent


def ecrire(tmp_path, texte):
    (tmp_path / "profil.yaml").write_text(texte, encoding="utf-8")
    return tmp_path


def test_defauts_sans_fichier(tmp_path):
    assert profil.charger(tmp_path) == {"priorites": [], "progression": None, "releves_machine": False,
                                         "base": {"exclure_systemes": ["windows", "macos"]}}


def test_defauts_fichier_vide_ou_partiel(tmp_path):
    assert profil.charger(ecrire(tmp_path, ""))["releves_machine"] is False
    p = profil.charger(ecrire(tmp_path, "releves_machine: true\n"))
    assert p["releves_machine"] is True and p["priorites"] == [] and p["base"]["exclure_systemes"] == ["windows", "macos"]


def test_profil_de_sylvain():
    p = profil.charger(RACINE)
    assert p["progression"] == "PROGRESSION.md" and p["releves_machine"] is True
    assert p["base"]["exclure_systemes"] == ["windows", "macos"]
    assert p["priorites"][0] == "trading-sim d'abord" and len(p["priorites"]) == 4


@pytest.mark.parametrize("texte", [
    "priorites: abc\n", "priorites: [1, 2]\n", "progression: 3\n", "releves_machine: oui\n", "releves_machine: 1\n",
    "base: []\n", "base: {exclure_systemes: windows}\n", "base: {exclure_systemes: [freebsd]}\n", "base: {x: 1}\n",
    "inconnue: 1\n", "- a\n", "a: [\n",
])
def test_erreurs_de_type(tmp_path, texte):
    with pytest.raises(profil.ProfilInvalide):
        profil.charger(ecrire(tmp_path, texte))


@pytest.mark.parametrize("systemes, attendu", [("[linux]", ["linux"]), ("[windows, linux]", ["windows", "linux"]),
                                               ("[Linux, MACOS]", ["linux", "macos"]), ("[windows, macos, linux]", ["windows", "macos", "linux"])])
def test_linux_accepte_dans_exclure_systemes(tmp_path, systemes, attendu):
    p = profil.charger(ecrire(tmp_path, f"base:\n  exclure_systemes: {systemes}\n"))
    assert p["base"]["exclure_systemes"] == attendu


def test_linux_ne_change_pas_la_valeur_par_defaut(tmp_path):
    assert profil.charger(tmp_path)["base"]["exclure_systemes"] == ["windows", "macos"]
    assert profil.DEFAUTS["base"]["exclure_systemes"] == ["windows", "macos"]
    assert profil.SYSTEMES_CONNUS == ("windows", "macos", "linux")


def test_versions_pertinent_pour_profil(tmp_path, monkeypatch):
    monkeypatch.setattr(versions_mod, "detecter", lambda racine, client=None: [{"outil": "x", "version": None, "derniere_publiee": None, "statut": "inconnu", "methode": "m"}])
    for contenu, attendu in ((None, False), ("releves_machine: false\n", False), ("releves_machine: true\n", True)):
        racine = tmp_path / str(attendu) / str(contenu is None)
        racine.mkdir(parents=True)
        if contenu:
            ecrire(racine, contenu)
        versions_mod.main(["--racine", str(racine)])
        lignes = json.loads((racine / "docs" / "data" / "versions.json").read_text(encoding="utf-8"))
        assert list(lignes[0])[0] == "pertinent_pour_profil" and lignes[0]["pertinent_pour_profil"] is attendu


def test_etat_pertinent_pour_profil(tmp_path, monkeypatch):
    monkeypatch.setattr(etat_mod, "relever", lambda: {"releve_le": "2026-10-06T00:00:00+00:00", "outils": {
        "Claude Code": {"modele_par_defaut": {"valeur": None}}, "Codex": {"modele_par_defaut": {"valeur": None},
                                                                        "profils": {"elements": []}}},
        "mcp_claude_code": {}, "instructions_globales": []})
    monkeypatch.setattr(etat_mod.organisation, "ecrire_releve", lambda racine: None)
    monkeypatch.setattr(etat_mod, "credits_cloud", lambda: [])  # D102 : pas de lecture du vrai OPÉRER
    for contenu, attendu in ((None, False), ("releves_machine: true\n", True)):
        racine = tmp_path / str(attendu)
        racine.mkdir()
        if contenu:
            ecrire(racine, contenu)
        etat_mod.main(["--racine", str(racine)])
        e = json.loads((racine / "docs" / "data" / "etat.json").read_text(encoding="utf-8"))
        assert list(e)[0] == "pertinent_pour_profil" and e["pertinent_pour_profil"] is attendu


@pytest.fixture
def systemes():
    yield extracteurs.definir_systemes_exclus
    extracteurs.definir_systemes_exclus(None)


def test_defaut_exclut_windows_et_macos(systemes):
    systemes(None)
    assert extracteurs.systemes_exclus() == ["windows", "macos"]
    assert not extracteurs._garder_linux("Cmd+K") and not extracteurs._garder_linux("Windows only")
    assert extracteurs._garder_linux("Ctrl+K")
    assert extracteurs._rx_exclure("bedrock|windows|macos").pattern == "bedrock|windows|macos"
    assert extracteurs._rx_exclure("bedrock|windows").pattern == "bedrock|windows"


def test_exclusions_parametrees(systemes):
    systemes(["macos"])
    assert extracteurs._rx_exclure("bedrock|windows|macos").pattern == "bedrock|macos"
    assert extracteurs._garder_linux("Windows only") and not extracteurs._garder_linux("Cmd+K")
    systemes([])
    assert extracteurs._rx_exclure("windows|macos") is None
    assert extracteurs._rx_exclure("bedrock|windows|macos").pattern == "bedrock"
    assert extracteurs._garder_linux("Cmd+K") and extracteurs._classer_table_codex("MacOptions") is not None
    systemes(["windows"])
    assert extracteurs._classer_table_codex("WindowsOptions") is None and extracteurs._classer_table_codex("MacOptions") is not None


def test_etat_comptes_seulement_si_releves_machine(tmp_path, monkeypatch):
    """D93 : le bloc `comptes` suit la condition des relevés de la machine (releves_machine)."""
    monkeypatch.setattr(etat_mod, "relever", lambda: {"releve_le": "2026-10-06T00:00:00+00:00", "outils": {
        "Claude Code": {"modele_par_defaut": {"valeur": None}}, "Codex": {"modele_par_defaut": {"valeur": None},
                                                                        "profils": {"elements": []}}},
        "mcp_claude_code": {}, "instructions_globales": []})
    monkeypatch.setattr(etat_mod.organisation, "ecrire_releve", lambda racine: None)
    for contenu, attendu in ((None, False), ("releves_machine: true\n", True)):
        racine = tmp_path / str(attendu)
        racine.mkdir()
        if contenu:
            ecrire(racine, contenu)
        (racine / "rapports").mkdir()
        (racine / "rapports" / "usage.json").write_text('{"releve_le": "2026-10-08T09:00:00Z", "claude": {"semaine": {"pct": 9}}}')
        etat_mod.main(["--racine", str(racine)])
        e = json.loads((racine / "docs" / "data" / "etat.json").read_text(encoding="utf-8"))
        assert ("comptes" in e) is attendu
        if attendu:
            assert e["comptes"]["statut"] == "ok" and e["comptes"]["quotas"]["claude_semaine"]["pct"] == 9
