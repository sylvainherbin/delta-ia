"""D105 : docs/data/kb/noms.json (index nom → id) et liens des segments de code de la veille vers les fiches de la base."""

import hashlib
import json

import pytest

import valider
from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite

CONTEXTE = "# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n"
EMPREINTE = hashlib.sha1(CONTEXTE.encode("utf-8")).hexdigest()


def entree(nom, categorie="commandes", produit="claude-code", usage=None, retiree=False):
    e = cat.nouvelle_entree(EntreeExtraite(
        produit=produit, categorie=categorie, nom=nom, usage=usage if usage is not None else nom,
        description_source="Doc.", url="https://example.org/doc", libelle="Doc", origine="test", usage_nature="syntaxe"), "2026-10-08")
    e["retiree"] = retiree
    return e


def app_js():
    return (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")


def morceau(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i + len(debut))]


# ----------------------------------------------------------------------------------------------- normalisation

@pytest.mark.parametrize("brut, attendu", [
    ("/Add-Dir", "/add-dir"),
    ("  claude   mcp\tadd \n", "claude mcp add"),
    ("ＡＮＴＨＲＯＰＩＣ_API_KEY", "anthropic_api_key"),  # NFKC : pleine chasse → ASCII
    ("--Add-Dir", "--add-dir"),
    ("", ""),
    (None, ""),
])
def test_normaliser_nom(brut, attendu):
    assert cat.normaliser_nom(brut) == attendu


def test_la_normalisation_js_est_la_meme():
    assert 'String(s || "").normalize("NFKC").replace(/\\s+/g, " ").trim().toLowerCase()' in app_js()
    assert 'unicodedata.normalize("NFKC", s or "")' in (RACINE / "scripts" / "deltalib" / "kb" / "catalogue.py").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------------------------- index

def test_nom_et_premier_mot_de_l_usage():
    doc = cat.construire_noms([
        entree("/add-dir", usage="/add-dir <path>"),
        entree("--advisor <model>", categorie="parametres", usage="--advisor <model>"),
        entree("Hooks reference", categorie="fonctionnalites", usage="/hooks"),  # catégorie sans premier mot d'usage
        entree("loop", categorie="skills", usage="/loop 5m /foo"),
    ])
    assert doc == {
        "--advisor": ["claude-code-parametres-advisor-model"],
        "--advisor <model>": ["claude-code-parametres-advisor-model"],
        "/add-dir": ["claude-code-commandes-add-dir"],
        "/loop": ["claude-code-skills-loop"],
        "hooks reference": ["claude-code-fonctionnalites-hooks-reference"],
        "loop": ["claude-code-skills-loop"],
    }


def test_collisions_deux_produits_et_deux_categories():
    doc = cat.construire_noms([
        entree("/clear", produit="codex"), entree("/clear"),
        entree("Plan", categorie="fonctionnalites", usage="/plan"), entree("/plan", usage="/plan"),
    ])
    assert doc["/clear"] == ["claude-code-commandes-clear", "codex-commandes-clear"], "ids triés"
    assert doc["/plan"] == ["claude-code-commandes-plan"], "le premier mot d'usage d'une fonctionnalité n'est pas une clé"


def test_la_casse_se_replie_et_les_collisions_aussi():
    doc = cat.construire_noms([entree("Read", categorie="fonctionnalites"), entree("read", categorie="parametres")])
    assert doc == {"read": ["claude-code-fonctionnalites-read", "claude-code-parametres-read"]}


def test_exclusions():
    doc = cat.construire_noms([
        entree("a", categorie="raccourcis"),  # une lettre : trop banal
        entree("0", categorie="raccourcis"),
        entree("retirée", retiree=True),
        entree("un deux trois quatre cinq six"),  # plus de 5 mots : une phrase, pas un nom
        entree("x" * 81),
        entree("Alt+B", categorie="raccourcis"),
        entree("  /spaced   name "),
    ])
    assert sorted(doc) == ["/spaced", "/spaced name", "alt+b"]


