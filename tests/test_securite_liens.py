"""Les entrées liées sont refusées avant toute lecture de leur cible."""
from pathlib import Path

import pytest
from deltalib.couches.projection import ImportImpossible, lire_entrees
from deltalib.couches.scission import scinder_sources


@pytest.mark.parametrize("lecteur,rel,dossier", [
    (lire_entrees, "docs/data/fixture.json", False),
    (lire_entrees, "docs/data", True),
    (lire_entrees, "docs", True),
    (scinder_sources, "kb-modeles/fixture.yaml", False),
    (scinder_sources, "kb-modeles", True),
    (scinder_sources, "kb-methodes/fixture.md", False),
    (scinder_sources, "kb-methodes", True),
])
def test_lien_externe_refuse_sans_lecture(tmp_path, monkeypatch, capsys, lecteur, rel, dossier):
    depot = tmp_path / "depot"
    depot.mkdir()
    externe = tmp_path / "externe"
    externe.mkdir()
    marqueur = "DONNEE_SYNTHETIQUE_NE_DOIT_PAS_SORTIR"
    cible = externe / "fixture.txt"
    cible.write_text(marqueur)
    lien = depot / rel
    lien.parent.mkdir(parents=True, exist_ok=True)
    lien.symlink_to(externe if dossier else cible, target_is_directory=dossier)
    lectures = []
    for nom in ("read_bytes", "read_text"):
        original = getattr(Path, nom)
        def lire(self, *a, _original=original, **kw):
            lectures.append(self)
            return _original(self, *a, **kw)
        monkeypatch.setattr(Path, nom, lire)
    with pytest.raises((ValueError, ImportImpossible), match="LIEN_SYMBOLIQUE_REFUSE") as err:
        lecteur(depot)
    assert not lectures
    sorties = capsys.readouterr()
    assert marqueur not in str(err.value) + sorties.out + sorties.err


def test_entrees_ordinaires_lues(tmp_path):
    f = tmp_path / "docs/data/fixture.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    assert lire_entrees(tmp_path)[0].octets == b"{}"
    assert scinder_sources(tmp_path) == ({}, {})
