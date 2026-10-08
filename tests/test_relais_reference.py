"""m-944fab565b10 : bouton « Envoyer à Delta » de l'onglet Référence et relais local vers la porte des idées."""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import relais_reference as rr

RACINE = Path(__file__).resolve().parent.parent
APP = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")

ENTREE = {
    "id": "claude-code-commandes-add-dir", "produit": "claude-code", "categorie": "commandes", "nom": "/add-dir",
    "description": "Ajoute un répertoire de travail.", "description_source": "Add a working directory.", "commentee": True,
    "usage": "/add-dir <path>", "usage_nature": "syntaxe",
    "recommandation": {"verdict": "tester", "pourquoi": "Accès aux missions sans relancer la session."},
    "sources": [{"url": "https://code.claude.com/docs/en/commands", "libelle": "commands", "officielle": True}],
}


def test_texte_idee_dit_la_reference_et_la_question():
    t = rr.texte_idee(ENTREE)
    assert t.startswith("idée : intégrer la référence Delta-IA « /add-dir » (Claude Code, commande, id claude-code-commandes-add-dir) ")
    assert "dans quel workflow ou chez quel agent" in t
    for morceau in ("Ce qu'elle fait : Ajoute un répertoire de travail.", "Syntaxe : /add-dir <path>",
                    "Avis de Delta-IA : tester, Accès aux missions", "Source : https://code.claude.com/docs/en/commands"):
        assert morceau in t
    assert "\n" not in t


def test_texte_idee_entree_en_attente_et_longue():
    e = dict(ENTREE, commentee=False, recommandation=None, usage_nature="etapes", description_source="x " * 5000, sources=[])
    t = rr.texte_idee(e)
    # description d'origine (anglais) coupée à 900 caractères ; l'accès suit ; ni avis ni source
    assert "Ce qu'elle fait : x x" in t and "x… Accès : /add-dir <path>" in t
    assert len(t) <= rr.IDEE_MAX and "Avis de Delta-IA" not in t and "Source :" not in t


def test_origines_admises():
    assert rr.origine_admise("https://sylvainherbin.github.io")
    assert rr.origine_admise("http://localhost:8000") and rr.origine_admise("http://127.0.0.1")
    for o in (None, "", "null", "https://exemple.com", "https://sylvainherbin.github.io.exemple.com", "http://localhost.exemple.com",
              "https://localhost:8000"):
        assert not rr.origine_admise(o), o


def test_trouver_dans_la_base_publiee():
    kb = RACINE / "docs" / "data" / "kb"
    e = json.loads(next(iter(sorted(kb.glob("*/*.json")))).read_text(encoding="utf-8"))["entrees"][0]
    assert rr.trouver(kb, e["id"])["id"] == e["id"]
    assert rr.trouver(kb, "inexistante-xyz") is None


@pytest.fixture
def relais(tmp_path):
    kb = tmp_path / "kb" / "claude"
    kb.mkdir(parents=True)
    (kb / "commandes.json").write_text(json.dumps({"entrees": [ENTREE]}), encoding="utf-8")
    recu = tmp_path / "recu.txt"
    idee = tmp_path / "idee.py"
    idee.write_text("import json, sys\n"
                    f"open({str(recu)!r}, 'w', encoding='utf-8').write(sys.stdin.read())\n"
                    "print(json.dumps({'ok': True, 'etape': 'envoyee', 'detail': 'Delta réfléchit à l’idée'}))\n", encoding="utf-8")

    class R(rr.Relais):
        pass
    R.kb, R.idee, R.journal = tmp_path / "kb", idee, tmp_path / "envois.jsonl"
    R.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), R)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}", "recu": recu, "R": R, "tmp": tmp_path}
    srv.shutdown()


