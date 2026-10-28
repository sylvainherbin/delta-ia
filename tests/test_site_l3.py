"""Deux couches, lot L3, côté site : bilingue EN/FR (décision du 22/10), lecteurs des deux formats, couche lue explicite.

- dictionnaires (docs/assets/textes.js) : mêmes clés, valeurs non vides, mêmes variables, clés d'app.js présentes ;
- aucune chaîne d'interface écrite en dur dans app.js hors dictionnaire ;
- pages par langue générées (scripts/site_langues.py) : textes du dictionnaire de leur langue, hreflang, canonical, og:locale,
  sitemap avec alternates, adresses lues dans le bootstrap ;
- exécution réelle d'app.js (tests/harnais_site.js) : ancienne route réelle, vue compatible (champs personnels nuls, sans
  etat.json), génération commune réelle, couche commune illisible ou de schéma inconnu (sans repli sur l'ancienne route),
  anciennes ancres.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

import site_langues
from test_relais_reference import trouver_node
from textes_site import EN, FR, TEXTES

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"
APP = (DOCS / "assets" / "app.js").read_text(encoding="utf-8")
GENERATION = json.loads((DOCS / "commun" / "v1" / "index.json").read_text(encoding="utf-8"))["generation"]


# ---------------------------------------------------------------- dictionnaires

def test_memes_cles_valeurs_non_vides_et_memes_variables():
    assert set(TEXTES) == {"en", "fr"}
    assert set(EN) == set(FR), sorted(set(EN) ^ set(FR))
    for langue, d in TEXTES.items():
        for cle, v in d.items():
            assert re.fullmatch(r"[a-z_]+(\.[a-z0-9_-]+)+", cle), cle
            assert isinstance(v, str) and v.strip(), f"{langue}:{cle} vide"
    for cle in FR:
        assert set(re.findall(r"\{(\w+)\}", FR[cle])) == set(re.findall(r"\{(\w+)\}", EN[cle])), cle


def test_un_dictionnaire_incomplet_est_detecte(monkeypatch):
    """Le contrôle échoue bien si une clé n'existe que dans une langue (garde contre un test qui ne verrait rien)."""
    fr = dict(FR, **{"onglet.nouveau": "Nouveau"})
    assert set(EN) != set(fr)


def cles_utilisees() -> tuple[set, list]:
    """Clés littérales d'app.js (motif d'une clé, premier segment connu) et clés à variable développées sur leurs valeurs."""
    espaces = {c.split(".")[0] for c in FR}
    litterales = {c for c in re.findall(r'"([a-z_]+(?:\.[a-z0-9_]+)+)"', APP) if c.split(".")[0] in espaces and not c.endswith((".json", ".js"))}
    dynamiques = re.findall(r"`([a-z_]+(?:\.[a-z0-9_]+)*\.\$\{[^`]+)`", APP)
    return litterales, dynamiques


def test_cles_utilisees_par_app_js_presentes():
    litterales, dynamiques = cles_utilisees()
    assert len(litterales) > 200
    manquantes = sorted(c for c in litterales if c not in FR)
    assert not manquantes, manquantes
    # clés à variable : chaque valeur possible de la variable
    valeurs = {
        "impact": ["fort", "moyen", "faible", "nul"], "certitude": ["officiel", "rapporte", "non_confirme"],
        "type": ["nouveaute", "amelioration", "correction", "changement_rupture", "depreciation", "actu"],
        "version": ["a_jour", "en_retard", "inconnu", "embarque", "non_utilise"],
        "perimetre": ["claude", "openai", "actu"], "perimetre.court": ["claude", "openai", "actu"],
        "categorie": ["fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis", "methodes", "modeles"],
        "categorie.nom": ["fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis", "methodes", "modeles"],
        "categorie.nom_pluriel": ["fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis", "methodes", "modeles"],
        "aide.etiquette": ["sert", "geste", "limite"],
        # boucle d'adoption (m-a04181983623) : états projetés, statuts d'essai de Delta Lab (STATUTS d'essais.py)
        "suivi.etape": ["propose", "retenu", "ecarte", "en_realisation", "adopte", "installe", "inconnu"],
        "suivi.essai": ["en_essai", "propose", "adopte", "ecarte", "regressif", "remplace"],
    }
    prefixes = {re.sub(r"\.\$\{.*", "", d) for d in dynamiques}
    assert prefixes <= set(valeurs) | {"aide", "categorie"}, prefixes
    for prefixe, liste in valeurs.items():
        for v in liste:
            assert f"{prefixe}.{v}" in FR, f"{prefixe}.{v}"
    # aide : chaque section déclarée dans AIDE a ses quatre textes (et sa liste)
    for ident, liste in re.findall(r'\{ id: "([a-z-]+)"(?:, liste: (\d+))? \}', APP[APP.index("const AIDE = ["):APP.index("const ADRESSES_AIDE")]):
        for champ in ("titre", "sert", "geste", "limite"):
            assert f"aide.{ident}.{champ}" in FR, f"aide.{ident}.{champ}"
        for i in range(1, int(liste or 0) + 1):
            assert f"aide.{ident}.liste.{i}" in FR


