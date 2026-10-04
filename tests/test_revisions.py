"""D76 : signatures volatiles, diff utile et cache lié au seul état validé, sans réseau."""

import hashlib
from dataclasses import replace
from datetime import date

import pytest

import fetch
from conftest import FIXTURES, FauxClient, ecrire_quotidien
from deltalib.analyseurs.html_notes import parser_sections_suivies
from deltalib.etat import charger_etat, ecrire_json
from deltalib.kb.documentation import DocSource, empreinte, recuperer
from deltalib.modeles import empreinte_contenu
from deltalib.passage import executer
from deltalib.revisions import MAX_CARACTERES, chemin_cache, comparer_phrases, ecrire_cache, textes_precedents
from deltalib.textes import normaliser_contenu

PAGE = (FIXTURES / "aide_usage_credits.md").read_text(encoding="utf-8")
JOUR = "2026-10-04"
VIDE = {"ajoutees": [], "retirees": [], "modifiees": []}


@pytest.mark.parametrize("texte", ["", "\n Texte  inchangé.\t\n\n Une autre ligne. \n",
                                  "[Voir](https://exemple.test/page?surface=cli&lang=fr#quota)",
                                  "![Image](https://exemple.test/image.png?width=200)",
                                  "## Un titre\n\n- Premier point.\n- Deuxième point."])
def test_empreintes_sans_url_volatile_strictement_inchangees(texte):
    assert empreinte_contenu(texte) == hashlib.sha1(texte.strip().encode()).hexdigest()[:16]
    assert empreinte(texte) == hashlib.sha1(texte.encode()).hexdigest()[:16]


@pytest.mark.parametrize("parametre", ["expires", "SIGNATURE", "req", "sig", "token", "X-Amz-Signature",
                                      "X-Amz-Expires", "X-Goog-Credential", "Policy", "Key-Pair-Id"])
@pytest.mark.parametrize("lien", ["![]({url})", "[Lien]({url})", '<img src="{url}">', '<a href="{url}">Lien</a>'])
def test_url_signee_entierement_normalisee(parametre, lien):
    avant = lien.format(url=f"https://exemple.test/image.png?width=200&amp;{parametre}=factice#image")
    apres = lien.format(url=f"https://exemple.test/image.png?width=200&amp;{parametre}=autre-factice#image")
    attendu = lien.format(url="https://exemple.test/image.png#image")
    assert normaliser_contenu(avant) == attendu
    assert normaliser_contenu(attendu) == attendu
    assert empreinte_contenu(avant) == empreinte_contenu(apres)
    assert empreinte(avant) == empreinte(apres)


def test_fixture_reelle_sans_jeton_et_intercom_stable():
    assert "expires=factice&amp;signature=factice&amp;req=factice" in PAGE
    autre = PAGE.replace("=factice", "=autre-factice")
    assert PAGE != autre and empreinte_contenu(PAGE) == empreinte_contenu(autre)
    assert empreinte(PAGE) == empreinte(autre)
    assert normaliser_contenu(" une  phrase\n\t suite ", reduire_blancs=True) == "une phrase suite"


def test_base_ne_signale_pas_une_nouvelle_signature(tmp_path):
    doc = DocSource("credits", "claude", "claude", "pages", "ok", base="https://exemple.test/",
                    options={"pages": {"credits": {}}})
    url = doc.fichiers()["page:credits"]
    def lire(page):
        return recuperer(tmp_path, [doc], lambda: FauxClient({url: (page, "text/markdown")}))
    assert lire(PAGE)["nouvelles"] == ["credits/page:credits"]
    assert lire(PAGE.replace("=factice", "=autre-factice"))["modifiees"] == []
    assert lire(PAGE.replace("$2000", "$3000"))["modifiees"] == ["credits/page:credits"]


