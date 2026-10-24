"""m-944fab565b10 : bouton « Envoyer à Delta » de l'onglet Référence et relais local vers la porte des idées."""

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import relais_reference as rr
from textes_site import FR, t_js

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
    assert rr.origine_admise("https://ai.orqyra.io") and rr.origine_admise("https://sylvainherbin.github.io")
    assert rr.origine_admise("http://localhost:8000") and rr.origine_admise("http://127.0.0.1")
    for o in (None, "", "null", "https://exemple.com", "https://sylvainherbin.github.io.exemple.com", "https://ai.orqyra.io.exemple.com", "http://ai.orqyra.io", "http://localhost.exemple.com",
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
    R.limiteur = rr.Limiteur(R.journal)
    R.deja = rr.DejaEnvoyees(R.journal)
    R.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), R)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}", "recu": recu, "R": R, "tmp": tmp_path}
    srv.shutdown()


def appel(url, methode="GET", corps=None, origine="https://ai.orqyra.io"):
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
    assert h["Access-Control-Allow-Origin"] == "https://ai.orqyra.io"
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
    # relais injoignable : console si une adresse est enregistrée, sinon idée copiée pour le lanceur ; refus du relais : motif affiché
    assert "navigator.clipboard.writeText(texteIdeeKb(e))" in corps and 't("envoi.refus"' in corps
    assert "Delta n'a pas pris la référence" in FR["envoi.refus"]
    # le message de repli précède la copie, qui ne peut pas rester en attente ; à défaut, un bouton « Copier l'idée »
    repli = corps[corps.index("async function repli("):corps.index("// le presse-papier")]
    assert repli.index("statut.textContent = motif") < repli.index("copierIdeeKb(e)") and 't("envoi.copier")' in repli and FR["envoi.copier"] == "Copier l'idée"
    assert "Promise.race" in corps and "return repli(e, statut," in corps
    assert "localStorage" in corps and corps.count("try {") >= 3 and "innerHTML" not in corps
    css = (RACINE / "docs" / "assets" / "style.css").read_text(encoding="utf-8")
    assert "button.envoi-delta" in css and ".envoi-statut" in css


def test_meme_phrase_d_ouverture_site_et_relais():
    js = re.search(r"return `idée : intégrer la référence Delta-IA « \$\{[^}]+\} » \(\$\{[^}]+\}, \$\{cat\}, id \$\{e\.id\}\) ` \+\n\s+\"([^\"]+)\"", APP)
    assert js, "phrase d'ouverture introuvable dans app.js"
    assert js.group(1) in rr.texte_idee(ENTREE)


# ---- m-ece2645167da (D104) : plafond, délai de 3 s, iPhone/iPad, adresse de console ----

def test_plafond_de_dix_envois_par_heure(relais):
    u = relais["url"] + "/reference"
    entrees = [dict(ENTREE, id=f"{ENTREE['id']}-{i}") for i in range(rr.PLAFOND + 1)]
    (relais["tmp"] / "kb" / "claude" / "commandes.json").write_text(json.dumps({"entrees": entrees}), encoding="utf-8")
    for e in entrees[:rr.PLAFOND]:
        assert appel(u, "POST", {"id": e["id"]})[0] == 200
    relais["recu"].unlink()
    code, h, r = appel(u, "POST", {"id": entrees[-1]["id"]})
    assert code == 429 and r["ok"] is False and r["etape"] == "plafond"
    assert "10 envois par heure" in r["detail"] and "min" in r["detail"]
    assert 1 <= int(h["Retry-After"]) <= rr.FENETRE + 1 and h["Access-Control-Allow-Origin"] == "https://ai.orqyra.io"
    assert not relais["recu"].exists()                      # rien n'est remis à la porte des idées
    assert len((relais["tmp"] / "envois.jsonl").read_text(encoding="utf-8").splitlines()) == rr.PLAFOND
    # les requêtes refusées en amont ne consomment pas le plafond ; la fiche refusée au plafond reste envoyable ensuite
    assert appel(u, "POST", {"id": "inconnue"})[0] == 404
    assert entrees[-1]["id"] not in relais["R"].deja.vues


def test_limiteur_fenetre_glissante():
    t = [1000.0]
    lim = rr.Limiteur(maxi=3, fenetre=100, horloge=lambda: t[0])
    for _ in range(3):
        assert lim.reserver() == (True, 0)
        t[0] += 10
    ok, attente = lim.reserver()                             # envois à 1000, 1010, 1020 ; on est à 1030
    assert not ok and 70 <= attente <= 72
    t[0] = 1101.0                                            # le premier (1000) est sorti de la fenêtre
    assert lim.reserver() == (True, 0) and not lim.reserver()[0]


