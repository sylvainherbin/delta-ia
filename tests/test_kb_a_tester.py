"""D103 : docs/data/kb/a-tester.json, fichier léger des essais de la base lu par l'onglet « À tester »."""

import hashlib
import json

import pytest

import valider
from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite

CONTEXTE = "# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n"
JOUR = "2026-10-08"
EMPREINTE = hashlib.sha1(CONTEXTE.encode("utf-8")).hexdigest()
CHAMPS = {"id", "produit", "categorie", "nom", "usage", "usage_nature", "exemple", "verdict", "pourquoi", "date_ajout"}


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
])
def test_valider_refuse_un_fichier_incoherent(tmp_path, capsys, modif, attendu):
    args = racine_valide(tmp_path, entree("a", ajout="2026-10-07"), entree("b", ajout="2026-10-05"), entree("c", verdict="utiliser"))
    modifier(tmp_path, modif)
    assert valider.main(args) == 1
    assert attendu in capsys.readouterr().err


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
    assert 'lireJson("data/kb/a-tester.json")' in charge and "etat.kbATester = null" in charge, "repli silencieux si le fichier manque"
    assert "console" not in charge and "chargerKb" not in charge
    section = app[app.index("function carteEssai"):app.index("function pageArchives")]
    assert "etat.kb." not in section and "etat.kb)" not in section, "l'onglet ne charge ni n'utilise la base complète"
    assert 'if (etat.page === "a-tester") await chargerATesterKb();' in app
    assert app.count("chargerKb()") == 2  # définition et appel de la route Référence seulement


def test_section_essais_sous_les_actions_avec_la_meme_case_fait():
    app = app_js()
    page = app[app.index("function pageATester"):app.index("function pageArchives")]
    assert page.index("Actions ouvertes (${ouvertes.length})") < page.index("sectionEssais(etat.kbATester)"), "sous les actions"
    assert "etat.kbATester && etat.kbATester.entrees.length" in page, "section omise si le fichier manque ou est vide"
    carte = app[app.index("function carteEssai"):app.index("function sectionEssais")]
    assert "lireFaits()" in carte and "ecrireFait(id, caseFait.checked)" in carte, "même stockage local que les actions"
    for champ in ("e.usage", "e.exemple", "e.pourquoi", "e.date_ajout"):
        assert champ in carte, champ
    assert 'el("pre", { class: "usage"' in carte and "el(\"code\"" in carte, "usage et exemple en code"
    assert "innerHTML" not in carte and "innerHTML" not in app[app.index("function sectionEssais"):app.index("function pageATester")]
    section = app[app.index("function sectionEssais"):app.index("function pageATester")]
    assert "Essais de la base (${ouverts.length})" in section and "Essais faits (${faitsListe.length})" in section
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
