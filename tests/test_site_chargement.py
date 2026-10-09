"""Aujourd'hui d'abord, le reste ensuite (D111, m-e6c49a1336e3) : ce que le premier affichage lit, le fond, l'attente des onglets de
fenêtre, une seule lecture par fichier."""

from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
APP = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")


def morceau(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i + len(debut))]


def test_aujourdhui_ne_lit_que_le_dernier_jour_les_quotas_et_les_outils():
    page = morceau(APP, "async function chargerDeLaPage", "async function rendre")
    assert 'case "aujourdhui": await Promise.all([chargerDernierJour(), chargerVersions(), chargerComptes()]); break;' in page
    dernier = morceau(APP, "async function chargerDernierJour", "// Archives")
    assert "derniereDate(p)" in dernier and "datesRecentes" not in dernier, "le dernier jour, pas les 30"
    assert "chargerNecessaire" not in APP
    demarrer = morceau(APP, "async function demarrer", "demarrer();")
    assert demarrer.index("chargerComptes(); chargerVersions();") < demarrer.index("await chargerIndex()"), "etat.json et versions.json partent avec les index"


def test_le_fond_lit_les_noms_puis_les_trente_jours_hors_reference():
    fond = morceau(APP, "function lancerFond", "// texte rendu avant")
    assert 'if (etat.page === "reference") return;' in fond
    assert fond.index("chargerNomsKb()") < fond.index("chargerFenetre()")
    rendre = morceau(APP, "async function rendre", "async function demarrer")
    assert "lancerFond();" in rendre and rendre.index("document.title") < rendre.index("lancerFond();"), "après le premier affichage"
    fen = morceau(APP, "function chargerFenetre", "function pageAttenteFenetre")
    assert "if (etat.fenetre) return etat.fenetre;" in fen, "une seule fois"
    assert "datesRecentes(p)" in fen and "FOND_PARALLELE" in fen and "chargerJour(p, d)" in fen


def test_changelogs_actu_et_a_tester_attendent_avec_un_indicateur():
    assert 'const PAGES_FENETRE = { changelogs: "Changelogs", actu: "Actu IA", "a-tester": "À tester" };' in APP
    rendre = morceau(APP, "async function rendre", "async function demarrer")
    assert "PAGES_FENETRE[etat.page] ? chargerFenetre() : null" in rendre and "pageAttenteFenetre(fenetre)" in rendre
    assert "await Promise.all([chargerDeLaPage(), fenetre && fenetre.termine]);" in rendre
    attente = morceau(APP, "function pageAttenteFenetre", "// après le premier affichage")
    assert 'role: "status"' in attente and '"aria-busy": "true"' in attente and 'id: "fenetre-avancement"' in attente
    assert "n'a pas à attendre" not in APP and "innerHTML" not in attente
    # Semaine et Archives n'attendent pas les 30 jours
    assert "semaine" not in PAGES_FENETRE_CLES() and "archives" not in PAGES_FENETRE_CLES()


def PAGES_FENETRE_CLES():
    return morceau(APP, "const PAGES_FENETRE", "};")


def test_un_fichier_n_est_lu_qu_une_fois():
    base = morceau(APP, "const lectures = new Map();", "async function lireJson")
    assert "if (!lectures.has(cle)) lectures.set(cle, lire());" in base
    for cle in ('unefois(`jour:${cle}`', 'unefois("comptes"', 'unefois("versions"', 'unefois("kb-recent"', 'unefois("kb-a-tester"',
                'unefois("kb-noms"', 'unefois("semaine-index"', 'unefois(`semaine:${semaine}`'):
        assert cle in APP, cle
    assert "etat.rendu" in morceau(APP, "async function rendre", "async function demarrer") and "if (mien !== etat.rendu) return;" in APP


def test_texte_rendu_avant_les_noms_est_complete_sur_place():
    enr = morceau(APP, "function enrichi", "\n  }\n")
    assert 'etat.noms === undefined && t.includes("`")' in enr and '"data-enrichir": t' in enr
    lien = morceau(APP, "function completerLiens", "\n  }\n")
    assert 'span[data-enrichir]' in lien and "replaceWith(...enrichi(" in lien and "innerHTML" not in lien
    assert '"data-produit": typeof produit === "string" ? produit : null' in enr and 's.getAttribute("data-produit")' in lien, "le produit de l'élément (D110) suit le texte"