def test_limiteur_relit_le_journal_au_demarrage(tmp_path):
    journal = tmp_path / "envois.jsonl"
    maintenant = rr.time.time()
    def ligne(dt, ok=True):
        return json.dumps({"date": rr.time.strftime("%Y-%m-%dT%H:%M:%S%z", rr.time.localtime(maintenant - dt)), "id": "x", "ok": ok})
    journal.write_text("\n".join([ligne(7200), ligne(3000), ligne(60, False), "pas du json", json.dumps({"id": "sans date"}), ligne(5)]) + "\n",
                       encoding="utf-8")
    lim = rr.Limiteur(journal)
    assert len(lim.envois) == 3                              # l'envoi de deux heures est hors fenêtre, les lignes illisibles sont ignorées
    assert rr.Limiteur(tmp_path / "absent.jsonl").envois == type(lim.envois)()
    for _ in range(rr.PLAFOND - 3):
        assert lim.reserver()[0]
    assert not lim.reserver()[0]


def test_delai_de_trois_secondes_au_blocage():
    corps = APP[APP.index("async function relaisJoignable"):APP.index("async function repli(")]
    # le blocage (Brave, Chrome) ou un relais arrêté est jugé sur GET /etat en 3 s ; l'envoi garde son délai propre, sans doublon
    assert "/etat" in corps and "AbortSignal.timeout(3000)" in corps
    assert corps.index("await relaisJoignable()") < corps.index('/reference')
    assert "AbortSignal.timeout(25000)" in corps


def test_ios_ipados_et_console_dans_le_navigateur():
    assert "/iPhone|iPad|iPod/.test(ua)" in APP and 'navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1' in APP
    envoi = APP[APP.index("async function envoyerADelta"):APP.index("async function repli(")]
    assert envoi.index("estIos()") < envoi.index("relaisJoignable()")      # sur iPhone/iPad, le relais n'est même pas tenté
    repli = APP[APP.index("async function repli("):APP.index("// le presse-papier")]
    assert "urlConsole(adresse, e)" in repli and repli.index("lireConsole()") < repli.index("copierIdeeKb(e)")
    assert "`${adresse}/#idee=${encodeURIComponent(coupe(texteIdeeKb(e), IDEE_CONSOLE_MAX))}`" in APP and "IDEE_CONSOLE_MAX = 500" in APP
    # fragment #console=<adresse> : validé, enregistré sous try/catch, retiré de l'URL, lu avant le premier rendu
    fonction = APP[APP.index("function enregistrerConsoleDepuisUrl"):APP.index("function annoncer")]
    assert 'startsWith("#console=")' in fonction and "history.replaceState" in fonction and "localStorage.setItem(CLE_CONSOLE" in fonction
    assert fonction.index("history.replaceState") < fonction.index("adresseConsole(brut)")
    assert APP.index("enregistrerConsoleDepuisUrl();") < APP.index("await chargerIndex();")
    schema = APP[APP.index("function adresseConsole"):APP.index("function lireConsole")]
    for morceau in ('"https:"', '"http:"', "100", ">= 64", "<= 127", "ts\\.net"):
        assert morceau in schema, morceau