def test_diff_phrases_ajoutee_retiree_modifiee():
    avant = "Le plafond quotidien est de 2000 dollars. Les exports CSV sont disponibles."
    apres = "Le plafond quotidien est de 3000 dollars. Un mode sombre est proposé."
    assert comparer_phrases(avant, apres) == {
        "ajoutees": ["Un mode sombre est proposé."],
        "retirees": ["Les exports CSV sont disponibles."],
        "modifiees": [{"avant": "Le plafond quotidien est de 2000 dollars.",
                       "apres": "Le plafond quotidien est de 3000 dollars."}],
    }


@pytest.mark.parametrize("avant,apres", [
    ("Une  phrase\ncontinue. La suite.", "Une phrase continue.\n\nLa suite."),
    ("## Titre\n\n**Un texte.**", "# Titre\n\nUn texte."),
    ("- Premier point.\n- Deuxième point.", "1. Premier point.\n2. Deuxième point."),
    ("Un texte.\n\n![](https://exemple.test/a.png)", "Un texte.\n\n![](https://exemple.test/b.png)"),
    ("Un texte.\n\nUpdated yesterday", "Un texte.\n\nUpdated 2 days ago"),
    ("Mis à jour le 3 octobre 2026\nUn texte.", "Mis à jour il y a 2 jours\nUn texte."),
    ("Updated on October 3, 2026\nUn texte.", "Updated on October 4, 2026\nUn texte."),
    ("2026-10-03\nUn texte.", "2026-10-04\nUn texte."),
])
def test_forme_et_dates_seules_ne_donnent_aucun_changement(avant, apres):
    assert comparer_phrases(avant, apres) == VIDE


@pytest.mark.parametrize("avant,apres", [
    ("Updated pricing: credits expire after six months.", "Updated pricing: credits expire after three months."),
    ("La promotion se termine le 3 octobre 2026.", "La promotion se termine le 4 octobre 2026."),
    ("[Documentation](https://exemple.test/a)", "[Documentation](https://exemple.test/b)"),
])
def test_date_metier_et_url_de_lien_restent_des_changements(avant, apres):
    assert comparer_phrases(avant, apres)["modifiees"] == [{"avant": avant, "apres": apres}]


@pytest.mark.parametrize("cle", ["ajoutees", "retirees", "modifiees"])
def test_diff_borne_chaque_liste(cle):
    phrases = [f"La fonctionnalité numéro {i} est disponible." for i in range(25)]
    texte = "\n\n".join(phrases)
    avant, apres = {"ajoutees": ("", texte), "retirees": (texte, ""),
                    "modifiees": (texte, texte.replace("disponible", "indisponible"))}[cle]
    res = comparer_phrases(avant, apres)
    assert len(res[cle]) == 20 and res["tronque"] is True


def test_diff_borne_la_longueur_des_phrases():
    res = comparer_phrases("", "mot " * MAX_CARACTERES)
    assert len(res["ajoutees"][0]) == MAX_CARACTERES and res["tronque"] is True


@pytest.fixture
def source(sources):
    s = sources["claude-aide-credits"]
    return replace(s, options={k: v for k, v in s.options.items() if k != "etat_initial"})


def element(source, texte=PAGE):
    return parser_sections_suivies(texte, source)[0]


def etat_initial(racine, source, texte=PAGE, ancien=False):
    e = element(source, texte)
    h = hashlib.sha1(e.contenu.strip().encode()).hexdigest()[:16] if ancien else empreinte_contenu(e.contenu)
    etat = {"version": 1, "maj_le": "2026-10-03T12:00:00+00:00",
            "vus": {e.id: {"empreinte": h, "source_id": e.source_id}}}
    ecrire_json(racine / "state/claude.json", etat)
    return e, etat


def passage(racine, source, texte=PAGE):
    return executer("claude", [source], racine / "state/claude.json",
                    FauxClient({source.url: (texte, "text/markdown")}), aujourd_hui_=date.fromisoformat(JOUR)).en_dict()


