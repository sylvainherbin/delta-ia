"""D103 : docs/data/kb/a-tester.json, fichier léger des essais de la base lu par l'onglet « À tester »."""

import hashlib
import json

import pytest

import valider
from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite
from textes_site import FR

CONTEXTE = "# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n"
JOUR = "2026-10-08"
EMPREINTE = hashlib.sha1(CONTEXTE.encode("utf-8")).hexdigest()
CHAMPS = {"id", "produit", "categorie", "nom", "usage", "usage_nature", "exemple", "verdict", "pourquoi", "date_ajout", "essai"}


def entree(nom="resume", ajout="2026-10-05", produit="claude-code", categorie="commandes", verdict="tester", statut="inconnu",
           commentee=True, usage="claude --resume", exemple="claude --resume projet"):
    e = cat.nouvelle_entree(EntreeExtraite(
        produit=produit, categorie=categorie, nom=nom, usage=usage, description_source="Resume a session.",
        url="https://example.org/doc", libelle="Doc", origine="test", usage_nature="syntaxe"), ajout)
    if commentee:
        e["commentee"] = True
        e["description"] = f"Reprend la session du projet {nom} dans le terminal et la remet en route avec son contexte."
        e["contexte_empreinte"] = EMPREINTE
        e["statut_usage"] = statut
        e["recommandation"] = {"verdict": verdict, "pourquoi": f"Pourquoi {nom}."}
        e["exemple"] = exemple
    return e


def base(*entrees):
    return {e["id"]: e for e in entrees}


def test_selection_tri_et_champs():
    ignorer = entree("ignorer", verdict="ignorer")
    attente = entree("attente", commentee=False)
    retiree = entree("retiree")
    retiree["retiree"] = True
    utiliser_deja = entree("deja", verdict="utiliser", statut="utilise")
    utiliser_neuf = entree("neuf", verdict="utiliser", statut="non_utilise", ajout="2026-10-07")
    utiliser_inconnu = entree("inconnu", verdict="utiliser", ajout="2026-10-08")
    tester_ancien = entree("ancien", ajout="2026-08-01")
    tester_deja_utilise = entree("tester-utilise", statut="utilise", ajout="2026-10-01")
    z, a = entree("zeta", ajout="2026-10-06"), entree("alpha", ajout="2026-10-06")
    sans_date = entree("sans-date")
    sans_date["historique"] = []
    doc = cat.construire_a_tester([ignorer, attente, retiree, utiliser_deja, utiliser_neuf, utiliser_inconnu, tester_ancien,
                                   tester_deja_utilise, z, a, sans_date], JOUR)
    assert [e["nom"] for e in doc["entrees"]] == ["alpha", "zeta", "tester-utilise", "ancien", "sans-date", "inconnu", "neuf"], \
        "tester d'abord, puis date d'ajout décroissante (inconnue en dernier), nom à égalité ; utiliser déjà utilisé écarté"
    assert doc["total"] == 7 and doc["tronque"] is False and doc["genere_le"] == JOUR
    assert all(set(e) == CHAMPS for e in doc["entrees"])
    premier = doc["entrees"][0]
    assert premier["verdict"] == "tester" and premier["pourquoi"] == "Pourquoi alpha." and premier["exemple"] == "claude --resume projet"
    assert doc["entrees"][4]["date_ajout"] is None
    assert all(e["essai"] is None for e in doc["entrees"]), "sans kb-essais.yaml, aucun essai déclaré"


def test_plafond_les_utiliser_sont_coupes_en_premier(monkeypatch):
    monkeypatch.setattr(cat, "A_TESTER_MAX", 3)
    entrees = [entree(f"t{i}", ajout=f"2026-10-0{i}") for i in range(1, 4)] + [entree("u", verdict="utiliser", ajout="2026-10-08")]
    doc = cat.construire_a_tester(entrees, JOUR)
    assert [e["nom"] for e in doc["entrees"]] == ["t3", "t2", "t1"]
    assert doc["total"] == 4 and doc["tronque"] is True


def test_vide():
    doc = cat.construire_a_tester([], JOUR)
    assert doc["entrees"] == [] and doc["total"] == 0 and doc["tronque"] is False


