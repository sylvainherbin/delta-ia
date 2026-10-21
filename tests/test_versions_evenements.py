"""Contrat du producteur Bureau : changements réels, append-only, panne tolérée."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
import versions
from deltalib import versions_evenements as journal
from deltalib.kb import fiches_modeles as fm


def chemin_journal(racine):
    return racine / "rapports/versions-evenements.jsonl"


def lire_evenements(racine):
    return [json.loads(l) for l in chemin_journal(racine).read_text().splitlines()]


def verifier_evenement(evenement, cle, nom, avant, apres):
    assert set(evenement) == {"id", "ts", "type", cle, "avant", "apres"}
    assert evenement["type"] == "version_changee"
    assert evenement[cle] == nom
    assert evenement["avant"] == avant and evenement["apres"] == apres
    assert datetime.fromisoformat(evenement["ts"]).utcoffset() is not None
    contenu = {k: v for k, v in evenement.items() if k != "id"}
    assert evenement["id"] == hashlib.sha256(
        json.dumps(contenu, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def relever(racine, monkeypatch, version, *, dry_run=False):
    monkeypatch.setattr(versions, "detecter", lambda _: [{
        "outil": "Outil témoin", "version": version, "derniere_publiee": None,
        "statut": "inconnu", "methode": "simulée"}])
    return versions.main(["--racine", str(racine), *(["--dry-run"] if dry_run else [])])


@pytest.mark.parametrize("avant,apres", [("1", "1"), ("1", None), (None, "1")])
def test_outil_sans_changement_connu(tmp_path, monkeypatch, avant, apres):
    assert relever(tmp_path, monkeypatch, avant) == 0
    assert chemin_journal(tmp_path).read_bytes() == b""
    assert relever(tmp_path, monkeypatch, apres) == 0
    assert lire_evenements(tmp_path) == []


def test_outil_nouveau_et_dry_run(tmp_path, monkeypatch):
    assert relever(tmp_path, monkeypatch, "1", dry_run=True) == 0
    assert not list(tmp_path.iterdir())
    chemin = tmp_path / "docs/data/versions.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text("[]")
    relever(tmp_path, monkeypatch, "1")
    assert chemin_journal(tmp_path).read_bytes() == b""
    relever(tmp_path, monkeypatch, "2", dry_run=True)
    assert json.loads(chemin.read_text())[0]["version"] == "1"
    assert lire_evenements(tmp_path) == []


def test_outils_deux_changements_conservent_les_octets(tmp_path, monkeypatch):
    relever(tmp_path, monkeypatch, "1")
    relever(tmp_path, monkeypatch, "2")
    chemin = chemin_journal(tmp_path)
    debut, inode = chemin.read_bytes(), chemin.stat().st_ino
    verifier_evenement(lire_evenements(tmp_path)[0], "outil", "Outil témoin", "1", "2")
    relever(tmp_path, monkeypatch, "3")
    assert chemin.read_bytes().startswith(debut) and chemin.stat().st_ino == inode
    evenements = lire_evenements(tmp_path)
    assert len(evenements) == 2 and evenements[0]["id"] != evenements[1]["id"]
    verifier_evenement(evenements[1], "outil", "Outil témoin", "2", "3")


def test_modeles_initialisation_ajout_et_efforts(tmp_path, monkeypatch):
    doc = {"schema_version": 2, "modeles": {"modele-a": {}}, "entrees": []}
    monkeypatch.setattr(fm, "construire_modeles", lambda _: doc)
    fm.ecrire_modeles(tmp_path)
    assert chemin_journal(tmp_path).read_bytes() == b""
    doc["entrees"].append({"modele": "modele-a", "effort": "high"})
    fm.ecrire_modeles(tmp_path)
    assert lire_evenements(tmp_path) == []
    doc["modeles"]["modele-b"] = {}
    doc["entrees"].extend([{"modele": "modele-b", "effort": e} for e in ["low", "high"]])
    fm.ecrire_modeles(tmp_path)
    evenements = lire_evenements(tmp_path)
    assert len(evenements) == 1
    verifier_evenement(evenements[0], "modele", "modele-b", None, "modele-b")
    debut = chemin_journal(tmp_path).read_bytes()
    fm.ecrire_modeles(tmp_path)
    assert chemin_journal(tmp_path).read_bytes() == debut
    doc["modeles"]["modele-c"] = {}
    fm.ecrire_modeles(tmp_path)
    assert chemin_journal(tmp_path).read_bytes().startswith(debut)
    assert len(lire_evenements(tmp_path)) == 2


def test_modeles_champ_version_si_present(tmp_path, monkeypatch):
    doc = {"schema_version": 2, "modeles": {"modele-a": {"version": "1"}}}
    monkeypatch.setattr(fm, "construire_modeles", lambda _: doc)
    fm.ecrire_modeles(tmp_path)
    doc["modeles"]["modele-a"]["version"] = "2"
    fm.ecrire_modeles(tmp_path)
    doc["modeles"]["modele-a"]["version"] = None
    fm.ecrire_modeles(tmp_path)
    evenements = lire_evenements(tmp_path)
    assert len(evenements) == 1
    verifier_evenement(evenements[0], "modele", "modele-a", "1", "2")


@pytest.mark.parametrize("producteur", ["outils", "modeles"])
def test_journal_en_echec_ne_bloque_pas(tmp_path, monkeypatch, capsys, producteur):
    chemin_journal(tmp_path).mkdir(parents=True)
    if producteur == "outils":
        assert relever(tmp_path, monkeypatch, "1") == 0
        assert relever(tmp_path, monkeypatch, "2") == 0
        assert json.loads((tmp_path / "docs/data/versions.json").read_text())[0]["version"] == "2"
    else:
        doc = {"schema_version": 2, "modeles": {}}
        monkeypatch.setattr(fm, "construire_modeles", lambda _: doc)
        fm.ecrire_modeles(tmp_path)
        doc["modeles"]["modele-a"] = {}
        assert fm.ecrire_modeles(tmp_path) == doc
        assert json.loads(fm.chemin_kb_modeles(tmp_path).read_text()) == doc
    assert "Avertissement" in capsys.readouterr().err


def test_une_ligne_complete_par_write(tmp_path, monkeypatch):
    lignes = []

    class JournalTemoin:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, texte):
            lignes.append(texte)

    def ouvrir(chemin, mode, *, encoding):
        assert chemin == chemin_journal(tmp_path) and mode == "a" and encoding == "utf-8"
        return JournalTemoin()

    monkeypatch.setattr(Path, "open", ouvrir)
    journal.ajouter_evenements(tmp_path, [
        {"outil": "a", "avant": "1", "apres": "2"},
        {"modele": "b", "avant": None, "apres": "b"}])
    assert len(lignes) == 2
    for ligne in lignes:
        assert ligne.endswith("\n") and len(ligne.splitlines()) == 1
        assert json.loads(ligne)["type"] == "version_changee"