def test_sans_entree():
    assert cat.construire_noms([]) == {}


def test_ecrire_produit_le_fichier_des_deux_perimetres(tmp_path):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    base = lambda *es: {e["id"]: e for e in es}
    cat.ecrire(tmp_path, "claude", base(entree("/zeta"), entree("/alpha")))
    assert json.loads(cat.chemin_noms(tmp_path).read_text(encoding="utf-8")) == {
        "/alpha": ["claude-code-commandes-alpha"], "/zeta": ["claude-code-commandes-zeta"]}
    cat.ecrire(tmp_path, "openai", base(entree("/alpha", produit="codex")))
    texte = cat.chemin_noms(tmp_path).read_text(encoding="utf-8")
    doc = json.loads(texte)
    assert doc["/alpha"] == ["claude-code-commandes-alpha", "codex-commandes-alpha"], "le fichier réunit les deux périmètres"
    assert list(doc) == sorted(doc)
    assert texte.count("\n") == len(doc) + 2, "une clé par ligne (diffs git lisibles)"
    assert "genere" not in texte, "aucun horodatage : le fichier ne change que si un nom change"
    assert not list((tmp_path / "docs" / "data" / "kb").glob("*.tmp"))


def test_mise_a_jour_a_blanc_n_ecrit_rien(tmp_path):
    cat.mettre_a_jour(tmp_path, "claude", [], ecrire_fichiers=False)
    assert not cat.chemin_noms(tmp_path).exists()


def test_index_leger_sur_la_base_publiee():
    """Sur la vraie base (lecture seule) : l'index reste léger et le fichier commité ne cite que des ids existants."""
    entrees = [e for per in ("claude", "openai") for e in cat.charger(RACINE, per).values()]
    doc = cat.construire_noms(entrees)
    taille = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert doc and taille < 250_000, taille
    base_complete = sum(f.stat().st_size for f in (RACINE / "docs" / "data" / "kb").glob("*/*.json"))
    assert taille < base_complete / 10
    publie = cat.chemin_noms(RACINE)
    if publie.exists():
        ids = {e["id"] for e in entrees}
        lu = json.loads(publie.read_text(encoding="utf-8"))
        assert all(i in ids for liste in lu.values() for i in liste)
        assert publie.stat().st_size < 250_000


# ----------------------------------------------------------------------------------------------- valider.py --kb

def racine_valide(tmp_path, *entrees):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    cat.ecrire(tmp_path, "claude", {e["id"]: e for e in entrees})
    return ["--perimetre", "claude", "--racine", str(tmp_path), "--kb"]


def modifier(tmp_path, fn):
    chemin = cat.chemin_noms(tmp_path)
    doc = json.loads(chemin.read_text(encoding="utf-8"))
    fn(doc)
    chemin.write_text(json.dumps(doc), encoding="utf-8")


def test_valider_accepte_le_fichier_produit_et_son_absence(tmp_path):
    args = racine_valide(tmp_path, entree("/a"), entree("/b"))
    assert valider.main(args) == 0
    cat.chemin_noms(tmp_path).unlink()
    assert valider.main(args) == 0


@pytest.mark.parametrize("modif, attendu", [
    (lambda d: d.update({"/z": ["claude-code-commandes-fantome"]}), "absent de la base claude"),
    (lambda d: d.update({"/Maj": ["claude-code-commandes-a"]}), "non normalisée"),
    (lambda d: d.update({"/vide": []}), "liste non vide"),
    (lambda d: d.update({"/a": ["claude-code-commandes-b", "claude-code-commandes-a"]}), "ids à trier"),
    (lambda d: d.update({"/a": ["claude-code-commandes-a", "claude-code-commandes-a"]}), "sans doublon"),
    (lambda d: d.update({"/a": "claude-code-commandes-a"}), "liste non vide"),
])
def test_valider_refuse_un_fichier_incoherent(tmp_path, capsys, modif, attendu):
    args = racine_valide(tmp_path, entree("/a"), entree("/b"))
    modifier(tmp_path, modif)
    assert valider.main(args) == 1
    assert attendu in capsys.readouterr().err


