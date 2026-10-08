"""D99 : docs/data/kb/recent.json, fichier léger des ajouts récents lu par l'onglet Aujourd'hui."""

import json

import pytest

import valider
from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite

CONTEXTE = "# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n"
JOUR = "2026-10-08"


def entree(nom="resume", ajout="2026-10-05", produit="claude-code", categorie="commandes", commentee=False, verdict="tester", usage="claude --resume"):
    e = cat.nouvelle_entree(EntreeExtraite(
        produit=produit, categorie=categorie, nom=nom, usage=usage, description_source="Resume a session.",
        url="https://example.org/doc", libelle="Doc", origine="test", usage_nature="syntaxe"), ajout)
    if commentee:
        e["commentee"] = True
        e["recommandation"] = {"verdict": verdict, "pourquoi": "Reprise des sessions du projet de veille."}
        e["exemple"] = "claude --resume projet"
    return e


def base(*entrees):
    return {e["id"]: e for e in entrees}


def test_fenetre_tri_et_champs():
    vieille = entree("vieille", ajout="2026-09-08")      # 30 jours exactement : dedans
    trop_vieille = entree("trop-vieille", ajout="2026-09-07")
    retiree = entree("retiree", ajout="2026-10-07")
    retiree["retiree"] = True
    futur = entree("futur", ajout="2026-10-09")
    z, a, b = entree("zeta", ajout="2026-10-07"), entree("alpha", ajout="2026-10-07"), entree("bravo", ajout="2026-10-08", commentee=True)
    sans_date = entree("sans-date")
    sans_date["historique"] = []
    doc = cat.construire_recent([vieille, trop_vieille, retiree, futur, z, a, b, sans_date], JOUR)
    assert [e["nom"] for e in doc["entrees"]] == ["bravo", "alpha", "zeta", "vieille"]
    assert doc["total"] == 4 and doc["tronque"] is False and doc["plus_ancienne"] == "2026-09-08"
    assert doc["genere_le"] == JOUR and doc["fenetre_jours"] == 30
    assert set(doc["entrees"][0]) == {"id", "produit", "categorie", "nom", "usage", "usage_nature", "exemple", "verdict", "date_ajout"}
    assert doc["entrees"][0]["verdict"] == "tester" and doc["entrees"][0]["exemple"] == "claude --resume projet"
    assert doc["entrees"][1]["verdict"] is None and doc["entrees"][1]["exemple"] is None  # non commentée : pas de verdict


def test_plafond_et_coupe(monkeypatch):
    monkeypatch.setattr(cat, "RECENT_MAX", 3)
    entrees = [entree(f"c{i}", ajout=f"2026-10-0{i}") for i in range(1, 7)]
    doc = cat.construire_recent(entrees, JOUR)
    assert [e["nom"] for e in doc["entrees"]] == ["c6", "c5", "c4"]
    assert doc["total"] == 6 and doc["tronque"] is True and doc["plus_ancienne"] == "2026-10-04"


def test_vide():
    doc = cat.construire_recent([], JOUR)
    assert doc["entrees"] == [] and doc["total"] == 0 and doc["tronque"] is False and doc["plus_ancienne"] is None


def test_ecrire_produit_le_fichier_des_deux_perimetres(tmp_path):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    aujourd_hui = cat.date.today().isoformat()
    cat.ecrire(tmp_path, "claude", base(entree("a", ajout=aujourd_hui)))
    assert [e["nom"] for e in json.loads(cat.chemin_recent(tmp_path).read_text(encoding="utf-8"))["entrees"]] == ["a"]
    cat.ecrire(tmp_path, "openai", base(entree("b", ajout=aujourd_hui, produit="codex")))
    texte = cat.chemin_recent(tmp_path).read_text(encoding="utf-8")
    doc = json.loads(texte)
    assert sorted(e["nom"] for e in doc["entrees"]) == ["a", "b"], "le fichier réunit les deux périmètres"
    assert texte.count("\n") == len(doc["entrees"]) + 2, "une entrée par ligne (diffs git lisibles)"
    assert not list((tmp_path / "docs" / "data" / "kb").glob("*.tmp"))


def test_mise_a_jour_a_blanc_n_ecrit_rien(tmp_path):
    cat.mettre_a_jour(tmp_path, "claude", [], ecrire_fichiers=False)
    assert not cat.chemin_recent(tmp_path).exists()


