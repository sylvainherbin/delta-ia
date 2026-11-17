"""Requêtes HTTP de la page publique, rejouées sans socket ni service réel."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import relais_reference as rr


class Connexion:
    def __init__(self, requete):
        self.entree = io.BytesIO(requete)
        self.sortie = bytearray()
    def makefile(self, *args):
        return self.entree
    def sendall(self, donnees):
        self.sortie.extend(donnees)


@pytest.fixture
def requete(tmp_path, monkeypatch):
    kb = tmp_path / "kb/fixture"
    kb.mkdir(parents=True)
    (kb / "commandes.json").write_text(json.dumps({"entrees": [{"id": "fiche", "nom": "Fixture"}]}))
    remis = []
    monkeypatch.setattr(rr, "remettre", lambda *args: remis.append(args) or {"ok": True})
    class R(rr.Relais):
        log_message = lambda *args: None
    R.kb = kb.parent
    R.journal = tmp_path / "journal.jsonl"
    R.limiteur, R.deja = rr.Limiteur(), rr.DejaEnvoyees()
    R.suivi = SimpleNamespace(lire_ou_lancer=lambda: {"ok": True, "fiches": {"fixture": {}}})
    def appeler(methode, chemin, origine, corps=b"", entetes=()):
        lignes = [f"{methode} {chemin} HTTP/1.1", f"Host: 127.0.0.1:{rr.PORT}", "Connection: close"]
        if origine is not None:
            lignes.append(f"Origin: {origine}")
        lignes.extend(entetes)
        if corps:
            lignes += ["Content-Type: application/json", f"Content-Length: {len(corps)}"]
        connexion = Connexion(("\r\n".join(lignes) + "\r\n\r\n").encode() + corps)
        R(connexion, ("127.0.0.1", 12345), SimpleNamespace(server_address=("127.0.0.1", rr.PORT)))
        return bytes(connexion.sortie).decode()
    return appeler, remis


@pytest.mark.parametrize("origine", [None, "https://ai.orqyra.io", "http://localhost:8000", "http://127.0.0.1:9000", "https://fixture.invalid"])
@pytest.mark.parametrize("methode", ["GET", "OPTIONS"])
def test_suivi_sans_cors(requete, origine, methode):
    reponse = requete[0](methode, "/suivi", origine)
    assert "Access-Control-Allow-" not in reponse


@pytest.mark.parametrize("origine", ["http://localhost:8000", "http://127.0.0.1", "http://127.0.0.1:9000", "https://sylvainherbin.github.io"])
def test_origine_arbitraire_refusee(requete, origine):
    reponse = requete[0]("POST", "/reference", origine, b'{"id":"fiche"}')
    assert " 403 " in reponse and not requete[1]
    assert "Access-Control-Allow-Origin" not in reponse


def test_flux_reference_de_la_page_actu(requete):
    # Actu charge widgets.js ; le même app.js porte le bouton Référence.
    app = (Path(__file__).resolve().parents[1] / "docs/assets/app.js").read_text()
    assert 'fetch(`${RELAIS}/etat`' in app and 'fetch(`${RELAIS}/reference`' in app
    assert 'body: JSON.stringify({ id: e.id })' in app
    appeler, remis = requete
    for methode, chemin, corps in (("GET", "/etat", b""), ("OPTIONS", "/reference", b""),
                                   ("POST", "/reference", b'{"id":"fiche"}')):
        reponse = appeler(methode, chemin, "https://ai.orqyra.io", corps,
                           ("Access-Control-Request-Method: POST", "Access-Control-Request-Headers: content-type"))
        assert " 200 " in reponse or " 204 " in reponse
        assert "Access-Control-Allow-Origin: https://ai.orqyra.io" in reponse
    assert len(remis) == 1