def test_ecrire_produit_le_fichier_des_deux_perimetres(tmp_path):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    cat.ecrire(tmp_path, "claude", base(entree("a")))
    assert [e["nom"] for e in json.loads(cat.chemin_a_tester(tmp_path).read_text(encoding="utf-8"))["entrees"]] == ["a"]
    cat.ecrire(tmp_path, "openai", base(entree("b", produit="codex")))
    texte = cat.chemin_a_tester(tmp_path).read_text(encoding="utf-8")
    doc = json.loads(texte)
    assert sorted(e["nom"] for e in doc["entrees"]) == ["a", "b"], "le fichier réunit les deux périmètres"
    assert texte.count("\n") == len(doc["entrees"]) + 2, "une entrée par ligne (diffs git lisibles)"
    assert not list((tmp_path / "docs" / "data" / "kb").glob("*.tmp"))


def test_mise_a_jour_a_blanc_n_ecrit_rien(tmp_path):
    cat.mettre_a_jour(tmp_path, "claude", [], ecrire_fichiers=False)
    assert not cat.chemin_a_tester(tmp_path).exists()


def test_taille_bornee_sur_la_base_publiee():
    """Sur la vraie base (lecture seule), le fichier reste léger : quelques centaines d'essais, loin de la base complète."""
    entrees = [e for per in ("claude", "openai") for e in cat.charger(RACINE, per).values()]
    doc = cat.construire_a_tester(entrees, JOUR)
    taille = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert 0 < len(doc["entrees"]) <= cat.A_TESTER_MAX
    assert taille < 200_000, taille
    base_complete = sum(f.stat().st_size for f in (RACINE / "docs" / "data" / "kb").glob("*/*.json"))
    assert taille < base_complete / 10
    publie = cat.chemin_a_tester(RACINE)
    if publie.exists():  # le fichier commité par les passages respecte lui aussi la borne
        assert publie.stat().st_size < 200_000


# ----------------------------------------------------------------------------------------------- D119 : kb-essais.yaml

def declarer(racine, texte):
    (racine / cat.ESSAIS_FICHIER).write_text(texte, encoding="utf-8")


def test_lire_essais_absent_vide_et_plus_recent(tmp_path):
    assert cat.lire_essais(tmp_path) == {}
    declarer(tmp_path, "")
    assert cat.lire_essais(tmp_path) == {}
    declarer(tmp_path, "- {date: 2026-10-11, id: claude-code-commandes-a, par: m-9871226c4940, rapport: rapports/r.md}\n"
                       "- {date: '2026-10-09', id: claude-code-commandes-a, par: m-ancienne}\n"
                       "- {date: '2026-10-10', id: claude-code-commandes-b, par: session:Design}\n")
    assert cat.lire_essais(tmp_path) == {
        "claude-code-commandes-a": {"date": "2026-10-11", "par": "m-9871226c4940", "rapport": "rapports/r.md"},
        "claude-code-commandes-b": {"date": "2026-10-10", "par": "session:Design", "rapport": None}}


@pytest.mark.parametrize("texte, attendu", [
    ("{date: 2026-10-11}", "liste de déclarations"),
    ("- {date: hier, id: x, par: m-1}", "date AAAA-MM-JJ"),
    ("- {date: 2026-10-11, id: 'Pas Un Id', par: m-1}", "id de fiche"),
    ("- {date: 2026-10-11, id: x, par: 'deux mots'}", "`par`"),
    ("- {date: 2026-10-11, id: x, par: m-1, fait: true}", "{date, id, par, rapport}"),
    ("- {date: 2026-10-11, id: x, par: m-1, rapport: ''}", "`rapport`"),
    ("- [", "YAML invalide"),
])
def test_lire_essais_refuse_une_declaration_mal_formee(tmp_path, texte, attendu):
    declarer(tmp_path, texte)
    with pytest.raises(ValueError, match=attendu.replace("{", r"\{").replace("}", r"\}")):
        cat.lire_essais(tmp_path)


def test_essai_declare_porte_dans_a_tester_sans_toucher_la_fiche(tmp_path):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    a, b = entree("a"), entree("b", verdict="utiliser")
    declarer(tmp_path, f"- {{date: '2026-10-11', id: {a['id']}, par: m-9871226c4940, rapport: rapports/r.md}}\n")
    cat.ecrire(tmp_path, "claude", base(a, b))
    doc = json.loads(cat.chemin_a_tester(tmp_path).read_text(encoding="utf-8"))
    essais = {e["nom"]: e["essai"] for e in doc["entrees"]}
    assert essais == {"a": "2026-10-11", "b": None}, "la date seule est publiée"
    r = valider.Rapport()
    valider.verifier_organisation_privee(tmp_path, r)
    assert r.erreurs == [], "D77 : ni l'id de mission ni le rapport ne passent dans docs/data"
    fiche = cat.charger(tmp_path, "claude")[a["id"]]
    assert fiche["statut_usage"] == "inconnu" and "essai" not in fiche, "D69 : un essai ne change ni la fiche ni statut_usage"