def test_valider_refuse_des_cles_mal_triees(tmp_path, capsys):
    args = racine_valide(tmp_path, entree("/a"), entree("/b"))
    chemin = cat.chemin_noms(tmp_path)
    chemin.write_text(json.dumps(dict(reversed(list(json.loads(chemin.read_text(encoding="utf-8")).items())))), encoding="utf-8")
    assert valider.main(args) == 1
    assert "trier par ordre alphabétique" in capsys.readouterr().err


def test_valider_laisse_les_ids_de_l_autre_perimetre_a_son_controle(tmp_path):
    args = racine_valide(tmp_path, entree("/a"))
    modifier(tmp_path, lambda d: d.update({"/z": ["codex-commandes-z"]}))
    assert valider.main(args) == 0


# ----------------------------------------------------------------------------------------------- app.js

def test_l_index_est_charge_a_part_et_sans_la_base():
    app = app_js()
    charge = morceau(app, "async function chargerNomsKb", "async function chargerKb")
    assert 'lireJson("data/kb/noms.json")' in charge and "etat.noms = null" in charge, "repli silencieux si le fichier manque"
    assert "chargerKb" not in charge and "console" not in charge
    assert 'etat.page === "reference" ? null : chargerNomsKb()' in app, "les pages de veille chargent l'index, pas la Référence"
    assert app.count("chargerKb()") == 2  # définition et appel de la route Référence seulement


def test_segments_de_code_des_champs_de_chaque_onglet():
    app = app_js()
    carte = morceau(app, "function carte(e, options)", "function listeCartes")
    assert "...enrichi(e.resume, e.produit)" in carte and "...enrichi(e.pour_toi, e.produit)" in carte
    assert "...enrichi(e.action.description, e.produit)" in carte and "...enrichi(s, e.produit)" in carte, "description et étapes de l'action"
    assert "text: e.resume" not in carte and "text: e.pour_toi" not in carte and "text: e.action.description" not in carte
    assert "...enrichi(l.action, l.produit)" in morceau(app, "function ligneSemaine", "function ligneKbSemaine"), "onglet Semaine"
    # Aujourd'hui, Changelogs et À tester affichent leurs éléments par `carte`
    assert "listeCartes(" in morceau(app, "function pageChangelogs", "function pageActu")
    assert "listeCartes(ouvertes" in morceau(app, "function pageATester", "function pageArchives")
    assert "carte(" in app[app.index("function blocSynthese"):app.index("function pageAujourdhui")] or "listeCartes(" in app[app.index("function pageAujourdhui"):app.index("function completerEncartKb")]


def test_regles_de_lien():
    app = app_js()
    ids = morceau(app, "function idsDuNom", "// texte → nœuds")
    assert "hasOwnProperty.call(noms, cle)" in ids, "pas de collision avec les propriétés héritées (`constructor`)"
    assert "if (!noms) return [];" in ids, "sans index, aucun lien"
    assert "/^[/-]/.test(premier)" in ids, "repli sur le premier mot seulement pour une commande ou une option"
    enr = morceau(app, "function enrichi", "\n  }\n")
    assert "#reference?id=${encodeURIComponent(ids[0])}" in enr, "un seul id : la fiche"
    assert "#reference?q=${encodeURIComponent(m[1].trim())}" in enr, "plusieurs ids : la recherche"
    assert "if (!ids.length) continue;" in enr, "inconnu : texte simple, accents graves conservés"
    assert "if (!etat.noms) return [t];" in enr
    assert 'el("code", { text: m[1] })' in enr and "innerHTML" not in enr


