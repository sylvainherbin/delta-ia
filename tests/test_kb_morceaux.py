"""Onglet Référence chargé par morceaux (m-b6207baf75ca) : premiers fichiers (commandes, fonctionnalités), reste en arrière-plan,
fichier demandé par un filtre passé devant, fiche seule lue dans son fichier, compteurs annoncés provisoires."""

import json
import re
from pathlib import Path
from textes_site import FR

RACINE = Path(__file__).resolve().parent.parent
KB = RACINE / "docs" / "data" / "kb"
PERIMETRES = ("claude", "openai")
APP = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")


def morceau(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i + len(debut))]


def categories_site():
    """Catégories de la Référence d'app.js (L3 : clés seules, libellés dans le dictionnaire)."""
    return json.loads(re.search(r"const KB_CATEGORIES_CLES = (\[[^\]]*\]);", APP).group(1))


def test_les_quatorze_fichiers_du_disque_sont_ceux_du_site():
    cats = set(categories_site()) - {"methodes", "modeles"}  # D121 : fichiers locaux, hors périmètres
    perimetres = set(json.loads(re.search(r"const KB_PERIMETRES = (\[[^\]]*\]);", APP).group(1)))
    sur_disque = {(f.parent.name, f.stem) for f in KB.glob("*/*.json")}
    assert perimetres == set(PERIMETRES)
    assert sur_disque == {(p, c) for p in perimetres for c in cats} and len(sur_disque) == 14


def test_premiers_fichiers_et_arriere_plan_couvrent_toute_la_base():
    prio = json.loads(re.search(r"const KB_PRIORITAIRES = (\[[^\]]*\]);", APP).group(1))
    reste = json.loads(re.search(r"const KB_ARRIERE_PLAN = (\[[^\]]*\]);", APP).group(1))
    assert prio == ["commandes", "fonctionnalites"], "décision de la mission : commandes et fonctionnalités des deux périmètres d'abord"
    assert not set(prio) & set(reste) and len(set(prio) | set(reste)) == 7
    assert {f.stem for f in KB.glob("*/*.json")} == set(prio) | set(reste)
    # le plus lourd (paramètres) est le dernier de l'arrière-plan
    assert reste[-1] == "parametres"


def test_chaque_id_donne_son_fichier():
    """La fiche seule (#reference?id=) ne lit que le fichier déduit de l'id : le calcul de app.js doit retomber sur le bon fichier."""
    perim = {"claude": "claude", "claude-code": "claude", "codex": "openai", "chatgpt": "openai"}
    assert json.loads(re.search(r"const KB_PRODUIT_PERIMETRE = (\{[^}]*\});", APP).group(1).replace("claude:", '"claude":').replace("codex:", '"codex":').replace("chatgpt:", '"chatgpt":')) == perim
    cats = categories_site()
    motif = re.compile(rf"^(claude-code|claude|codex|chatgpt)-({'|'.join(cats)})-")
    assert "(claude-code|claude|codex|chatgpt)" in APP and "const RE_ID_KB = new RegExp(`^(claude-code|claude|codex|chatgpt)-(${KB_CATEGORIES_CLES.filter((c) => c !== \"methodes\" && c !== \"modeles\").join(\"|\")})-`);" in APP
    for f in KB.glob("*/*.json"):
        for e in json.loads(f.read_text(encoding="utf-8"))["entrees"]:
            m = motif.match(e["id"])
            assert m, e["id"]
            assert (perim[m.group(1)], m.group(2)) == (f.parent.name, f.stem), e["id"]


def test_chargement_par_fichier_memorise_et_sans_liste_vide_muette():
    charge = morceau(APP, "function chargerFichierKb", "const kbComplet")
    assert "kb.promesses.has(cle)" in charge and "kb.promesses.set(cle" in charge, "un fichier n'est lu qu'une fois, même demandé deux fois"
    # erreur à clé des fiches modèles traduite par le dictionnaire du site (L4), message brut sinon
    assert "kb.erreurs.push(`${cle} : ${err && err.cle ? t(err.cle, err.vars) : err.message || err}`)" in charge, \
        "un fichier en échec est signalé, jamais ignoré"
    # L3 : même disposition kb/<p>/<c>.json sur l'ancienne route et dans la génération commune, racine choisie par chemin()
    assert 'lireJson(cheminKb(p, c))' in charge and "`kb/${p}/${c}.json`" in APP and 'adapterKb(d, `kb/${cle}.json`)' in charge
    assert FR["erreur.sans_entrees"] == "fichier sans `entrees`" and 't("erreur.sans_entrees")' in APP
    for champ in ("_sections", "_deprecies", "_ajout", "_texte"):
        assert f"e.{champ} =" in charge, champ
    assert "fusionnerParNomKb(kb.entrees, nouvelles.sort(comparerNomKb))" in charge, "tri alphabétique conservé à chaque fichier reçu"
    assert 'new Intl.Collator("fr")' in APP and "COLLATEUR_KB.compare(String(a.nom), String(b.nom))" in APP
    assert "kb.charges.size === KB_FICHIERS.length" in charge and "delta:kb complet" in charge


