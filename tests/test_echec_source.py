"""Une source en échec ne bloque pas les autres et figure dans sources_en_echec. Robustesse du client HTTP."""

import io
import json

import pytest
import requests

import fetch
from conftest import FauxClient
from deltalib.http import Client
from deltalib.modeles import ErreurReseau
from deltalib.passage import recuperer
from deltalib.sources import sources_du_perimetre


def actives(sources, perimetre):
    return sources_du_perimetre(list(sources.values()), perimetre)


def test_source_en_panne_reseau_n_arrete_pas_les_autres(sources):
    s = actives(sources, "claude")
    url_apps = sources["claude-apps-notes"].url
    elements, echecs, traitees, _ = recuperer(s, FauxClient({url_apps: ErreurReseau("HTTP 403 pour " + url_apps)}))
    durs = [e for e in echecs if not e.partiel]
    assert [e.id for e in durs] == ["claude-apps-notes"]
    assert durs[0].url == url_apps and "403" in durs[0].erreur
    assert set(traitees) == {x.id for x in s} - {"claude-apps-notes"}
    assert any(e.source_id == "claude-code-changelog" for e in elements)


def test_format_inattendu_est_une_erreur_explicite_jamais_un_vide(sources):
    """Une réponse 200 au mauvais format doit être signalée, pas prise pour « rien de nouveau »."""
    s = actives(sources, "openai")
    url = sources["openai-changelog-general"].url
    elements, echecs, traitees, _ = recuperer(s, FauxClient({url: ('{"feeds": [{"id": "general"}]}', "application/json")}))
    durs = [e for e in echecs if not e.partiel]
    assert [e.id for e in durs] == ["openai-changelog-general"]
    assert durs[0].erreur.startswith("FormatInattendu:")
    assert "openai-changelog-general" not in traitees and elements


def test_echec_partiel_dates(sources):
    s = actives(sources, "claude")
    url_api = sources["claude-code-changelog"].options["releases_url"]
    elements, echecs, traitees, _ = recuperer(s, FauxClient({url_api: ErreurReseau("HTTP 500")}))
    assert ("claude-code-changelog", "dates indisponibles, API releases en échec : HTTP 500") in [(e.id, e.erreur) for e in echecs]
    assert "claude-code-changelog" in traitees  # la source a livré ses éléments, sans dates


def test_erreur_interne_d_un_analyseur_est_capturee(sources, monkeypatch):
    from deltalib import passage
    def casse(source, client):
        raise KeyError("bogue")
    monkeypatch.setitem(passage.ANALYSEURS, "rss", casse)
    s = actives(sources, "actu")
    elements, echecs, traitees, _ = recuperer(s, FauxClient())
    assert len(echecs) == len(s) and all("erreur interne" in e.erreur for e in echecs) and elements == []


def test_cli_signale_les_echecs_et_continue(tmp_path, monkeypatch, date_figee, sources, capsys):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    url = sources["anthropic-newsroom"].url
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient({url: ErreurReseau("délai dépassé")}))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "claude"]) == 0
    brut = json.loads((tmp_path / "raw" / "claude-nouveautes.json").read_text())
    durs = [e for e in brut["sources_en_echec"] if not e["partiel"]]
    assert durs == [{"id": "anthropic-newsroom", "url": url, "erreur": "ErreurReseau: délai dépassé", "partiel": False}]
    assert brut["nouveautes"]
    assert "ÉCHEC" in capsys.readouterr().out


def test_cli_toutes_les_sources_en_echec_code_3(tmp_path, monkeypatch, date_figee, sources):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    pannes = {s.url: ErreurReseau("panne") for s in sources.values()}
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient(pannes))
    assert fetch.main(["--racine", str(tmp_path), "--perimetre", "actu"]) == 3
    brut = json.loads((tmp_path / "raw" / "actu-nouveautes.json").read_text())
    assert brut["nouveautes"] == [] and len(brut["sources_en_echec"]) == 4


# --- client HTTP -------------------------------------------------------------------------------------------

class FausseSession:
    def __init__(self, scenario):
        self.scenario = list(scenario)
        self.headers = {}
        self.appels = []

    def get(self, url, headers=None, timeout=None, allow_redirects=True, stream=False):
        self.appels.append((url, headers, timeout))
        etape = self.scenario.pop(0)
        if isinstance(etape, Exception):
            raise etape
        corps = b"ok"
        if isinstance(etape, tuple):
            etape, corps = etape
        r = requests.Response()
        r.status_code = etape
        r.raw = io.BytesIO(corps)  # lu en flux par le client
        r.url = url
        r.encoding = "utf-8"
        r.headers["Content-Type"] = "text/plain"
        return r


def client_avec(scenario):
    return Client(session=FausseSession(scenario), dormir=lambda s: None)


def test_client_reessaie_apres_erreur_reseau():
    c = client_avec([requests.ConnectionError("coupure"), requests.Timeout("lent"), 200])
    r = c.get("https://exemple.test/a")
    assert r.statut == 200 and r.texte == "ok" and len(c.session.appels) == 3
    assert c.session.appels[0][2] == (10, 30)
    assert c.session.headers["User-Agent"].startswith("Delta-veille/")


def test_client_abandonne_apres_trois_tentatives():
    c = client_avec([500, 502, 503])
    with pytest.raises(ErreurReseau, match="HTTP 503"):
        c.get("https://exemple.test/a")
    assert len(c.session.appels) == 3


def test_client_ne_reessaie_pas_un_refus_definitif():
    c = client_avec([403])
    with pytest.raises(ErreurReseau, match="HTTP 403"):
        c.get("https://help.openai.com/x")
    assert len(c.session.appels) == 1


def test_client_jeton_github_uniquement_pour_l_api(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "jeton-de-test")
    c = client_avec([200, 200])
    c.get("https://api.github.com/repos/x/y/releases")
    c.get("https://raw.githubusercontent.com/x/y/CHANGELOG.md")
    assert c.session.appels[0][1]["Authorization"] == "Bearer jeton-de-test"
    assert "Authorization" not in c.session.appels[1][1]


def test_client_coupe_une_reponse_trop_volumineuse(monkeypatch):
    from deltalib import http
    monkeypatch.setattr(http, "TAILLE_MAX", 1000)
    c = client_avec([(200, b"x" * 5000)])
    with pytest.raises(ErreurReseau, match="trop volumineuse"):
        c.get("https://exemple.test/gros")
    assert len(c.session.appels) == 1  # pas de nouvelle tentative : ce n'est pas une panne passagère