def appel(url, methode="GET", corps=None, origine="https://sylvainherbin.github.io"):
    h = {"Content-Type": "application/json"}
    if origine:
        h["Origin"] = origine
    req = urllib.request.Request(url, data=None if corps is None else json.dumps(corps).encode(), method=methode, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            b = r.read()
            return r.status, dict(r.headers), json.loads(b) if b else None
    except urllib.error.HTTPError as err:
        b = err.read()
        return err.code, dict(err.headers), json.loads(b) if b else None


def test_envoi_remet_l_idee_et_journalise(relais):
    code, h, r = appel(relais["url"] + "/reference", "POST", {"id": ENTREE["id"], "nom": "texte de la page ignoré"})
    assert code == 200 and r == {"ok": True, "etape": "envoyee", "detail": "Delta réfléchit à l’idée"}
    assert h["Access-Control-Allow-Origin"] == "https://sylvainherbin.github.io"
    assert relais["recu"].read_text(encoding="utf-8") == rr.texte_idee(ENTREE) + "\n"
    ligne = json.loads((relais["tmp"] / "envois.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["id"] == ENTREE["id"] and ligne["ok"] is True and ligne["etape"] == "envoyee"


def test_preflight_et_etat(relais):
    code, h, _ = appel(relais["url"] + "/reference", "OPTIONS")
    assert code == 204 and h["Access-Control-Allow-Private-Network"] == "true" and "POST" in h["Access-Control-Allow-Methods"]
    assert appel(relais["url"] + "/reference", "OPTIONS", origine="https://exemple.com")[0] == 403
    code, _, r = appel(relais["url"] + "/etat")
    assert code == 200 and r["ok"] is True


def test_refus_sans_rien_remettre(relais):
    u = relais["url"] + "/reference"
    assert appel(u, "POST", {"id": ENTREE["id"]}, origine="https://exemple.com")[:1] == (403,)
    assert appel(u, "POST", {"id": ENTREE["id"]}, origine=None)[0] == 403
    assert appel(u, "POST", {"id": "inconnue"})[2]["etape"] == "reference"
    assert appel(u, "POST", {"pas": "d'id"})[0] == 400
    assert appel(relais["url"] + "/ailleurs", "POST", {"id": ENTREE["id"]})[0] == 404
    assert not relais["recu"].exists()


def test_porte_des_idees_absente(relais):
    relais["R"].idee = relais["tmp"] / "absent.py"
    code, _, r = appel(relais["url"] + "/reference", "POST", {"id": ENTREE["id"]})
    assert code == 502 and r["ok"] is False and r["etape"] == "outils"


def test_bouton_de_la_carte_reference():
    carte = APP[APP.index("function carteKb"):APP.index("function badgeContexte")]
    assert "c.append(blocEnvoi(e));" in carte
    corps = APP[APP.index("const RELAIS"):APP.index("function badgeContexte")]
    assert f'const RELAIS = "http://127.0.0.1:{rr.PORT}";' in corps
    # seul l'id part au relais ; l'entrée est relue dans la base locale
    assert "body: JSON.stringify({ id: e.id })" in corps
    # relais injoignable : idée copiée pour le lanceur ; refus du relais : motif affiché
    assert "navigator.clipboard.writeText(texteIdeeKb(e))" in corps and "Delta n'a pas pris la référence" in corps
    # le message de repli précède la copie, qui ne peut pas rester en attente ; à défaut, un bouton « Copier l'idée »
    repli = corps[corps.index("// relais injoignable (téléphone"):]
    assert repli.index("statut.textContent") < repli.index("copierIdeeKb(e)") and "Promise.race" in corps and "Copier l'idée" in repli
    assert "localStorage" in corps and corps.count("try {") >= 3 and "innerHTML" not in corps
    css = (RACINE / "docs" / "assets" / "style.css").read_text(encoding="utf-8")
    assert "button.envoi-delta" in css and ".envoi-statut" in css


def test_meme_phrase_d_ouverture_site_et_relais():
    js = re.search(r"return `idée : intégrer la référence Delta-IA « \$\{[^}]+\} » \(\$\{[^}]+\}, \$\{cat\}, id \$\{e\.id\}\) ` \+\n\s+\"([^\"]+)\"", APP)
    assert js, "phrase d'ouverture introuvable dans app.js"
    assert js.group(1) in rr.texte_idee(ENTREE)
