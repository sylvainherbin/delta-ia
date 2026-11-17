"""SSRF : résolution et réponses simulées, aucun accès au réseau."""
import io
import socket
from types import SimpleNamespace

import pytest
import requests
from deltalib.http import Client
from deltalib.modeles import ErreurReseau
from deltalib.analyseurs.html_notes import parser_html_time_liens, parser_resources_liste


@pytest.fixture(autouse=True)
def environnement_sans_jeton(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


class Session:
    def __init__(self, redirection=None):
        self.headers, self.appels = {}, []
        self.redirection = redirection
    def get(self, url, **kwargs):
        self.appels.append((url, kwargs))
        rep = requests.Response()
        rep.status_code = 302 if len(self.appels) == 1 and self.redirection else 200
        rep.url, rep.raw, rep.encoding = url, io.BytesIO(b"fixture"), "utf-8"
        if rep.status_code == 302:
            rep.headers["Location"] = self.redirection
        return rep


def resolution(hote, port, **kw):
    ip = {"prive.invalid": "10.1.2.3", "mixte.invalid": "10.1.2.3"}.get(hote, hote if hote[0].isdigit() or ":" in hote else "93.184.216.34")
    reponses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    if hote == "mixte.invalid":
        reponses.insert(0, (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)))
    return reponses


@pytest.mark.parametrize("cible", ["https://127.0.0.1/a", "https://10.1.2.3/a", "https://169.254.1.2/a", "file:///fixture", "https://[::1]/a", "https://prive.invalid/a", "https://mixte.invalid/a", "http://public.invalid/a"])
def test_redirection_refusee_avant_la_requete(monkeypatch, cible):
    monkeypatch.setattr(socket, "getaddrinfo", resolution)
    session = Session(cible)
    with pytest.raises(ErreurReseau, match="DESTINATION_REFUSEE"):
        Client(session=session).get("https://public.invalid/debut")
    assert len(session.appels) == 1
    assert session.appels[0][1]["allow_redirects"] is False


def test_redirection_publique_et_http_declare(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", resolution)
    session = Session("https://autre.invalid/fin")
    rep = Client(session=session).get("https://public.invalid/debut")
    assert rep.texte == "fixture" and rep.redirections == ((302, "https://public.invalid/debut"),)
    source = SimpleNamespace(url="http://public.invalid/liste", options={})
    assert Client(session=Session()).pour_source(source).get(source.url).statut == 200
    with pytest.raises(ErreurReseau, match="DESTINATION_REFUSEE"):
        Client(session=Session()).get(source.url)


@pytest.mark.parametrize("parseur", [parser_html_time_liens, parser_resources_liste])
def test_liens_articles_filtrent_hote_et_schema(parseur):
    source = SimpleNamespace(url="https://public.invalid/resources/articles", options={}, id="fixture", produit="actu", officielle=False)
    def carte(url, titre):
        return f'<a class="ResourceCard" href="{url}"><h2>{titre}</h2><time datetime="2026-11-17">Nov 17, 2026</time><span class="meta">Nov 17, 2026</span></a>'
    html = carte("/resources/articles/bon", "Bon") + carte("https://interdit.invalid/resources/articles/non", "Interdit") + carte("http://public.invalid/resources/articles/non", "HTTP")
    res = parseur(html, source)
    elements = res[0] if isinstance(res, tuple) else res
    assert [e.titre for e in elements] == ["Bon"]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "0.0.0.0", "::1", "fc00::1", "fe80::1", "224.0.0.1", "192.0.2.1"])
def test_destination_initiale_non_routable_refusee(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))])
    session = Session()
    with pytest.raises(ErreurReseau, match="DESTINATION_REFUSEE"):
        Client(session=session).get("https://public.invalid/a")
    assert session.appels == []
