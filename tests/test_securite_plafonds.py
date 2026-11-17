"""Bornes atteintes et dépassées, sans réseau ni production partielle."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from deltalib import passage
from deltalib.couches import config, publication
from deltalib.http import Reponse
from deltalib.modeles import Element
from deltalib.sources import Source


def test_lectures_articles_borne_et_depassement():
    source = Source("fixture", "actu", "actu", "html", "https://public.invalid/liste", "ok", options={"lire_articles": "markdown"})
    def elements(n):
        return [Element(str(i), "actu", "Fixture", None, None, f"https://public.invalid/{i}", "résumé", source.id, False) for i in range(n)]
    appels = []
    def obtenir(url, **kw):
        appels.append(url)
        return Reponse(url, 200, "text/markdown", "# Fixture\nCorps synthétique.")
    client = SimpleNamespace(get=obtenir)
    passage.lire_articles(elements(2), [source], client, [], limite=2)
    assert len(appels) == 2
    appels.clear()
    trop = elements(3)
    with pytest.raises(passage.PlafondDepasse, match="PLAFOND_ARTICLES"):
        passage.lire_articles(trop, [source], client, [], limite=2)
    assert appels == [] and all(e.contenu == "résumé" for e in trop)


@pytest.mark.parametrize("depasse", [False, True])
def test_synchro_total_avant_toute_ecriture(tmp_path, monkeypatch, depasse):
    octets_fichier = b"fixture"
    manifest = json.dumps({"fichiers": [{"chemin": "fixture.json", "taille": len(octets_fichier), "sha256": hashlib.sha256(octets_fichier).hexdigest()}]}).encode()
    index = json.dumps({"generation": "g-fixture", "manifest_sha256": hashlib.sha256(manifest).hexdigest(), "publie_le": "2026-11-17T12:00:00Z"}).encode()
    total = len(index) + len(manifest) + len(octets_fichier)
    racines = SimpleNamespace(commun=tmp_path / "commun", commun_actif=tmp_path / "actif.json")
    monkeypatch.setattr(publication.schemas, "valider_publication", lambda _: [])
    monkeypatch.setattr(publication.schemas, "valider_generation", lambda *a: [])
    pointages, poses, appels = [], [], []
    monkeypatch.setattr(publication, "_pointer", lambda *a: pointages.append(a))
    original = publication._poser
    def poser(p, contenu):
        poses.append(p)
        original(p, contenu)
    monkeypatch.setattr(publication, "_poser", poser)
    def obtenir(url, entetes, limite):
        appels.append(url)
        return 200, {}, index if url.endswith("index.json") else manifest if url.endswith("manifest.json") else octets_fichier
    if depasse:
        with pytest.raises(publication.SynchroEchec, match="PLAFOND_SYNCHRO"):
            publication._synchroniser(racines, "https://public.invalid/", {}, obtenir, limite_total=total - 1)
        assert poses == pointages == []
        assert not racines.commun.exists()  # aucune génération, même provisoire, n'est écrite
        assert len(appels) == 2
    else:
        assert publication._synchroniser(racines, "https://public.invalid/", {}, obtenir, limite_total=total)["statut"] == "nouvelle"
        assert len(poses) == 2 and len(pointages) == 1
        assert (racines.commun / "g-fixture/fixture.json").read_bytes() == octets_fichier


@pytest.mark.parametrize("valeur", [0, -1, True, "100"])
def test_limites_invalides_refusees(tmp_path, monkeypatch, valeur):
    conf = json.loads(config.BOOTSTRAP.read_text())
    conf["limites"]["lectures_articles"] = valeur
    fichier = tmp_path / "bootstrap.json"
    fichier.write_text(json.dumps(conf))
    monkeypatch.setattr(config, "BOOTSTRAP", fichier)
    with pytest.raises(config.ConfigInvalide, match="limites"):
        config.charger()


def test_fetch_plafond_arrete_sans_ecriture_du_brut(tmp_path, monkeypatch):
    import fetch
    source = Source("fixture", "actu", "actu", "html", "https://public.invalid/", "ok")
    monkeypatch.setattr(fetch, "charger_sources", lambda _: [source])
    monkeypatch.setattr(fetch, "Client", lambda: SimpleNamespace())
    def depasser(*args, **kw):
        raise passage.PlafondDepasse("PLAFOND_ARTICLES : fixture")
    monkeypatch.setattr(fetch, "executer", depasser)
    args = SimpleNamespace(sources=tmp_path / "sources.yaml", perimetre="actu", depuis=None, dry_run=False)
    assert fetch.commande_recuperer(args, tmp_path) == 6
    assert not (tmp_path / "raw").exists() and not (tmp_path / "state").exists()
    rapports = list((tmp_path / "rapports").glob("*-fetch-plafond.md"))
    assert len(rapports) == 1 and "PLAFOND_ARTICLES" in rapports[0].read_text()