# ---------------------------------------------------------------- aucune chaîne d'interface en dur

def jetons_js(source: str, decalage: int = 0):
    """Littéraux de chaînes d'un source JS : (début, fin, texte statique). Commentaires et expressions régulières sautés ;
    les expressions `${…}` des gabarits sont parcourues aussi. Suffisant pour app.js (heuristique classique du `/`)."""
    out, i, n = [], 0, len(source)
    precedent = ""  # dernier caractère significatif hors espace, pour distinguer division et expression régulière
    while i < n:
        c = source[i]
        if source.startswith("//", i):
            i = source.find("\n", i)
            i = n if i < 0 else i
            continue
        if source.startswith("/*", i):
            i = source.index("*/", i) + 2
            continue
        if c in "\"'":
            j = i + 1
            while source[j] != c:
                j += 2 if source[j] == "\\" else 1
            out.append((decalage + i, decalage + j + 1, source[i + 1:j]))
            i, precedent = j + 1, "s"
            continue
        if c == "`":
            j, statique = i + 1, []
            while source[j] != "`":
                if source[j] == "\\":
                    statique.append(source[j:j + 2]); j += 2; continue
                if source.startswith("${", j):
                    profondeur, k = 1, j + 2
                    while profondeur:
                        if source[k] == "{": profondeur += 1
                        elif source[k] == "}": profondeur -= 1
                        elif source[k] in "\"'`":
                            # chaîne imbriquée : sauter jusqu'à sa fin
                            q, k = source[k], k + 1
                            while source[k] != q:
                                k += 2 if source[k] == "\\" else 1
                        k += 1
                    out.extend(jetons_js(source[j + 2:k - 1], decalage + j + 2))
                    statique.append(" ")
                    j = k
                    continue
                statique.append(source[j]); j += 1
            out.append((decalage + i, decalage + j + 1, "".join(statique)))
            i, precedent = j + 1, "s"
            continue
        if c == "/" and (precedent in "(,=:[!&|?{};+-*%<>~^" or precedent == "" or re.search(r"(return|typeof|case)\s*$", source[max(0, i - 8):i])):
            j, classe = i + 1, False
            while True:
                if source[j] == "\\": j += 2; continue
                if source[j] == "[": classe = True
                elif source[j] == "]": classe = False
                elif source[j] == "/" and not classe: break
                j += 1
            i = j + 1
            while i < n and source[i].isalpha():
                i += 1
            precedent = "r"
            continue
        if not c.isspace():
            precedent = c if not (c.isalnum() or c in "_$") else "a"
        i += 1
    return out


# Zones d'app.js qui ne sont pas de l'interface : message français destiné à Delta (même phrase que texte_idee() du relais),
# libellé de l'historique des données, journaux de console.
def zones_exclues():
    zones = []
    debut = APP.index("function texteIdeeKb")
    zones.append((debut, APP.index("\n  }\n", debut)))
    for m in re.finditer(r"console\.(log|error)\(", APP):
        zones.append((m.start(), APP.index(");", m.start())))
    i = APP.index("const LIGNE_AJOUT")
    zones.append((i, APP.index("\n", i)))
    return zones