def test_declaration_mal_formee_n_arrete_pas_le_passage(tmp_path, capsys):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    declarer(tmp_path, "- {date: hier, id: x, par: m-1}\n")
    cat.ecrire(tmp_path, "claude", base(entree("a")))
    doc = json.loads(cat.chemin_a_tester(tmp_path).read_text(encoding="utf-8"))
    assert [e["essai"] for e in doc["entrees"]] == [None]
    assert "écrit sans les essais déclarés" in capsys.readouterr().err


def test_id_inconnu_signale_sans_bloquer(tmp_path, capsys):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    declarer(tmp_path, "- {date: '2026-10-11', id: claude-code-commandes-fantome, par: m-1}\n")
    cat.ecrire(tmp_path, "claude", base(entree("a")))
    assert "id inconnus dans la base : claude-code-commandes-fantome" in capsys.readouterr().err


def test_declaration_du_depot_valide_et_connue():
    """Le fichier du dépôt se lit, et chaque id déclaré existe dans la base."""
    essais = cat.lire_essais(RACINE)
    ids = {k for per in ("claude", "openai") for k in cat.charger(RACINE, per)}
    assert set(essais) <= ids, sorted(set(essais) - ids)


# ----------------------------------------------------------------------------------------------- valider.py --kb

def racine_valide(tmp_path, *entrees):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    cat.ecrire(tmp_path, "claude", base(*entrees))
    return ["--perimetre", "claude", "--racine", str(tmp_path), "--kb"]


def test_valider_accepte_le_fichier_produit_et_son_absence(tmp_path):
    args = racine_valide(tmp_path, entree("a"), entree("b", verdict="utiliser"))
    assert valider.main(args) == 0
    cat.chemin_a_tester(tmp_path).unlink()
    assert valider.main(args) == 0


def modifier(tmp_path, fn):
    chemin = cat.chemin_a_tester(tmp_path)
    doc = json.loads(chemin.read_text(encoding="utf-8"))
    fn(doc)
    chemin.write_text(json.dumps(doc), encoding="utf-8")


@pytest.mark.parametrize("modif, attendu", [
    (lambda d: d["entrees"][0].update(id="claude-code-commandes-fantome"), "absent de la base claude"),
    (lambda d: d["entrees"].reverse(), "trier par verdict"),
    (lambda d: d["entrees"][0].update(verdict="ignorer"), "`verdict` doit valoir tester ou utiliser"),
    (lambda d: d["entrees"][0].update(date_ajout="hier"), "`date_ajout`"),
    (lambda d: d["entrees"][0].pop("pourquoi"), "champs inattendus ou manquants"),
    (lambda d: d["entrees"][0].update(pourquoi=3), "`pourquoi`"),
    (lambda d: d.update(tronque=True), "`tronque`"),
    (lambda d: d.update(total=0), "`total`"),
    (lambda d: d.update(entrees="x"), "liste `entrees`"),
    (lambda d: d["entrees"][0].update(essai="hier"), "`essai` doit valoir null"),
    (lambda d: d["entrees"][0].update(essai={"date": "2026-10-11"}), "`essai` doit valoir null"),
    (lambda d: d["entrees"][0].update(essai=True), "`essai` doit valoir null"),
])
def test_valider_refuse_un_fichier_incoherent(tmp_path, capsys, modif, attendu):
    args = racine_valide(tmp_path, entree("a", ajout="2026-10-07"), entree("b", ajout="2026-10-05"), entree("c", verdict="utiliser"))
    modifier(tmp_path, modif)
    assert valider.main(args) == 1
    assert attendu in capsys.readouterr().err


def test_valider_accepte_un_essai_declare_et_un_fichier_d_avant_d119(tmp_path):
    a = entree("a")
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    declarer(tmp_path, f"- {{date: '2026-10-11', id: {a['id']}, par: m-9871226c4940, rapport: rapports/r.md}}\n")
    args = racine_valide(tmp_path, a)
    assert valider.main(args) == 0
    modifier(tmp_path, lambda d: [e.pop("essai") for e in d["entrees"]])
    assert valider.main(args) == 0, "le fichier publié avant D119 reste valide jusqu'au passage suivant"


def test_valider_refuse_une_declaration_mal_formee(tmp_path, capsys):
    args = racine_valide(tmp_path, entree("a"))
    declarer(tmp_path, "- {date: hier, id: x, par: m-1}\n")
    assert valider.main(args) == 1
    assert "kb-essais.yaml" in capsys.readouterr().err