def test_taille_bornee_sur_la_base_publiee():
    """Sur la vraie base (lecture seule), le fichier tient en quelques dizaines de Ko, bien sous la base complète."""
    entrees = [e for per in ("claude", "openai") for e in cat.charger(RACINE, per).values()]
    dates = [cat.date_ajout(e) for e in entrees if cat.date_ajout(e)]
    doc = cat.construire_recent(entrees, max(dates))
    taille = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert 0 < len(doc["entrees"]) <= cat.RECENT_MAX
    assert taille < 80_000, taille
    base_complete = sum(f.stat().st_size for f in (RACINE / "docs" / "data" / "kb").glob("*/*.json"))
    assert taille < base_complete / 20
    publie = cat.chemin_recent(RACINE)
    if publie.exists():  # le fichier commité par les passages respecte lui aussi la borne
        assert publie.stat().st_size < 80_000


# ----------------------------------------------------------------------------------------------- valider.py --kb

def racine_valide(tmp_path, *entrees):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    cat.ecrire(tmp_path, "claude", base(*entrees))
    return ["--perimetre", "claude", "--racine", str(tmp_path), "--kb"]


def test_valider_accepte_le_fichier_produit_et_son_absence(tmp_path, capsys):
    args = racine_valide(tmp_path, entree("a", ajout=cat.date.today().isoformat()), entree("b", ajout=cat.date.today().isoformat()))
    assert valider.main(args) == 0
    cat.chemin_recent(tmp_path).unlink()
    assert valider.main(args) == 0


def modifier_recent(tmp_path, fn):
    chemin = cat.chemin_recent(tmp_path)
    doc = json.loads(chemin.read_text(encoding="utf-8"))
    fn(doc)
    chemin.write_text(json.dumps(doc), encoding="utf-8")


@pytest.mark.parametrize("modif, attendu", [
    (lambda d: d["entrees"][0].update(id="claude-code-commandes-fantome"), "absent de la base claude"),
    (lambda d: d["entrees"].reverse(), "décroissante"),
    (lambda d: d["entrees"][0].update(verdict="peut-etre"), "`verdict` inconnu"),
    (lambda d: d["entrees"][0].update(date_ajout="hier"), "`date_ajout`"),
    (lambda d: d["entrees"][0].pop("usage"), "champs inattendus ou manquants"),
    (lambda d: d.update(tronque=True), "`tronque`"),
    (lambda d: d.update(plus_ancienne="2020-01-01"), "`plus_ancienne`"),
    (lambda d: d.update(entrees="x"), "liste `entrees`"),
])
def test_valider_refuse_un_fichier_incoherent(tmp_path, capsys, modif, attendu):
    jour = cat.date.today()
    args = racine_valide(tmp_path, entree("a", ajout=jour.isoformat()), entree("b", ajout="2026-01-01"),
                         entree("c", ajout=(jour - cat.timedelta(days=1)).isoformat()))  # b hors fenêtre
    modifier_recent(tmp_path, modif)
    assert valider.main(args) == 1
    assert attendu in capsys.readouterr().err


# ----------------------------------------------------------------------------------------------- site et chaîne

def test_encart_lit_recent_json_et_non_la_base():
    app = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    encart = app[app.index("function completerEncartKb"):app.index("function pageChangelogs")]
    assert "chargerRecentKb()" in encart and "chargerKb" not in encart, "l'onglet Aujourd'hui ne charge pas la base complète"
    charge = app[app.index("async function chargerRecentKb"):app.index("async function chargerKb")]
    assert 'lireJson("data/kb/recent.json")' in charge and "etat.kbRecent = null" in charge, "repli silencieux si le fichier manque"
    assert "console" not in charge
    corps = app[app.index("function encartNouveauKb"):app.index("function carteKb")]
    assert "etat.kb" not in corps and "recent.entrees" in corps and "au moins " in corps
    # la base complète reste chargée par l'onglet Référence seulement
    assert 'if (etat.page === "reference") await chargerKb();' in app
    assert app.count("chargerKb()") == 2  # définition... appel de la route ; aucun autre appelant


def test_chaque_etape_de_la_chaine_connait_recent_json():
    import garde
    import orchestrateur as orc
    f = "docs/data/kb/recent.json"
    for etape, chemins in garde.CHEMINS_ETAPE.items():
        assert f in chemins, etape
    e = {x.nom: x for x in orc.construire_etapes(orc.charger_config(), RACINE)}
    for n in ("delta", "codex-delta", "delta-kb", "codex-delta-kb"):
        assert f in e[n].checkout and f in e[n].clean, n
    settings = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    assert f"Bash(git add docs/data/kb/claude {f})" in settings
    for fichier in (".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta/SKILL.md",
                    ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md", "prompts/codex-delta-kb.md"):
        assert f in (RACINE / fichier).read_text(encoding="utf-8"), fichier