def archive(racine, e, nom="2026-10-03/claude-nouveautes-040000.json"):
    p = racine / "raw/historique" / nom
    ecrire_json(p, {"perimetre": "claude", "nouveautes": [e.en_dict()]})
    return p


@pytest.mark.parametrize("ancien", [False, True])
def test_amorcage_depuis_historique_sans_ecriture(tmp_path, source, ancien):
    e, etat = etat_initial(tmp_path, source, ancien=ancien)
    archive(tmp_path, e)
    archive(tmp_path, element(source, PAGE.replace("$2000", "$4000")), "2026-10-04/claude-nouveautes-040000.json")
    mauvais = tmp_path / "raw/historique/2026-10-04/claude-nouveautes-040001.json"
    mauvais.write_text("JSON tronqué")
    brut = passage(tmp_path, source, PAGE.replace("$2000", "$3000"))
    rev = brut["nouveautes"][0]
    assert rev["revision"] and rev["changements"]["modifiees"] == [
        {"avant": "Note: There is a daily redemption limit of $2000.",
         "apres": "Note: There is a daily redemption limit of $3000."}]
    assert not (tmp_path / "raw/revisions").exists()
    assert charger_etat(tmp_path / "state/claude.json") == etat


def test_archive_la_plus_recente_correspondant_a_l_etat(tmp_path, source):
    e, etat = etat_initial(tmp_path, source)
    archive(tmp_path, e)
    # Même empreinte normalisée, mais signature différente et collisions de seconde D72.
    dernier = element(source, PAGE.replace("=factice", "=autre-factice"))
    archive(tmp_path, dernier, "2026-10-04/claude-nouveautes-040000-10.json")
    textes = textes_precedents(tmp_path, "claude", {e.id: etat["vus"][e.id]["empreinte"]})
    assert textes == {e.id: normaliser_contenu(dernier.contenu).strip()}


def test_cache_en_avance_sur_etat_est_ecarte(tmp_path, source):
    e, _ = etat_initial(tmp_path, source)
    archive(tmp_path, e)
    ecrire_cache(tmp_path, "claude", e.id, element(source, PAGE.replace("$2000", "$4000")).contenu)
    brut = passage(tmp_path, source, PAGE.replace("$2000", "$3000"))
    assert "$2000" in brut["nouveautes"][0]["changements"]["modifiees"][0]["avant"]


def test_revision_sans_precedent_reste_explicite(tmp_path, source):
    etat_initial(tmp_path, source)
    brut = passage(tmp_path, source, PAGE.replace("$2000", "$3000"))
    assert brut["nouveautes"][0]["revision"] is True
    assert brut["nouveautes"][0]["changements"] is None


def test_sans_historique_la_signature_ne_redonne_pas_une_alerte_apres_validation(tmp_path, source):
    etat_initial(tmp_path, source, ancien=True)
    brut = passage(tmp_path, source, PAGE.replace("=factice", "=autre-factice"))
    assert brut["nouveautes"][0]["changements"] is None
    valider_brut(tmp_path, brut)
    assert passage(tmp_path, source, PAGE.replace("=factice", "=troisieme-factice"))["nouveautes"] == []


@pytest.mark.parametrize("changer", [lambda s: s.replace("=factice", "=autre-factice"),
                                     lambda s: s.replace("**Note:**", "Note:").replace("There is", "There  is"),
                                     lambda s: s + "\n\nUpdated yesterday"])
def test_revision_de_forme_ignoree_puis_validee(tmp_path, source, changer):
    e, etat = etat_initial(tmp_path, source, ancien=True)
    archive(tmp_path, e)
    page = changer(PAGE)
    brut = passage(tmp_path, source, page)
    assert brut["nouveautes"] == [] and brut["ignores"] == [e.id]
    assert brut["ignores_raisons"] == {e.id: "revision_de_forme"}
    assert charger_etat(tmp_path / "state/claude.json") == etat
    valider_brut(tmp_path, brut)
    assert charger_etat(tmp_path / "state/claude.json")["vus"][e.id]["empreinte"] == empreinte_contenu(element(source, page).contenu)
    assert chemin_cache(tmp_path, "claude", e.id).read_text() == normaliser_contenu(element(source, page).contenu).strip()
    suivant = passage(tmp_path, source, page.replace("=factice", "=autre-factice"))
    assert suivant["nouveautes"] == [] and suivant["ignores"] == []