LETTRES = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
# langage naturel : une lettre accentuée, une majuscule suivie d'un mot, ou une ponctuation de phrase entre deux mots
NATUREL = re.compile(r"[À-ÿ]|\b[A-Z][a-z]+ [a-zA-Z]|[a-zA-Z][.:;!?] [a-zA-Z]|[a-z]'[a-z]")
# littéraux admis qui ressemblent à du texte sans en être (aucun ne s'affiche comme phrase)
ADMIS = {"Claude Code", "Claude", "ChatGPT", "Codex", "Delta-IA", "MacIntel", "AI Agents & Builders"}


ESPACES = {c.split(".")[0] for c in FR}


def est_cle(texte: str) -> bool:
    return bool(re.fullmatch(r"[a-z_]+(\.[a-z0-9_]+)+", texte)) and texte.split(".")[0] in ESPACES and not texte.endswith((".json", ".js"))


def chaines_en_dur(source: str) -> list[str]:
    exclues = zones_exclues() if source is APP else []
    trouvees = []
    for debut, fin, texte in jetons_js(source):
        if any(a <= debut < b for a, b in exclues) or texte in ADMIS:
            continue
        avant = source[max(0, debut - 30):debut]
        if re.search(r"\bt\(\s*$", avant) or est_cle(texte):   # clé du dictionnaire (y compris dans un ternaire passé à t)
            continue
        apres = source[fin:fin + 6]
        if re.search(r"[!=]==\s*$|matchMedia\(\s*$", avant) or re.match(r"\s*[!=]==", apres):  # comparaison, requête média
            continue
        contexte_ui = re.search(r"(\btext|\btitle|placeholder|\"aria-label\"|\blabel)\s*:\s*[^,{}]*$|\.textContent\s*=\s*[^;]*$|\bbadge\([^,()]*,\s*$|\.append\(\s*$|\bel\(\"[a-z0-9]+\",\s*(null|\{[^{}]*\})\s*,\s*$", avant)
        if NATUREL.search(texte) or (contexte_ui and LETTRES.search(texte)):
            trouvees.append(texte)
    return trouvees


def test_aucune_chaine_d_interface_en_dur_dans_app_js():
    assert chaines_en_dur(APP) == []


def test_le_controle_des_chaines_en_dur_les_voit():
    """Une phrase écrite en dur, un libellé court dans `text:` ou en enfant d'el() sont bien signalés."""
    for code in ('el("p", { text: "Aucune donnée" });', 'el("button", { type: "button", text: "Done" });',
                 'el("strong", null, "Pourquoi");', 'x.textContent = cond ? "Envoyé" : "";', 'badge("type", "Skill");',
                 'el("p", { text: `${n} items shown` });'):
        assert chaines_en_dur(code), code
    for code in ('el("p", { class: "carte kb attente", text: t("kb.attente") });', 'const r = /`([^`\\n]+)`/g;', 'el("td", { text: "?" });'):
        assert not chaines_en_dur(code), code


def test_aucune_adresse_de_delta_en_dur_cote_site():
    conf = json.loads((RACINE / "scripts/deltalib/couches/bootstrap.json").read_text(encoding="utf-8"))
    hotes = {re.sub(r"^https://([^/]+).*", r"\1", u) for u in (conf["site_public_url"], conf["mcp_public_url"], *conf["site_anciennes_urls"])}
    for f in ("app.js", "textes.js"):
        texte = (DOCS / "assets" / f).read_text(encoding="utf-8")
        for h in hotes:
            assert h not in texte, (f, h)
    # l'aide interpole les adresses de la configuration
    assert "{mcp_url}" in FR["aide.mcp.geste"] and "{mcp_url}" in EN["aide.mcp.geste"]
    assert "{site_url}#console=<adresse>" in FR["aide.envoi.geste"] and "{site_url}#console=<adresse>" in EN["aide.envoi.geste"]
    assert "mcp_url: CONFIG.mcp_public_url" in APP and "site_url: CONFIG.site_public_url" in APP


# ---------------------------------------------------------------- pages par langue

