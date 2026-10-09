"""m-944fab565b10 : bouton « Envoyer à Delta » de l'onglet Référence et relais local vers la porte des idées."""

import json
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
    R.limiteur = rr.Limiteur(R.journal)
    R.deja = rr.DejaEnvoyees(R.journal)
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
    # relais injoignable : console si une adresse est enregistrée, sinon idée copiée pour le lanceur ; refus du relais : motif affiché
    assert "navigator.clipboard.writeText(texteIdeeKb(e))" in corps and "Delta n'a pas pris la référence" in corps
    # le message de repli précède la copie, qui ne peut pas rester en attente ; à défaut, un bouton « Copier l'idée »
    repli = corps[corps.index("async function repli("):corps.index("// le presse-papier")]
    assert repli.index("statut.textContent = motif") < repli.index("copierIdeeKb(e)") and "Copier l'idée" in repli
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
    assert 1 <= int(h["Retry-After"]) <= rr.FENETRE + 1 and h["Access-Control-Allow-Origin"] == "https://sylvainherbin.github.io"
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
    for chemin in ("docs/assets/app.js", "docs/assets/style.css", "docs/index.html", "scripts/relais_reference.py",
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
    assert h["Access-Control-Allow-Origin"] == "https://sylvainherbin.github.io"
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
    assert 'statut.textContent = "Envoyé à Delta, jugement en cours"' in corps
    assert "HEURE_MS = 3600000" in corps and 'noterHeure("envoi", e.id, t)' in corps and 'localStorage.setItem(CLE_HEURES' in corps
    memoire = corps[corps.index("function lireHeures"):corps.index("function hhmm")]
    assert memoire.count("try {") == 2 and memoire.count("catch (err)") == 2
    envoi = corps[corps.index("async function envoyerADelta"):corps.index("async function repli(")]
    assert "déjà envoyée à ${hhmm(dejaT)}" in envoi and envoi.index('heureRecente("envoi", e.id)') < envoi.index("estIos()") < envoi.index("relaisJoignable()")
    assert envoi.index("déjà envoyée à ${hhmm(dejaT)}") < envoi.index("relaisJoignable()")   # aucun appel au relais
    assert 'r.etape === "deja_envoyee"' in envoi          # 409 du relais : le bouton se bloque aussi
    # (3) repli : le message exact, puis « copiée à HH:MM » pour l'heure
    assert ("Pas envoyé : relais non joignable et console non reliée (ouvre la console et touche « Relier Delta-IA » "
            "une fois sur cet appareil).") in corps
    assert "brave://settings/content/localhostAccess" not in APP
    assert "L'idée est copiée : colle-la une fois dans le lanceur." in corps and "return repli(e, statut, PAS_JOIGNABLE, bouton)" in envoi
    repli = corps[corps.index("async function repli("):corps.index("// le presse-papier")]
    assert repli.count('noterHeure("copie", e.id, Date.now())') == 2
    bloc = corps[corps.index("function blocEnvoi"):]
    assert "copiée à ${hhmm(copie)}" in bloc and 'heureRecente("copie", e.id)' in bloc and "Envoyé à Delta à ${hhmm(envoi)}, jugement en cours" in bloc
    assert "bloquerBouton(b, envoi)" in bloc


def test_aide_dit_la_regle_d_une_heure():
    envoi = APP[APP.index('id: "envoi"'):APP.index('id: "a-tester"')]
    assert "ne repart pas dans l'heure" in envoi and "Pas envoyé" in envoi and "jugement en cours" in envoi


# ---- m-94f3b7e1274b : exécution du bouton, sans appeler le service installé ----

def bouton_execute(**options):
    """Le vrai code du bouton sous Node : réseau, onglets, horloge et presse-papier simulés."""
    node = shutil.which("node")
    assert node, "Node est nécessaire aux tests du bouton (présent sur ubuntu-24.04 en CI)"
    code = APP[APP.index("const RELAIS"):APP.index("// D64-bis : péremption")]
    script = r"""
const vm = require('node:vm');
const {code, options: o} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const appels = [], onglets = [], copies = [], delais = [], liens = [];
const stockage = new Map();
if (o.console !== false) stockage.set('delta.console', o.console || 'https://console.example');
let maintenant = 1000000000000;
class Horloge extends Date { static now() { return maintenant; } }
function el(tag, props, ...children) {
  return {tag, ...props, textContent: props.text || '', children, listeners: {},
    addEventListener(type, cb) { this.listeners[type] = cb; }, remove() {}};
}
const context = vm.createContext({
  Date: Horloge, URL, el, KB_NOMS: {}, PRODUITS: {},
  texte: (s, defaut) => s || defaut, jourLocalIso: () => '2001-09-09', dateFr: s => s,
  localStorage: {getItem: k => stockage.get(k), setItem: (k, v) => stockage.set(k, v)},
  navigator: {userAgent: o.ios ? 'iPhone' : '', platform: o.ipad ? 'MacIntel' : '',
    maxTouchPoints: o.ipad ? 5 : 0, clipboard: {writeText: async s => {
      copies.push(s); if (o.copie === false) throw Error('refus');
    }}},
  document: {querySelectorAll: () => []},
  window: {open: (url, cible) => {onglets.push({url, cible}); return o.popup === false ? null : {}; }},
  setTimeout: () => {}, AbortSignal: {timeout: ms => {delais.push(ms); return null;}},
  fetch: async (url, opts) => {
    appels.push({url, ...opts});
    if (url.endsWith('/etat')) {if (o.etat === 'erreur') throw Error('réseau'); return {ok: o.etat === true};}
    return {json: async () => o.post || {ok: true}};
  }
});
vm.runInContext(code + ';globalThis.api = {envoyerADelta, blocEnvoi, urlConsole, heureRecente};', context);
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
  await context.api.envoyerADelta(e, bouton, statut);
  const second = statut.textContent;
  if (o.expire) {maintenant += 3600001; await context.api.envoyerADelta(e, bouton, statut);}
  console.log(JSON.stringify({appels, onglets, copies, delais, avantLien, premier, second,
    disabled: !!bouton.disabled, rendu: rendu.children[1].textContent,
    liens: liens.map(l => ({tag: l.tag, href: l.href, target: l.target, rel: l.rel}))}));
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    res = subprocess.run([node, "-e", script], input=json.dumps({"code": code, "options": options}),
                         text=True, capture_output=True, timeout=10)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_bureau_relais_prioritaire_meme_console_reliee():
    r = bouton_execute(etat=True)
    assert [a["url"].rsplit("/", 1)[-1] for a in r["appels"]] == ["etat", "reference"]
    assert json.loads(r["appels"][1]["body"]) == {"id": "fiche"}
    assert r["delais"] == [3000, 25000] and not r["onglets"] and not r["copies"]
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