def test_valider_refuse_un_depassement_du_plafond(tmp_path, capsys, monkeypatch):
    args = racine_valide(tmp_path, entree("a"), entree("b"))
    monkeypatch.setattr(cat, "A_TESTER_MAX", 1)
    assert valider.main(args) == 1
    assert "plafond" in capsys.readouterr().err


# ----------------------------------------------------------------------------------------------- site et chaîne

def app_js():
    return (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")


def test_onglet_lit_a_tester_json_et_non_la_base():
    app = app_js()
    charge = app[app.index("async function chargerATesterKb"):app.index("async function chargerKb")]
    assert 'lireJson(chemin("kb/a-tester.json"))' in charge and "etat.kbATester = null" in charge, "repli silencieux si le fichier manque"
    assert "if (enCommun()) { etat.kbATester = null; return null; }" in charge, "L3 : couche personnelle, jamais lue sur la référence commune"
    assert "console" not in charge and "chargerKb" not in charge
    section = app[app.index("function carteEssai"):app.index("function pageArchives")]
    assert "etat.kb." not in section and "etat.kb)" not in section, "l'onglet ne charge ni n'utilise la base complète"
    assert 'case "a-tester": await chargerATesterKb(); break;' in app
    assert app.count("chargerKb()") == 2  # définition et appel de la route Référence seulement


def test_section_essais_sous_les_actions_avec_la_meme_case_fait():
    app = app_js()
    page = app[app.index("function pageATester"):app.index("function pageArchives")]
    assert page.index('t("atester.ouvertes", { n: ouvertes.length })') < page.index("sectionEssais(etat.kbATester)"), "sous les actions"
    assert "etat.kbATester && etat.kbATester.entrees.length" in page, "section omise si le fichier manque ou est vide"
    carte = app[app.index("function carteEssai"):app.index("function sectionEssais")]
    assert "lireFaits()" in carte and "ecrireFait(id, caseFait.checked)" in carte, "même stockage local que les actions"
    for champ in ("e.usage", "e.exemple", "e.pourquoi", "e.date_ajout"):
        assert champ in carte, champ
    assert 'el("pre", { class: "usage"' in carte and "el(\"code\"" in carte, "usage et exemple en code"
    assert "innerHTML" not in carte and "innerHTML" not in app[app.index("function sectionEssais"):app.index("function pageATester")]


def test_essai_declare_coche_sans_geste_sur_le_site():
    """D119 : un essai déclaré par une mission compte comme fait, case cochée et figée, provenance affichée."""
    app = app_js()
    carte = app[app.index("function essaiDeclare"):app.index("function sectionEssais")]
    assert 'ISO_JOUR.test(e.essai || "")' in carte
    assert 'disabled: true' in carte and "caseFait.checked = true" in carte
    assert 't("essai.fait_mission", { date: dateAffichee(declare) })' in carte and FR["essai.fait_mission"] == "Fait le {date} pendant une mission"
    section = app[app.index("function sectionEssais"):app.index("function pageATester")]
    assert "!essaiFait(e, faits)" in section and "entrees.filter((e) => essaiFait(e, faits))" in section
    section = app[app.index("function sectionEssais"):app.index("function pageATester")]
    assert 't("essais.titre", { n: ouverts.length })' in section and 't("essais.faits", { n: faitsListe.length })' in section
    assert FR["essais.titre"] == "Essais de la base ({n})" and FR["essais.faits"] == "Essais faits ({n})"
    assert "ouverts.slice(0, etat.essaisLimite)" in section, "affichage borné"


def test_chaque_etape_de_la_chaine_connait_a_tester_json():
    import garde
    import orchestrateur as orc
    f = "docs/data/kb/a-tester.json"
    for etape, chemins in garde.CHEMINS_ETAPE.items():
        assert f in chemins, etape
    e = {x.nom: x for x in orc.construire_etapes(orc.charger_config(), RACINE)}
    for n in ("delta", "codex-delta", "delta-kb", "codex-delta-kb"):
        assert f in e[n].checkout and f in e[n].clean, n
    settings = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    assert f"Bash(git add docs/data/kb/claude docs/data/kb/recent.json {f} docs/data/kb/noms.json)" in settings
    for fichier in (".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta/SKILL.md",
                    ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md", "prompts/codex-delta-kb.md",
                    "CLAUDE.md", "AGENTS.md", "SPEC.md"):
        assert f in (RACINE / fichier).read_text(encoding="utf-8"), fichier