def test_adresse_de_console_jamais_dans_le_depot():
    # REGLES §5 : ni adresse Tailscale (la plage « 100.64.0.0/10 » citée en commentaire est admise) ni adresse de console dans ce qui est publié ou suivi
    motif = re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b(?!/)|[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b", re.I)
    for chemin in ("docs/assets/app.js", "docs/assets/textes.js", "docs/assets/style.css", "docs/index.html", "docs/fr/index.html", "scripts/relais_reference.py",
                   "deploy/relais/delta-ia-relais.service.exemple"):
        assert not motif.search((RACINE / chemin).read_text(encoding="utf-8")), chemin


# ---- m-fcce5f697e73 (D104, suite B2) : pas de second envoi de la même fiche dans l'heure ----

def test_second_envoi_de_la_meme_fiche_refuse_en_409(relais):
    u = relais["url"] + "/reference"
    avant = rr.time.time()
    assert appel(u, "POST", {"id": ENTREE["id"]})[0] == 200
    relais["recu"].unlink()
    code, h, r = appel(u, "POST", {"id": ENTREE["id"]})
    assert code == 409 and r["ok"] is False and r["etape"] == "deja_envoyee"
    assert re.fullmatch(r"déjà envoyée à \d\d:\d\d", r["detail"]) and r["detail"].endswith(rr.heure(r["envoye_a"]))
    assert avant - 1 <= r["envoye_a"] <= rr.time.time() + 1
    assert h["Access-Control-Allow-Origin"] == "https://ai.orqyra.io"
    assert not relais["recu"].exists()                       # JUGER n'est pas relancé
    assert len((relais["tmp"] / "envois.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert len(relais["R"].limiteur.envois) == 1             # le refus ne consomme pas le plafond


def test_un_echec_n_empeche_pas_le_nouvel_envoi(relais):
    u = relais["url"] + "/reference"
    bonne = relais["R"].idee
    relais["R"].idee = relais["tmp"] / "absent.py"
    assert appel(u, "POST", {"id": ENTREE["id"]})[0] == 502
    relais["R"].idee = bonne
    assert appel(u, "POST", {"id": ENTREE["id"]})[0] == 200  # rien n'est parti : la fiche reste envoyable
    assert appel(u, "POST", {"id": ENTREE["id"]})[0] == 409


def test_deja_envoyees_fenetre_et_reservation():
    t = [1000.0]
    d = rr.DejaEnvoyees(fenetre=100, horloge=lambda: t[0])
    assert d.reserver("a") == (None, 1000.0)
    t[0] = 1050.0
    assert d.reserver("a") == (1000.0, None) and d.reserver("b") == (None, 1050.0)
    d.liberer("b", 1050.0)
    assert d.reserver("b")[0] is None                        # envoi échoué : libérée
    t[0] = 1101.0                                            # une heure (ici 100 s) après le premier envoi de « a »
    assert d.reserver("a") == (None, 1101.0)
    d.liberer("a", 1000.0)                                   # libération d'une ancienne réservation : sans effet
    assert d.reserver("a")[0] == 1101.0


def test_deja_envoyees_relues_dans_le_journal_au_demarrage(tmp_path):
    journal = tmp_path / "envois.jsonl"
    maintenant = rr.time.time()
    def ligne(ident, dt, ok=True):
        return json.dumps({"date": rr.time.strftime("%Y-%m-%dT%H:%M:%S%z", rr.time.localtime(maintenant - dt)), "id": ident, "ok": ok})
    journal.write_text("\n".join([ligne("vieille", 7200), ligne("recente", 600), ligne("recente", 60), ligne("echouee", 60, False),
                                   "pas du json", json.dumps({"id": "sans date", "ok": True})]) + "\n", encoding="utf-8")
    d = rr.DejaEnvoyees(journal)
    assert set(d.vues) == {"recente"} and d.vues["recente"] > maintenant - 120   # la plus récente des deux lignes
    assert rr.DejaEnvoyees(tmp_path / "absent.jsonl").vues == {}
    # un redémarrage du relais n'efface pas la règle
    ok, _ = d.reserver("recente")
    assert ok is not None and d.reserver("echouee")[0] is None


def test_carte_confirmation_repli_et_memoire_d_une_heure():
    corps = APP[APP.index("const CLE_HEURES"):APP.index("function badgeContexte")]
    # (2) confirmation, bouton désactivé une heure, mémoire par fiche sous try/catch, second clic sans appel
    assert 'statut.textContent = t("envoi.ok")' in corps and FR["envoi.ok"] == "Envoyé à Delta, jugement en cours"
    assert "HEURE_MS = 3600000" in corps and 'noterHeure("envoi", e.id, t0)' in corps and 'localStorage.setItem(CLE_HEURES' in corps
    memoire = corps[corps.index("function lireHeures"):corps.index("function hhmm")]
    assert memoire.count("try {") == 2 and memoire.count("catch (err)") == 2
    envoi = corps[corps.index("async function envoyerADelta"):corps.index("async function repli(")]
    deja = 't("envoi.deja", { heure: hhmm(dejaT) })'
    assert FR["envoi.deja"] == "déjà envoyée à {heure}"
    assert deja in envoi and envoi.index('heureRecente("envoi", e.id)') < envoi.index("estIos()") < envoi.index("relaisJoignable()")
    assert envoi.index(deja) < envoi.index("relaisJoignable()")   # aucun appel au relais
    assert 'r.etape === "deja_envoyee"' in envoi          # 409 du relais : le bouton se bloque aussi
    # (3) repli : le message exact, puis « copiée à HH:MM » pour l'heure
    assert FR["envoi.pas_joignable"] == ("Pas envoyé : relais non joignable et console non reliée (ouvre la console et touche « Relier Delta-IA » "
                                         "une fois sur cet appareil).")
    assert "brave://settings/content/localhostAccess" not in APP
    assert FR["envoi.copiee"] == "L'idée est copiée : colle-la une fois dans le lanceur." and 't("envoi.copiee")' in corps
    assert 'return repli(e, statut, t("envoi.pas_joignable"), bouton)' in envoi
    repli = corps[corps.index("async function repli("):corps.index("// le presse-papier")]
    assert repli.count('noterHeure("copie", e.id, Date.now())') == 2
    bloc = corps[corps.index("function blocEnvoi"):]
    assert 't("envoi.copiee_a", { heure: hhmm(copie) })' in bloc and 'heureRecente("copie", e.id)' in bloc and 't("envoi.ok_a", { heure: hhmm(envoi) })' in bloc
    assert FR["envoi.copiee_a"].startswith("copiée à {heure}") and FR["envoi.ok_a"] == "Envoyé à Delta à {heure}, jugement en cours"
    assert "bloquerBouton(b, envoi)" in bloc


def test_aide_dit_la_regle_d_une_heure():
    envoi = " ".join(FR[f"aide.envoi.{c}"] for c in ("sert", "geste", "limite"))
    assert '{ id: "envoi" }' in APP
    assert "ne repart pas dans l'heure" in envoi and "Pas envoyé" in envoi and "jugement en cours" in envoi


# ---- m-94f3b7e1274b : exécution du bouton, sans appeler le service installé ----

def trouver_node():
    """Node du PATH, sinon ~/.nvm/current/bin (absent du PATH des sessions et de verrou-tests), jamais un chemin de version."""
    du_path = shutil.which("node")
    if du_path:
        return du_path
    nvm = Path.home() / ".nvm/current/bin/node"
    return str(nvm) if os.access(nvm, os.X_OK) else None


def bouton_execute(**options):
    """Le vrai code du bouton sous Node : réseau, onglets, horloge et presse-papier simulés."""
    node = trouver_node()
    if not node:
        assert not os.environ.get("CI"), "Node est nécessaire aux tests du bouton (présent sur ubuntu-24.04 en CI)"
        pytest.skip("Node introuvable (PATH, ~/.nvm/current/bin/node) : tests du bouton lancés par la CI")
    code = APP[APP.index("const RELAIS"):APP.index("// D64-bis : péremption")]
    script = r"""
const vm = require('node:vm');
const {code, T_JS, options: o} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const appels = [], onglets = [], copies = [], delais = [], liens = [], suivis = [];
const stockage = new Map();
const aplatir = x => typeof x === 'string' ? x : x.tag === 'br' ? '|' : (x.textContent || '') + (x.children || []).map(aplatir).join('');
if (o.console !== false) stockage.set('delta.console', o.console || 'https://console.example');
let maintenant = 1000000000000;
class Horloge extends Date { static now() { return maintenant; } }
function el(tag, props, ...children) {
  return {tag, ...props, textContent: (props || {}).text || '', children, listeners: {},
    addEventListener(type, cb) { this.listeners[type] = cb; }, remove() {}, append(...x) { this.children.push(...x); }};
}
const rubrique = el('section', {hidden: true});
const context = vm.createContext({
  Date: Horloge, URL, el, PRODUITS: {}, enCommun: () => !!o.commun, ISO_JOUR: /^\d{4}-\d{2}-\d{2}$/,
  texte: (s, defaut) => s || defaut, jourLocalIso: () => '2001-09-09', dateAffichee: s => s,
  localStorage: {getItem: k => stockage.get(k), setItem: (k, v) => stockage.set(k, v)},
  navigator: {userAgent: o.ios ? 'iPhone' : '', platform: o.ipad ? 'MacIntel' : '',
    maxTouchPoints: o.ipad ? 5 : 0, clipboard: {writeText: async s => {
      copies.push(s); if (o.copie === false) throw Error('refus');
    }}},
  document: {querySelectorAll: () => [], getElementById: id => (id === 'kb-ameliorations' && o.rubrique ? rubrique : null)},
  etat: {kb: {entrees: o.entrees || []}},
  window: {DELTA_TEXTES: {fr: {}}, open: (url, cible) => {onglets.push({url, cible}); return o.popup === false ? null : {}; }},
  setTimeout: () => {}, AbortSignal: {timeout: ms => {delais.push(ms); return null;}},
  fetch: async (url, opts) => {
    if (url.endsWith('/suivi')) {   // boucle d'adoption : comptée à part, sans relais simulé par défaut
      suivis.push(url);
      if (!o.suivi) throw Error('relais absent');
      return {status: o.suivi.status || 200, json: async () => o.suivi.corps};
    }
    appels.push({url, ...opts});
    if (url.endsWith('/etat')) {if (o.etat === 'erreur') throw Error('réseau'); return {ok: o.etat === true};}
    return {json: async () => o.post || {ok: true}};
  }
});
vm.runInContext(T_JS + code + ';globalThis.api = {envoyerADelta, blocEnvoi, urlConsole, heureRecente, chargerSuivi, remplirAmeliorations};', context);
(async () => {
  const e = {id: 'fiche', nom: o.long ? 'é'.repeat(800) : 'Essai & idée', produit: 'essai'};
  const bouton = el('button', {}), statut = el('span', {});
  statut.after = lien => liens.push(lien);
  await context.api.envoyerADelta(e, bouton, statut);
  const avantLien = {disabled: !!bouton.disabled, envoi: context.api.heureRecente('envoi', e.id)};
  if (o.lien) {
    liens[0].listeners.click({preventDefault() {throw Error('premier lien bloqué');}});
    let bloque = false;
    liens[0].listeners.click({preventDefault() {bloque = true;}});
    if (!bloque) throw Error('second lien non bloqué');
  }
  if (o.copier) await liens[0].listeners.click();
  const premier = statut.textContent;
  const rendu = context.api.blocEnvoi(e);
  const projection = await context.api.chargerSuivi();   // la ligne de suivi se remplit dans le .then posé par blocEnvoi
  if (o.rubrique) context.api.remplirAmeliorations(projection);
  await context.api.envoyerADelta(e, bouton, statut);
  const second = statut.textContent;
  if (o.expire) {maintenant += 3600001; await context.api.envoyerADelta(e, bouton, statut);}
  console.log(JSON.stringify({appels, onglets, copies, delais, avantLien, premier, second,
    disabled: !!bouton.disabled, rendu: rendu.children[1].textContent, suivis,
    suivi: {hidden: rendu.children[2].hidden, texte: rendu.children[2].children.map(x => typeof x === 'string' ? x : x.tag === 'br' ? '|' : x.textContent).join('')},
    rubrique: {hidden: rubrique.hidden, texte: rubrique.children.map(aplatir).join(''),
      liens: rubrique.children.length ? rubrique.children[0].children[2].children.map(li => li.children[0].href) : []},
    liens: liens.map(l => ({tag: l.tag, href: l.href, target: l.target, rel: l.rel}))}));
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    res = subprocess.run([node, "-e", script], input=json.dumps({"code": code, "T_JS": t_js("fr"), "options": options}),
                         text=True, capture_output=True, timeout=10)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_node_de_nvm_current_hors_path(tmp_path, monkeypatch):
    version = tmp_path / ".nvm/versions/node/v24.3.1/bin/node"
    version.parent.mkdir(parents=True); version.write_text("#!/bin/sh\n"); version.chmod(0o755)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(shutil, "which", lambda nom: None)
    assert trouver_node() is None  # une version installée hors du lien current n'est jamais prise
    (tmp_path / ".nvm/current").symlink_to(version.parent.parent)
    assert trouver_node() == str(tmp_path / ".nvm/current/bin/node")
    monkeypatch.setattr(shutil, "which", lambda nom: "/usr/bin/node")
    assert trouver_node() == "/usr/bin/node"


def test_sans_node_skip_en_local_echec_en_ci(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(shutil, "which", lambda nom: None)
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception, match="Node introuvable"):
        bouton_execute()
    monkeypatch.setenv("CI", "true")
    with pytest.raises(AssertionError, match="Node est nécessaire"):
        bouton_execute()


def test_bureau_relais_prioritaire_meme_console_reliee():
    r = bouton_execute(etat=True)
    assert [a["url"].rsplit("/", 1)[-1] for a in r["appels"]] == ["etat", "reference"]
    assert json.loads(r["appels"][1]["body"]) == {"id": "fiche"}
    # après l'envoi réussi, la carte redemande le suivi (5 s au plus) ; relais simulé absent : ligne de suivi cachée
    assert r["delais"] == [3000, 25000, 5000] and not r["onglets"] and not r["copies"]
    assert len(r["suivis"]) == 1 and r["suivi"]["hidden"] is True
    assert r["premier"] == "Envoyé à Delta, jugement en cours" and r["second"].startswith("déjà envoyée à ")


@pytest.mark.parametrize("options", [{}, {"etat": "erreur"}, {"ios": True}, {"ipad": True}])
def test_console_reliee_et_memoire_sur_tous_les_appareils(options):
    r = bouton_execute(**options, long=True)
    assert len(r["appels"]) == (0 if options.get("ios") or options.get("ipad") else 1)
    assert len(r["onglets"]) == 1 and r["onglets"][0]["cible"] == "_blank" and not r["copies"]
    url = r["onglets"][0]["url"]
    assert url.startswith("https://console.example/#idee=")
    assert len(urllib.parse.unquote(url.split("#idee=", 1)[1])) == 500
    assert "%C3%A9" in url
    assert r["disabled"] and r["second"].startswith("déjà envoyée à ")
    assert "valide l'envoi" in r["premier"] and "jugement en cours" not in r["rendu"]
    assert r["rendu"].startswith("déjà envoyée à ")


def test_console_onglet_bloque_memoire_au_geste_seulement():
    r = bouton_execute(popup=False, lien=True)
    assert r["avantLien"] == {"disabled": False, "envoi": None}
    assert r["liens"] == [{"tag": "a", "href": r["onglets"][0]["url"], "target": "_blank", "rel": "noopener"}]
    assert r["disabled"] and r["second"].startswith("déjà envoyée à ") and not r["copies"]


def test_console_redevient_ouvrable_apres_une_heure():
    r = bouton_execute(expire=True)
    assert len(r["onglets"]) == 2 and len(r["appels"]) == 2


@pytest.mark.parametrize("ios", [False, True])
def test_sans_console_copie_et_message_exact(ios):
    r = bouton_execute(console=False, ios=ios)
    assert not r["onglets"] and r["copies"] and not r["disabled"]
    assert r["premier"] == ("Pas envoyé : relais non joignable et console non reliée (ouvre la console et touche « Relier "
                            "Delta-IA » une fois sur cet appareil). L'idée est copiée : colle-la une fois dans le lanceur.")
    assert r["rendu"].startswith("copiée à ")


def test_copie_refusee_reste_possible_par_geste():
    r = bouton_execute(console=False, copie=False)
    assert r["liens"][0]["tag"] == "button" and not r["disabled"]
    assert r["premier"].startswith("Pas envoyé") and "L'idée est copiée" not in r["premier"]


def test_refus_explicite_du_relais_ne_passe_pas_par_console():
    r = bouton_execute(etat=True, post={"ok": False, "etape": "plafond", "detail": "10 envois par heure"})
    assert not r["onglets"] and not r["copies"] and not r["disabled"]
    assert "Delta n'a pas pris la référence (10 envois par heure)" in r["premier"]


# ---- m-a04181983623 : boucle d'adoption, GET /suivi projeté depuis OPÉRER ----

def lire_factice(vues, bloque=None):
    """Remplace `operer --json …` : vues[(arguments)] → dict ; `bloque` (Event) retient le calcul."""
    def lire(*args):
        if bloque is not None:
            bloque.wait(5)
        return vues[args]
    return lire


VUES = {
    ("idees",): {"sujets": [{"verbatim": "idée : intégrer la référence Delta-IA « /add-dir » (Claude Code, commande, id "
                                         "claude-code-commandes-add-dir) dans un workflow", "position": "PERTINENTE",
                             "premier": "2026-10-09T09:00:00+00:00", "missions": [{"id": "m-1", "etat": "CLOSE"}]}]},
    ("mission", "m-1"): {"mission": {"etat": "CLOSE", "issue": "livre", "preuves": {
        "verifie_ts": "2026-10-11T18:04:37+02:00", "sans_installation": False, "fichiers": [{"source": "outils/agents/x.md"}]}}},
    ("essai", "liste"): {"essais": []},
}


def test_suivi_sert_la_projection_a_l_origine_admise(relais):
    R = relais["R"]
    R.suivi = rr.Suivi(R.journal, lire=lire_factice(VUES))
    R.suivi.lancer(attendre=True)
    code, h, r = appel(relais["url"] + "/suivi")
    assert code == 200 and r["ok"] is True and r["etape"] == "suivi" and r["sources_en_echec"] == []
    f = r["fiches"]["claude-code-commandes-add-dir"]
    assert f["etat"] == "installe" and f["installations"][0]["lot"] == "m-1" and f["installations"][0]["le"] == "2026-10-11"
    assert h["Access-Control-Allow-Origin"] == "https://ai.orqyra.io"
    # donnée personnelle : ni origine inconnue, ni requête sans origine, ni autre hôte (rebinding DNS)
    for origine in ("https://exemple.com", None):
        code, h, r = appel(relais["url"] + "/suivi", origine=origine)
        assert code == 403 and "fiches" not in r and "Access-Control-Allow-Origin" not in h
    port = relais["url"].rsplit(":", 1)[1]
    req = urllib.request.Request(relais["url"] + "/suivi", headers={"Origin": "https://ai.orqyra.io", "Host": f"rebind.exemple:{port}"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 403 and "fiches" not in json.loads(err.value.read())


def test_suivi_premier_calcul_503_puis_cache(relais):
    R, feu = relais["R"], threading.Event()
    R.suivi = rr.Suivi(R.journal, lire=lire_factice(VUES, bloque=feu))
    code, h, r = appel(relais["url"] + "/suivi")
    assert code == 503 and r["etape"] == "en_calcul" and h["Retry-After"] == "15"
    feu.set()
    for _ in range(50):
        code, _, r = appel(relais["url"] + "/suivi")
        if code == 200:
            break
        threading.Event().wait(0.1)
    assert code == 200 and "claude-code-commandes-add-dir" in r["fiches"]
    # périmé : le dernier calcul est servi tout de suite, un seul nouveau calcul part
    R.suivi.calcule_a -= rr.SUIVI_TTL + 1
    assert appel(relais["url"] + "/suivi")[0] == 200


def test_suivi_une_vue_en_echec_est_nommee(relais):
    def lire(*args):
        if args == ("essai", "liste"):
            raise rr.adoptions.LectureImpossible("essai liste : code de sortie 2")
        return VUES[args]
    R = relais["R"]
    R.suivi = rr.Suivi(R.journal, lire=lire)
    R.suivi.lancer(attendre=True)
    code, _, r = appel(relais["url"] + "/suivi")
    assert code == 200 and r["sources_en_echec"] == ["essais : essai liste : code de sortie 2"]
    assert r["fiches"]["claude-code-commandes-add-dir"]["etat"] == "installe"


def test_suivi_journal_des_envois_propose_la_fiche(relais):
    R = relais["R"]
    R.journal.write_text(json.dumps({"date": "2026-10-24T10:00:00+0200", "id": "codex-commandes-review", "ok": True}) + "\n"
                         + json.dumps({"date": "2026-10-24T10:01:00+0200", "id": "refusee", "ok": False}) + "\n", encoding="utf-8")
    R.suivi = rr.Suivi(R.journal, lire=lire_factice({**VUES, ("idees",): {"sujets": []}}))
    R.suivi.lancer(attendre=True)
    f = appel(relais["url"] + "/suivi")[2]["fiches"]
    assert f["codex-commandes-review"]["etat"] == "propose" and f["codex-commandes-review"]["propose_le"] == "2026-10-24"
    assert "refusee" not in f


SUIVI_INSTALLE = {"ok": True, "etape": "suivi", "sources_en_echec": [], "fiches": {"fiche": {
    "id": "fiche", "etat": "installe", "position": "PERTINENTE", "missions": [{"id": "m-1", "etat": "CLOSE", "projete": "installe"}],
    "installations": [{"lot": "m-1", "le": "2026-10-11", "par": "mission", "resultat": None},
                      {"lot": "ess_0123456789ab", "le": "2026-10-20", "par": "essai", "resultat": "plafond"}],
    "resultat_observe": [{"essai": "ess_0123456789ab", "statut": "adopte", "maturite": "confirme", "explication": "gain 12 %"}]}}}


def test_carte_affiche_l_etat_projete_et_le_resultat_distinct():
    r = bouton_execute(etat=True, suivi={"corps": SUIVI_INSTALLE})
    s = r["suivi"]
    assert s["hidden"] is False
    assert s["texte"].startswith("Suivi Delta : proposée › retenue › en réalisation › installée (jugement : PERTINENTE)")
    assert "|Utilisations : installée le 2026-10-11, lot m-1 ; installée le 2026-10-20, lot ess_0123456789ab." in s["texte"]
    assert "|Résultat observé (Delta Lab) : ess_0123456789ab adopté · confirme : gain 12 %. À lire dans OBSERVATORY › EXPÉRIENCES" in s["texte"]


def test_carte_ecartee_en_realisation_et_sans_mesure():
    ecartee = {"ok": True, "fiches": {"fiche": {"id": "fiche", "etat": "ecarte", "position": "PAS_PERTINENTE", "missions": [],
                                                "installations": [], "resultat_observe": []}}}
    assert bouton_execute(etat=True, suivi={"corps": ecartee})["suivi"]["texte"] == "Suivi Delta : proposée › écartée (jugement : PAS_PERTINENTE)"
    cours = {"ok": True, "fiches": {"fiche": {"id": "fiche", "etat": "en_realisation", "position": "PERTINENTE", "installations": [],
                                              "missions": [{"id": "m-2", "etat": "A_RELIRE", "projete": "en_realisation"}], "resultat_observe": []}}}
    assert "en réalisation › installée (jugement : PERTINENTE ; mission m-2 (A_RELIRE))" in bouton_execute(etat=True, suivi={"corps": cours})["suivi"]["texte"]
    sans = json.loads(json.dumps(SUIVI_INSTALLE))
    sans["fiches"]["fiche"]["resultat_observe"] = []
    assert bouton_execute(etat=True, suivi={"corps": sans})["suivi"]["texte"].endswith("|Résultat observé : pas encore mesuré par Delta Lab.")
    # fiche absente du suivi, réponse refusée par le relais : rien n'est affiché
    for corps in ({"ok": True, "fiches": {}}, {"ok": False, "etape": "suivi"}):
        assert bouton_execute(etat=True, suivi={"corps": corps})["suivi"]["hidden"] is True


def test_carte_adoptee_sans_installation_jamais_dite_installee():
    """Relecture fe21147f : une livraison fusionnée sans fichier installé (preuves sans_installation) est « adoptée »."""
    adoptee = {"ok": True, "fiches": {"fiche": {"id": "fiche", "etat": "adopte", "position": "PERTINENTE",
                                                "missions": [{"id": "m-3", "etat": "CLOSE", "projete": "adopte"}],
                                                "installations": [{"lot": "m-3", "le": "2026-10-11", "par": "mission_sans_installation"}],
                                                "resultat_observe": []}}}
    texte = bouton_execute(etat=True, suivi={"corps": adoptee})["suivi"]["texte"]
    assert texte.startswith("Suivi Delta : proposée › retenue › en réalisation › adoptée (jugement : PERTINENTE)")
    assert "|Utilisations : adoptée le 2026-10-11, lot m-3 : livrée et fusionnée, rien d'installé." in texte
    assert "installée" not in texte
    rubrique = APP[APP.index("function remplirAmeliorations"):APP.index("// D64-bis : péremption")]
    assert 'f.etat === "installe" || f.etat === "adopte"' in rubrique


def test_carte_mission_illisible_etat_inconnu():
    """Relecture 9d0ce971 (4) : vue mission en échec sur une mission close → « état inconnu », jamais « retenue »."""
    inconnue = {"ok": True, "sources_en_echec": ["mission m-9 : mission m-9 : délai de 120 s dépassé"], "fiches": {"fiche": {
        "id": "fiche", "etat": "inconnu", "position": "PERTINENTE", "missions": [{"id": "m-9", "etat": "CLOSE", "projete": "inconnu"}],
        "missions_illisibles": ["m-9"], "installations": [], "resultat_observe": []}}}
    texte = bouton_execute(etat=True, suivi={"corps": inconnue})["suivi"]["texte"]
    assert texte == "Suivi Delta : état inconnu (jugement : PERTINENTE ; mission m-9 : vue OPÉRER illisible, relue au prochain calcul)"
    assert "retenue" not in texte


def test_rubrique_ameliorations_executee():
    """La vraie remplirAmeliorations sous Node : fiches installées et adoptées, dites comme telles, lien vers la fiche, échecs nommés."""
    corps = json.loads(json.dumps(SUIVI_INSTALLE))
    corps["sources_en_echec"] = ["mission m-9 : code de sortie 2"]
    corps["fiches"]["adoptee"] = {"id": "adoptee", "etat": "adopte", "installations": [
        {"lot": "m-3", "le": "2026-10-12", "par": "mission_sans_installation"}]}
    corps["fiches"]["retenue"] = {"id": "retenue", "etat": "retenu", "installations": []}
    r = bouton_execute(etat=True, suivi={"corps": corps}, rubrique=True, entrees=[{"id": "adoptee", "nom": "/goal"}])["rubrique"]
    assert r["hidden"] is False and r["liens"] == ["#reference?id=fiche", "#reference?id=adoptee"]   # dernière utilisation la plus récente d'abord
    assert r["texte"].startswith("Améliorations appliquées (2)")
    assert "/goal — adoptée le 2026-10-12, lot m-3 : livrée et fusionnée, rien d'installé" in r["texte"]
    assert "fiche — installée le 2026-10-11, lot m-1 ; installée le 2026-10-20, lot ess_0123456789ab" in r["texte"]
    assert "retenue" not in r["texte"] and r["texte"].endswith("Suivi incomplet : mission m-9 : code de sortie 2")


def test_suivi_jamais_demande_en_commun_ni_sans_envoi():
    assert bouton_execute(etat=True, commun=True, suivi={"corps": SUIVI_INSTALLE})["suivis"] == []
    corps = APP[APP.index("function chargerSuivi"):APP.index("function libelleInstallation")]
    # seul un navigateur qui a déjà envoyé une fiche interroge le relais (pas de demande d'accès au réseau local au visiteur)
    assert "enCommun() || estIos() || !Object.keys(lireEnvois()).length" in corps
    assert "innerHTML" not in APP[APP.index("function chargerSuivi"):APP.index("// D64-bis : péremption")]


def test_rubrique_ameliorations_appliquees():
    page = APP[APP.index("function pageReference"):APP.index("const ESSAIS_PAGE")]
    assert 'el("section", { id: "kb-ameliorations", hidden: true })' in page and "chargerSuivi().then(remplirAmeliorations)" in page
    assert page.index("if (!enCommun()) {") < page.index("kb-ameliorations")
    rubrique = APP[APP.index("function remplirAmeliorations"):APP.index("// D64-bis : péremption")]
    assert 'f.etat === "installe"' in rubrique and "#reference?id=" in rubrique and "libelleInstallation" in rubrique
    assert FR["ameliorations.titre"] == "Améliorations appliquées ({n})" and "rien n'est publié" in FR["ameliorations.sous_titre"]