def test_nom_ambigu_departage_par_le_produit_de_l_element():
    """D110 : le produit de l'élément choisit la fiche d'un nom partagé entre produits ; sinon recherche comme avant."""
    app = app_js()
    prod = morceau(app, "function produitDeId", "// D110 : parmi")
    assert "RE_ID_KB.exec(String(id || \"\"))" in prod and "m[1]" in prod, "le produit vient de l'id, noms.json ne change pas de format"
    choix = morceau(app, "function idsDuProduit", "// texte → nœuds")
    assert "ids.length < 2" in choix and 'typeof produit !== "string"' in choix, "un seul id ou pas de produit : liste inchangée"
    assert "produitDeId(i) === produit" in choix and "memes.length === 1 ? memes : ids" in choix, "unique : la fiche ; sinon la recherche"
    enr = morceau(app, "function enrichi", "\n  }\n")
    assert "idsDuProduit(idsDuNom(m[1]), produit)" in enr and "function enrichi(s, produit)" in app
    for appel in ("enrichi(e.resume, e.produit)", "enrichi(e.pour_toi, e.produit)", "enrichi(e.action.description, e.produit)",
                  "enrichi(s, e.produit)", "enrichi(l.action, l.produit)"):
        assert f"...{appel}" in app, appel
    assert "...enrichi(e.resume)" not in app and "...enrichi(l.action)" not in app


def test_produits_des_ids_de_noms_json_publie():
    """D110 : chaque id de l'index publié porte un produit connu de l'onglet (préfixe), sans quoi le choix retomberait sur la recherche."""
    publie = cat.chemin_noms(RACINE)
    if not publie.exists():
        pytest.skip("pas d'index publié")
    produits = {"claude-code", "claude", "codex", "chatgpt"}
    ids = {i for liste in json.loads(publie.read_text(encoding="utf-8")).values() for i in liste}
    sans = [i for i in ids if not any(i.startswith(f"{p}-") for p in produits)]
    assert not sans, sans[:5]


def test_fiche_seule_et_recherche_par_l_url():
    app = app_js()
    route = morceau(app, "function lireRoute", "async function rendre")
    assert 'params.get("id")' in route and "etat.kbFicheId" in route
    assert 'params.get("q")' in route and "Object.assign(kbFiltre, { q," in route, "la recherche repart de filtres vides"
    fiche = morceau(app, "if (etat.kbFicheId)", "const total = kb.entrees.length")
    assert "carteKb(fiche)" in fiche and 'href: "#reference", text: "← Toute la référence"' in fiche
    assert "return frag;" in fiche, "pas de filtres ni de liste sous la fiche"
    assert "Aucune fiche pour cet identifiant" in fiche


def test_style_des_liens_de_reference():
    css = (RACINE / "docs" / "assets" / "style.css").read_text(encoding="utf-8")
    assert "a.ref-lien" in css and ".retour-ref" in css
    assert "a.ref-lien code { color: inherit; }" in css, "le code garde la couleur du lien en clair comme en sombre"


# ----------------------------------------------------------------------------------------------- chaîne

def test_chaque_etape_de_la_chaine_connait_noms_json():
    import garde
    import orchestrateur as orc
    f = "docs/data/kb/noms.json"
    for etape, chemins in garde.CHEMINS_ETAPE.items():
        assert f in chemins, etape
    e = {x.nom: x for x in orc.construire_etapes(orc.charger_config(), RACINE)}
    for n in ("delta", "codex-delta", "delta-kb", "codex-delta-kb"):
        assert f in e[n].checkout and f in e[n].clean, n
    settings = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    assert f"Bash(git add docs/data/kb/claude docs/data/kb/recent.json docs/data/kb/a-tester.json {f})" in settings
    for fichier in (".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta/SKILL.md",
                    ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md", "prompts/codex-delta-kb.md",
                    "CLAUDE.md", "AGENTS.md", "SPEC.md"):
        assert f in (RACINE / fichier).read_text(encoding="utf-8"), fichier