def test_les_premiers_fichiers_suffisent_a_la_premiere_page():
    corps = morceau(APP, "async function chargerKb", "/* Chargement par morceaux")
    assert "KB_PRIORITAIRES.flatMap((c) => KB_PERIMETRES.map((p) => chargerFichierKb(p, c)))" in corps
    # le reste part sans être attendu ; attendu seulement si les premiers fichiers n'ont rien donné
    assert "if (kb.entrees.length) chargerResteKb();" in corps and "await kb.reste" in corps
    assert "await chargerResteKb" not in corps
    reste = morceau(APP, "function chargerResteKb", "// ligne d'état du chargement")
    assert "KB_PARALLELE" in reste and "if (kb.reste) return kb.reste;" in reste, "lancé une seule fois"
    assert APP.count("chargerKb()") == 2  # définition et appel de la route Référence seulement


def test_un_filtre_fait_passer_son_fichier_devant():
    req = morceau(APP, "function fichiersRequisKb", "// charge ce qui reste")
    assert "KB_PRODUIT_PERIMETRE[kbFiltre.produit]" in req and "c === kbFiltre.categorie" in req
    res = morceau(APP, "function rendreResultatsKb", "function pageReference")
    assert "fichiersRequisKb().filter" in res and "refaireApresChargementKb(manquants)" in res
    assert 't("kb.provisoire")' in res and FR["kb.provisoire"] == "provisoire, chargement en cours", "compteur annoncé provisoire tant qu'un fichier du filtre manque"
    refait = morceau(APP, "function refaireApresChargementKb", "function rendreResultatsKb")
    assert "clearTimeout(renduKb)" in refait, "plusieurs attentes, un seul nouveau rendu"


def test_indicateur_de_chargement_et_compteurs_exacts_une_fois_tout_charge():
    maj = morceau(APP, "function majChargementKb", "  function filtrerKb")
    assert 't("kb.chargement", { faits: kb.charges.size, total: KB_FICHIERS.length })' in maj
    assert FR["kb.chargement"].startswith("Chargement de la base en arrière-plan : {faits}/{total} fichiers")
    assert "Compteurs et résultats provisoires" in FR["kb.chargement"] and '"aria-busy"' in maj and "(provisoire)" in FR["kb.avancement_provisoire"]
    assert 't(enCommun() ? "kb.erreurs_commun" : "kb.erreurs"' in maj and FR["kb.erreurs"].startswith("Fichiers illisibles : "), "les erreurs de fichiers restent visibles"
    page = morceau(APP, "function pageReference", "const ESSAIS_PAGE")
    assert 'id: "kb-chargement"' in page and 'id: "kb-avancement"' in page and 'role: "status"' in page
    assert "!kb.entrees.length && kbComplet()" in page, "« pas encore publiée » seulement une fois tout lu"
    assert "innerHTML" not in maj


def test_fiche_seule_lit_son_fichier_puis_toute_la_base_en_repli():
    corps = morceau(APP, "async function chargerKb", "    await Promise.all(KB_PRIORITAIRES")
    assert "const f = fichierDeIdKb(etat.kbFicheId);" in corps and "await chargerFichierKb(f[0], f[1]);" in corps
    assert "kb.entrees.some((e) => e.id === etat.kbFicheId)" in corps, "fiche absente de son fichier : toute la base, pour conclure juste"
    assert "return;" in corps  # la fiche seule ne lance pas le reste


def test_les_routes_de_la_reference_sont_inchangees():
    route = morceau(APP, "function lireRoute", "async function rendre")
    assert 'get("recent")' in route and "kbFiltre.depuis = recent" in route
    assert 'params.get("id")' in route and 'params.get("q")' in route
    assert 'case "reference": await chargerKb(); break;' in APP