def valider_brut(racine, brut, *, couvrir=None, ecarter=(), dry_run=False, attendu=0):
    ecrire_json(racine / "raw/claude-nouveautes.json", brut)
    ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=couvrir, ecarter=ecarter)
    args = ["--racine", str(racine), "--perimetre", "claude", "--valider", "--date", JOUR]
    assert fetch.main(args + (["--dry-run"] if dry_run else [])) == attendu


@pytest.mark.parametrize("mode", ["couverte", "ecartee", "etat_initial", "deja_vue"])
def test_cache_ecrit_uniquement_a_valider(tmp_path, source, mode):
    e = element(source)
    if mode == "etat_initial":
        source = replace(source, options={**source.options, "etat_initial": "État initial"})
    elif mode == "deja_vue":
        etat_initial(tmp_path, source)
    brut = passage(tmp_path, source)
    cible = chemin_cache(tmp_path, "claude", e.id)
    assert not cible.exists()
    valider_brut(tmp_path, brut, dry_run=True)
    assert not cible.exists()
    valider_brut(tmp_path, brut, ecarter=[e.id] if mode == "ecartee" else ())
    assert cible.read_text() == normaliser_contenu(e.contenu).strip()
    assert "signature=" not in cible.read_text()
    assert passage(tmp_path, source)["nouveautes"] == []


def test_nouveaute_en_attente_ne_remplace_pas_le_cache(tmp_path, source):
    e, _ = etat_initial(tmp_path, source)
    ecrire_cache(tmp_path, "claude", e.id, e.contenu)
    brut = passage(tmp_path, source, PAGE.replace("$2000", "$3000"))
    valider_brut(tmp_path, brut, couvrir=[], attendu=4)
    assert chemin_cache(tmp_path, "claude", e.id).read_text() == normaliser_contenu(e.contenu).strip()
    assert passage(tmp_path, source, PAGE.replace("$2000", "$3000"))["nouveautes"][0]["changements"] == brut["nouveautes"][0]["changements"]


def test_echec_ecriture_cache_n_avance_pas_etat_sur_disque(tmp_path, source, monkeypatch):
    import deltalib.etat as etat
    _, initial = etat_initial(tmp_path, source)
    brut = passage(tmp_path, source, PAGE.replace("$2000", "$3000"))
    def refuser(*args):
        raise OSError("disque plein (simulé)")
    monkeypatch.setattr(etat, "ecrire_cache", refuser)
    with pytest.raises(OSError, match="disque plein"):
        valider_brut(tmp_path, brut)
    assert charger_etat(tmp_path / "state/claude.json") == initial


def test_cache_invalide_ou_absent_dans_les_archives_donne_null(tmp_path, source):
    e, _ = etat_initial(tmp_path, source)
    ecrire_cache(tmp_path, "claude", e.id, "Un texte ne correspondant pas à l'état.")
    archive(tmp_path, element(source, PAGE.replace("$2000", "$4000")))
    assert passage(tmp_path, source, PAGE.replace("$2000", "$3000"))["nouveautes"][0]["changements"] is None


@pytest.mark.parametrize("ident", ["../../ailleurs", "https://exemple.test/" + "a" * 400])
def test_cache_reste_dans_son_perimetre(tmp_path, ident):
    ecrire_cache(tmp_path, "openai", ident, "Un texte.")
    cible = chemin_cache(tmp_path, "openai", ident)
    assert cible.parent == tmp_path / "raw/revisions/openai"
    assert cible.read_text() == "Un texte."