class Textes(HTMLParser):
    """Nœuds texte et attributs lisibles (title, content de description/og, aria-label) d'une page."""
    def __init__(self):
        super().__init__()
        self.textes, self.liens, self.metas, self.dans = [], [], {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.dans.append(tag)
        if "aria-label" in a:
            self.textes.append(a["aria-label"])
        if tag == "link":
            self.liens.append(a)
        if tag == "meta" and ("property" in a or "name" in a):
            self.metas[a.get("property") or a.get("name")] = a.get("content")

    def handle_endtag(self, tag):
        if self.dans and self.dans[-1] == tag:
            self.dans.pop()

    def handle_data(self, data):
        if data.strip() and (not self.dans or self.dans[-1] not in ("script", "style")):
            self.textes.append(data.strip())


def lire_page(langue):
    p = Textes()
    p.feed((DOCS / site_langues.LANGUES[langue][0] / "index.html").read_text(encoding="utf-8"))
    return p


def test_pages_generees_a_jour():
    assert site_langues.main(["--verifier"]) == 0, "lancer scripts/site_langues.py"


@pytest.mark.parametrize("langue", ["en", "fr"])
def test_textes_des_pages_viennent_du_dictionnaire_de_leur_langue(langue):
    p = lire_page(langue)
    valeurs = set(TEXTES[langue].values())
    for x in p.textes:
        assert x in valeurs, (langue, x)
    autre = "fr" if langue == "en" else "en"
    # au moins le pied et les onglets sont bien dans la langue de la page
    assert TEXTES[langue]["html.pied"] in p.textes and TEXTES[langue]["onglet.reference"] in p.textes
    assert TEXTES[autre]["html.pied"] not in p.textes


@pytest.mark.parametrize("langue", ["en", "fr"])
def test_hreflang_canonical_og_locale(langue):
    base = site_langues.mod_config.charger()["site_public_url"]
    p = lire_page(langue)
    alternates = {l["hreflang"]: l["href"] for l in p.liens if l.get("rel") == "alternate"}
    assert alternates == {"en": base, "fr": base + "fr/", "x-default": base}
    canonical = [l["href"] for l in p.liens if l.get("rel") == "canonical"]
    assert canonical == [base if langue == "en" else base + "fr/"]
    assert p.metas["og:locale"] == TEXTES[langue]["html.og_locale"] and p.metas["og:url"] == canonical[0]
    assert p.metas["og:locale:alternate"] == TEXTES["fr" if langue == "en" else "en"]["html.og_locale"]
    html = (DOCS / site_langues.LANGUES[langue][0] / "index.html").read_text(encoding="utf-8")
    assert f'<html lang="{langue}" data-racine="{site_langues.LANGUES[langue][1]}">' in html
    # config.js puis textes.js avant app.js
    assert html.index("assets/config.js") < html.index("assets/textes.js") < html.index("assets/app.js")
    # sélecteur vers l'autre langue, sans redirection automatique dans la page
    assert 'id="choix-langue"' in html and "location.replace" not in APP and "navigator.language" not in APP


def test_sitemap_et_robots():
    base = site_langues.mod_config.charger()["site_public_url"]
    s = (DOCS / "sitemap.xml").read_text(encoding="utf-8")
    assert s.count("<url>") == 2 and f"<loc>{base}</loc>" in s and f"<loc>{base}fr/</loc>" in s
    for l, u in (("en", base), ("fr", base + "fr/"), ("x-default", base)):
        assert s.count(f'<xhtml:link rel="alternate" hreflang="{l}" href="{u}"/>') == 2
    assert f"Sitemap: {base}sitemap.xml" in (DOCS / "robots.txt").read_text(encoding="utf-8")


def test_manifestes_par_langue():
    for langue, (dossier, racine, _) in site_langues.LANGUES.items():
        m = json.loads((DOCS / dossier / "manifest.webmanifest").read_text(encoding="utf-8"))
        assert m["name"] == TEXTES[langue]["manifeste.nom"] and m["lang"] == langue and m["start_url"] == "./"
        for i in m["icons"]:
            assert (DOCS / dossier / i["src"]).resolve().exists(), i["src"]


# ---------------------------------------------------------------- exécution réelle d'app.js

def executer(**entree):
    node = trouver_node()
    if not node:
        assert not os.environ.get("CI"), "Node est nécessaire aux tests du site"
        pytest.skip("Node introuvable")
    r = subprocess.run([node, str(RACINE / "tests" / "harnais_site.js")], input=json.dumps(entree), text=True,
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    sortie = json.loads(r.stdout)
    assert not [e for e in sortie["erreurs"] if "texte-manquant" in e], sortie["erreurs"]
    return sortie


def dernier_jour(p):
    idx = json.loads((DOCS / "data" / p / "index.json").read_text(encoding="utf-8"))
    return sorted(j["date"] for j in idx["jours"])[-1]


def horloge_des_donnees():
    """Une heure après le dernier passage publié : la bannière « n'a pas tourné depuis N h » ne dépend plus du jour du test."""
    maj = [datetime.fromisoformat(json.loads((DOCS / "data" / p / "index.json").read_text(encoding="utf-8"))["maj_le"])
           for p in ("claude", "openai", "actu")]
    return (max(maj) + timedelta(hours=1)).isoformat()


def test_horloge_fixee_decide_de_la_banniere_de_fraicheur():
    """Témoin : à 1 h du dernier passage, pas de bannière ; 40 h plus tard, la bannière précède « Aujourd'hui »."""
    frais = horloge_des_donnees()
    tard = (datetime.fromisoformat(frais) + timedelta(hours=40)).isoformat()
    assert executer(langue="fr", ancres=["#aujourdhui"], horloge=frais)["etapes"][0]["texte"].startswith(FR["onglet.aujourdhui"])
    en_retard = executer(langue="fr", ancres=["#aujourdhui"], horloge=tard)["etapes"][0]["texte"]
    assert en_retard.startswith("Claude Code n'a pas tourné depuis ") and not en_retard.startswith(FR["onglet.aujourdhui"])


def test_ancienne_route_reelle_en_anglais_et_en_francais():
    horloge = horloge_des_donnees()
    for langue, attendu in (("en", "Today"), ("fr", "Aujourd'hui")):
        r = executer(langue=langue, ancres=["#aujourdhui"], horloge=horloge)
        texte = r["etapes"][0]["texte"]
        assert texte.startswith(attendu), texte[:80]
        assert TEXTES[langue]["couche.ancienne"] in r["etapes"][0]["couche"]
        assert "commun/v1/index.json" not in r["lus"]
    # le sélecteur garde la vue : même ancre dans l'autre langue
    r = executer(langue="en", ancres=["#reference?id=claude-code-commandes-add-dir"])
    assert r["etapes"][0]["langue_href"] == "fr/#reference?id=claude-code-commandes-add-dir"
    r = executer(langue="fr", ancres=["#archives/2026-10-24"])
    assert r["etapes"][0]["langue_href"] == "../#archives/2026-10-24"
    assert all(x.startswith("data/") for x in r["lus"]), "sous /fr/, les données se lisent à la racine du site"


def vue_compatible():
    """Ancienne route en vue compatible (L5 prévue) : champs personnels nuls, sans etat.json, versions sans installée."""
    remplacer = {}
    for p in ("claude", "openai", "actu"):
        d = dernier_jour(p)
        q = json.loads((DOCS / "data" / p / f"{d}.json").read_text(encoding="utf-8"))
        for e in q["elements"]:
            e.update(impact=None, pour_toi=None, action=None, projets_concernes=[])
        q["synthese"] = None
        remplacer[f"data/{p}/{d}.json"] = q
    versions = json.loads((DOCS / "data" / "versions.json").read_text(encoding="utf-8"))
    for v in versions:
        v.update(version=None, detectee_le=None, statut="a_jour", note=None)
    remplacer["data/versions.json"] = versions
    return remplacer


def test_vue_compatible_sans_etat_prive_reste_consultable_et_pas_faussement_vide():
    remplacer = vue_compatible()
    attendus = sum(len(q["elements"]) for k, q in remplacer.items() if k.count("/") == 2)
    assert attendus > 0
    for langue in ("en", "fr"):
        r = executer(langue=langue, ancres=["#aujourdhui"], absents=["data/etat.json"], remplacer=remplacer)
        texte = r["etapes"][0]["texte"]
        d = TEXTES[langue]
        # éléments à impact inconnu affichés, aucun impact fabriqué, aucune bascule « sans impact »
        assert d["elements.titre"].replace("{n}", str(attendus)) in texte
        for niveau in ("fort", "moyen", "faible", "nul"):
            assert d[f"impact.{niveau}"] not in texte
        assert "impact ?" not in texte and d["nul.afficher"].split("(")[0] not in texte
        # quotas absents sans erreur ; installée inconnue, aucune comparaison « à jour »
        assert d["comptes.titre_haut"] not in texte
        tableau = tableau_outils(texte, langue)
        assert d["outils.inconnue"] in tableau and d["version.a_jour"] not in tableau
        assert "data/etat.json" in r["lus"]


def tableau_outils(texte, langue):
    """Le texte de la vue jusqu'au titre des éléments : les statuts des outils s'y lisent, pas le texte libre des éléments
    (une « mise à jour » dans un titre du jour contient « à jour »)."""
    marque = TEXTES[langue]["elements.titre"].split("{n}")[0]
    assert marque in texte, texte[:200]
    return texte.split(marque, 1)[0]


def test_temoin_a_jour_reste_lu_dans_le_tableau_des_outils_et_pas_dans_le_texte_libre():
    remplacer = vue_compatible()
    remplacer["data/versions.json"] = [{"pertinent_pour_profil": True, "outil": "Claude Code", "version": "2.1.311",
                                        "detectee_le": "2026-10-27T03:00:27+00:00", "derniere_publiee": "2.1.311",
                                        "source_derniere": "claude-code-changelog", "statut": "a_jour"}]
    for langue in ("en", "fr"):
        d = TEXTES[langue]
        r = executer(langue=langue, ancres=["#aujourdhui"], absents=["data/etat.json"], remplacer=remplacer)
        assert d["version.a_jour"] in tableau_outils(r["etapes"][0]["texte"], langue), "l'assertion de la vue compatible ne verrait plus « à jour »"
        libre = "x " + d["elements.titre"].replace("{n}", "1") + f" système {d['version.a_jour']}, hors des outils suivis"
        assert d["version.a_jour"] not in tableau_outils(libre, langue)


def test_textes_bilingues_d_une_fiche_suivent_la_langue_de_la_page():
    kb = json.loads((DOCS / "data" / "kb" / "claude" / "commandes.json").read_text(encoding="utf-8"))
    e = next(x for x in kb["entrees"] if x["id"] == "claude-code-commandes-add-dir")
    e.update(commentee=False, recommandation=None, textes={"description": {"en": {"texte": "English text A", "statut": "source"},
                                                                          "fr": {"texte": "Texte français A", "statut": "automatique"}}})
    remplacer = {"data/kb/claude/commandes.json": kb}
    ancre = "#reference?id=claude-code-commandes-add-dir"
    assert "English text A" in executer(langue="en", ancres=[ancre], remplacer=remplacer)["etapes"][0]["texte"]
    fr = executer(langue="fr", ancres=[ancre], remplacer=remplacer)["etapes"][0]["texte"]
    assert "Texte français A" in fr and "English text A" not in fr and FR["kb.repli_en"] not in fr
    del e["textes"]["description"]["fr"]
    fr = executer(langue="fr", ancres=[ancre], remplacer=remplacer)["etapes"][0]["texte"]
    assert "English text A" in fr and FR["kb.repli_en"] in fr, "repli anglais annoncé"


def test_generation_commune_reelle():
    gen = json.loads((DOCS / "commun" / "v1" / GENERATION / "kb" / "openai" / "parametres.json").read_text(encoding="utf-8"))
    windows = next(e for e in gen["entrees"] if e["id"] == "codex-parametres-windows-sandbox")
    ancres = ["#aujourdhui", "#reference?id=codex-parametres-windows-sandbox", "#reference?id=modele-claude-opus-5-5-low",
              "#archives", "#semaine", "#a-tester", "#changelogs", "#actu", "#archives/" + dernier_jour("claude")]
    for langue in ("en", "fr"):
        d = TEXTES[langue]
        r = executer(langue=langue, recherche="?couche=commun", ancres=ancres)
        # jamais de lecture de l'ancienne route ni d'un fichier personnel
        assert r["lus"] and all(x.startswith("commun/v1/") for x in r["lus"]), [x for x in r["lus"] if not x.startswith("commun/v1/")]
        assert not any(x.endswith(("etat.json", "a-tester.json", "recent.json", "recherche.json")) or "/semaine/" in x for x in r["lus"])
        e = {x["ancre"]: x for x in r["etapes"]}
        assert GENERATION in e["#aujourdhui"]["couche"]
        auj = e["#aujourdhui"]["texte"]
        assert d["personnel.aujourdhui"] in auj and d["outils.titre_publiees"].upper() in auj and d["comptes.titre_haut"] not in auj
        assert d["synthese.commun_absente"].split("{n}")[0] in auj
        assert re.search(re.escape(d["elements.titre"].split("{n}")[0]) + r"[1-9]", auj), "éléments du jour listés"
        fiche = e["#reference?id=codex-parametres-windows-sandbox"]["texte"]
        assert windows["textes"]["description"][langue]["texte"][:60] in fiche
        assert d["kb.avis_indisponible"] in fiche and d["kb.systemes"].replace("{liste}", "windows") in fiche
        modele = e["#reference?id=modele-claude-opus-5-5-low"]["texte"]
        assert "claude --model claude-opus-5-5 --effort low" in modele and "Recommandation OPÉRER" not in modele
        assert d["personnel.recherche"] in e["#archives"]["texte"]
        assert d["personnel.semaine"] in e["#semaine"]["texte"]
        assert d["personnel.a_tester"] in e["#a-tester"]["texte"]
        assert d["changelogs.sous_titre"] in e["#changelogs"]["texte"]


def test_couche_commune_illisible_ou_schema_inconnu_sans_repli_sur_l_ancienne_route():
    r = executer(langue="en", recherche="?couche=commun", absents=["commun/v1/index.json"])
    texte = r["etapes"][0]["texte"]
    assert texte.startswith("Common reference unavailable: commun/v1/index.json: HTTP 404"), texte[:120]
    assert not any(x.startswith("data/") for x in r["lus"])
    index = json.loads((DOCS / "commun" / "v1" / "index.json").read_text(encoding="utf-8"))
    r = executer(langue="fr", recherche="?couche=commun", remplacer={"commun/v1/index.json": dict(index, schema_version=2)})
    texte = r["etapes"][0]["texte"]
    assert "Référence commune indisponible" in texte and "version 2 du schéma delta.manifest inconnue" in texte
    assert not any(x.startswith("data/") for x in r["lus"])
    # fichier de veille d'une version inconnue : erreur de ce périmètre, nommée par la couche
    veille = json.loads((DOCS / "commun" / "v1" / GENERATION / "veille" / "actu.json").read_text(encoding="utf-8"))
    r = executer(langue="en", recherche="?couche=commun", remplacer={f"commun/v1/{GENERATION}/veille/actu.json": dict(veille, schema_version=9)})
    assert "Common reference, actu: veille/actu.json: unknown version 9 of schema delta.commun" in r["etapes"][0]["texte"]


def test_ancienne_route_illisible_bascule_sur_la_reference_commune():
    absents = [f"data/{p}/index.json" for p in ("claude", "openai", "actu")]
    r = executer(langue="en", ancres=["#aujourdhui"], absents=absents)
    assert EN["couche.automatique"] in r["etapes"][0]["couche"] and GENERATION in r["etapes"][0]["couche"]
    assert EN["personnel.aujourdhui"] in r["etapes"][0]["texte"]
    # ce qui était parti de l'ancienne route (quotas, versions installées) n'est pas affiché sur la référence commune
    assert EN["comptes.titre_haut"] not in r["etapes"][0]["texte"] and EN["outils.titre"].upper() not in r["etapes"][0]["texte"]


def test_anciennes_ancres_fonctionnent():
    semaine = json.loads((DOCS / "data" / "semaine" / "index.json").read_text(encoding="utf-8"))["semaines"][0]["semaine"]
    d = dernier_jour("claude")
    r = executer(langue="fr", horloge=horloge_des_donnees(),
                 ancres=[f"#archives/{d}", f"#semaine/{semaine}", "#reference?q=/add-dir", "#archives?q=worktree",
                         "#reference?recent=7", "#console="])
    e = [x["texte"] for x in r["etapes"]]
    assert FR["archives.retour"] in e[0]
    assert semaine in e[1] and FR["comptes.titre"] in e[1]
    assert "/add-dir" in e[2]
    assert FR["recherche.titre"] not in e[3] and "worktree" in e[3].lower()
    assert FR["filtre.depuis_7"] in e[4]
    assert e[5].startswith(FR["onglet.aujourdhui"])
