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


def test_rebond_dns_la_connexion_va_a_l_ip_controlee_a_chaque_saut(monkeypatch):
    """Rebond DNS : l'hôte est public au contrôle, 127.0.0.1 à toute résolution suivante. La connexion se fait à l'IP
    contrôlée (Host conservé), au premier saut comme après la redirection ; 127.0.0.1 n'est jamais demandé."""
    import threading
    import urllib3.util.connection as connexion
    from http.server import BaseHTTPRequestHandler, HTTPServer

    hotes = []

    class Gestion(BaseHTTPRequestHandler):
        def do_GET(self):
            hotes.append(self.headers["Host"])
            if self.path == "/debut":
                self.send_response(302)
                self.send_header("Location", f"http://saut.invalid:{port}/fin")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                corps = b"fixture"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

        def log_message(self, *a):
            pass

    serveur = HTTPServer(("127.0.0.1", 0), Gestion)
    port = serveur.server_address[1]
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    publiques = {"debut.invalid": "93.184.216.34", "saut.invalid": "93.184.216.35"}
    vues = []

    def rebond(hote, p, *a, **kw):  # urllib3 appelle getaddrinfo(hôte, port, famille, type) en positionnel
        ip = hote if hote[0].isdigit() else ("127.0.0.1" if hote in vues else publiques[hote])
        vues.append(hote)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))]

    demandees = []
    vraie_connexion = connexion.create_connection

    def connecter(adresse, *a, **k):
        demandees.append(adresse)
        if adresse[0] in publiques.values():  # l'IP publique contrôlée est servie par le serveur local du test
            return vraie_connexion(("127.0.0.1", adresse[1]), *a, **k)
        return vraie_connexion(adresse, *a, **k)  # sans épinglage : hôte résolu de nouveau, donc 127.0.0.1

    monkeypatch.setattr(socket, "getaddrinfo", rebond)
    monkeypatch.setattr(connexion, "create_connection", connecter)
    try:
        source = SimpleNamespace(url=f"http://debut.invalid:{port}/debut", options={})
        rep = Client(dormir=lambda s: None).pour_source(source).get(source.url)
    finally:
        serveur.shutdown()
        serveur.server_close()
    assert demandees == [("93.184.216.34", port), ("93.184.216.35", port)], "connexion à l'IP contrôlée, jamais une résolution neuve"
    assert hotes == [f"debut.invalid:{port}", f"saut.invalid:{port}"], "en-tête Host conservé"
    assert rep.texte == "fixture" and rep.redirections == ((302, f"http://debut.invalid:{port}/debut"),)



def test_repli_sur_les_ip_deja_controlees_sans_nouvelle_resolution(monkeypatch):
    """SUITE 3, point 5 : la première IP contrôlée refuse la connexion, la seconde sert ; une seule résolution, et la
    connexion ne demande que des IP contrôlées (doublon écarté, ordre de la résolution)."""
    import urllib3.util.connection as connexion

    resolutions, demandees = [], []

    def resoudre(h, p, *a, **kw):
        resolutions.append(h)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p)) for ip in ("93.184.216.34", "93.184.216.34", "93.184.216.35")]

    def connecter(adresse, *a, **k):
        demandees.append(adresse)
        if adresse[0] == "93.184.216.34":
            raise ConnectionRefusedError("fixture : première IP fermée")
        raise OSError("fixture : seconde IP atteinte")  # atteinte : le repli a eu lieu ; aucun échange réel

    monkeypatch.setattr(socket, "getaddrinfo", resoudre)
    monkeypatch.setattr(connexion, "create_connection", connecter)
    with pytest.raises(ErreurReseau):
        Client(tentatives=1, dormir=lambda s: None).get("https://hote.invalid/a")
    assert demandees == [("93.184.216.34", 443), ("93.184.216.35", 443)], "repli dans l'ordre, sans doublon"
    assert resolutions == ["hote.invalid"], "une seule résolution par saut"


def test_nom_accentue_controle_et_connecte_en_punycode(monkeypatch):
    """SUITE 3, point 5 : requests passe l'hôte « café.invalid » en punycode à la connexion ; le contrôle résout la même
    forme et l'épingle sous la même clé : la connexion part vers l'IP contrôlée au lieu d'être refusée faute d'épingle."""
    import urllib3.util.connection as connexion

    resolutions, demandees = [], []

    def resoudre(h, p, *a, **kw):
        resolutions.append(h)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", p))]

    def connecter(adresse, *a, **k):
        demandees.append(adresse)
        raise OSError("fixture : IP contrôlée atteinte")

    monkeypatch.setattr(socket, "getaddrinfo", resoudre)
    monkeypatch.setattr(connexion, "create_connection", connecter)
    with pytest.raises(ErreurReseau) as exc:
        Client(tentatives=1, dormir=lambda s: None).get("https://café.invalid/a")
    assert resolutions == ["xn--caf-dma.invalid"] and demandees == [("93.184.216.34", 443)]
    assert "aucune IP contrôlée" not in str(exc.value)

def test_tls_garde_sni_et_certificat_de_l_hote(monkeypatch):
    """HTTPS : socket ouvert vers l'IP contrôlée, SNI et vérification du certificat sur le nom d'hôte."""
    import urllib3.connection as conn
    import urllib3.util.connection as connexion

    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", p))])
    demandees, sni = [], []

    def connecter(adresse, *a, **k):
        demandees.append(adresse)
        return socket.socket()  # jamais connecté : l'enveloppe TLS est interceptée avant tout échange

    def envelopper(*a, **k):
        sni.append((k.get("server_hostname"), k.get("assert_hostname")))
        raise OSError("fixture : pas de TLS")

    monkeypatch.setattr(connexion, "create_connection", connecter)
    monkeypatch.setattr(conn, "_ssl_wrap_socket_and_match_hostname", envelopper)
    with pytest.raises(ErreurReseau):
        Client(tentatives=1, dormir=lambda s: None).get("https://hote.invalid/a")
    assert demandees == [("93.184.216.34", 443)] and sni and sni[0][0] == "hote.invalid"
