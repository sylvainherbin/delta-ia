"""D91 : lot `exemples` de delta-kb, règle de provenance (`exemple_origine`) et avertissement de valider.py."""

import json

import pytest

import catalogue as cli
import orchestrateur
import valider
from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite

CONTEXTE = "# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n"
JOUR = "2026-10-08"


def entree(categorie="commandes", nom="resume", verdict="utiliser", usage="claude --resume [session]", nature="syntaxe",
           exemple=None, commentee=True, produit="claude-code", source="Resume a session. See --continue too."):
    e = cat.nouvelle_entree(EntreeExtraite(
        produit=produit, categorie=categorie, nom=nom, usage=usage, description_source=source,
        url="https://example.org/doc", libelle="Doc", origine="test", usage_nature=nature), "2026-09-23")
    if commentee:
        cat.appliquer_commentaires({e["id"]: e}, {e["id"]: {
            "description": "Reprend une session de travail dans le projet.", "statut_usage": "inconnu",
            "recommandation": {"verdict": verdict, "pourquoi": "Reprise des sessions du projet de veille."},
            "contexte_sections": {}}}, jour="2026-10-01", contexte="a" * 40, resoudre=lambda cs: cs)
    if exemple:
        e["exemple"] = exemple
    return e


def base(*entrees):
    return {e["id"]: e for e in entrees}


# ----------------------------------------------------------------------------------------------- sélection du lot

def test_lot_exemples_ordre_categories_puis_verdicts():
    ent = base(
        entree("mcp", "m-utiliser", "utiliser"), entree("skills", "s-tester", "tester"),
        entree("fonctionnalites", "f-ignorer", "ignorer"), entree("fonctionnalites", "f-tester", "tester"),
        entree("fonctionnalites", "f-utiliser", "utiliser"), entree("commandes", "c-ignorer", "ignorer"),
        entree("commandes", "c-tester", "tester"), entree("commandes", "c-utiliser", "utiliser"))
    assert cat.exemples_detail(ent) == [
        "claude-code-commandes-c-utiliser", "claude-code-commandes-c-tester", "claude-code-commandes-c-ignorer",
        "claude-code-fonctionnalites-f-utiliser", "claude-code-fonctionnalites-f-tester", "claude-code-fonctionnalites-f-ignorer",
        "claude-code-skills-s-tester", "claude-code-mcp-m-utiliser"]


def test_lot_exemples_exclusions():
    avec = entree(nom="avec", exemple="claude --resume")
    retiree = entree(nom="retiree")
    retiree["retiree"] = True
    ent = base(entree(nom="due"), avec, retiree, entree(nom="non-commentee", commentee=False),
               entree(nom="etapes", nature="etapes", usage="Menu > Réglages"), entree("plugins", "plugin"),
               entree("parametres", "reglage"), entree("raccourcis", "touche"))
    assert cat.exemples_detail(ent) == ["claude-code-commandes-due"]
    ent["claude-code-commandes-avec"]["exemple"] = "   "
    assert "claude-code-commandes-avec" in cat.exemples_detail(ent, maximum=None), "un exemple blanc compte comme absent"


def test_lot_exemples_plafond():
    ent = base(*(entree(nom=f"c{i:02}") for i in range(30)))
    assert cat.EXEMPLES_MAX == 25
    assert cat.exemples_detail(ent) == sorted(ent)[:25]
    assert len(cat.exemples_detail(ent, maximum=None)) == 30
    assert cat.exemples_detail(ent, maximum=3) == sorted(ent)[:3]


# ----------------------------------------------------------------------------------------------- règle de provenance

def test_ajout_d_exemple_seul_sans_refaire_le_commentaire():
    e = entree()
    avant = {k: e[k] for k in ("description", "recommandation", "contexte_empreinte", "contexte_sections", "commentee")}
    ok = {e["id"]: {"exemple": "claude --resume projet-veille", "exemple_origine": "compose"}}
    assert cat.appliquer_commentaires({e["id"]: e}, ok, jour=JOUR) == []
    assert (e["exemple"], e["exemple_origine"], e["maj_le"]) == ("claude --resume projet-veille", "compose", JOUR)
    assert e["historique"][-1] == {"date": JOUR, "changement": "exemple ajouté"}
    assert {k: e[k] for k in avant} == avant, "le jugement n'est pas refait"
    assert cat.exemples_detail({e["id"]: e}, maximum=None) == []


@pytest.mark.parametrize("patch,attendu", [
    ({"exemple": "claude --resume"}, "exemple_origine"),
    ({"exemple": "claude --resume", "exemple_origine": "invente"}, "exemple_origine"),
    ({"exemple": "claude --resume x --nouvelle-option", "exemple_origine": "compose"}, "--nouvelle-option"),
    ({"exemple": " ", "exemple_origine": "source"}, "`exemple` absent"),
    ({"exemple_origine": "source"}, "`exemple` absent"),
])
def test_ajout_d_exemple_refuse(patch, attendu):
    e = entree()
    erreurs = cat.appliquer_commentaires({e["id"]: e}, {e["id"]: patch}, jour=JOUR)
    assert len(erreurs) == 1 and attendu in erreurs[0], erreurs
    assert e["exemple"] is None and "exemple_origine" not in e


def test_exemple_refuse_pour_etapes_et_pour_entree_non_commentee():
    etapes = entree(nom="e", nature="etapes", usage="Menu > Réglages")
    brouillon = entree(nom="b", commentee=False)
    patch = {"exemple": "claude", "exemple_origine": "source"}
    erreurs = cat.appliquer_commentaires({etapes["id"]: etapes, brouillon["id"]: brouillon},
                                         {etapes["id"]: patch, brouillon["id"]: patch}, jour=JOUR)
    assert len(erreurs) == 2 and "etapes" in erreurs[0] and "commentées" in erreurs[1]


def test_exemple_compose_avec_options_de_la_source_et_exemple_recopie():
    e = entree(usage="claude --resume [session]", source="Resume. See --continue too.")
    recopie = {"exemple": "claude --continue --resume abc --autre-option", "exemple_origine": "source"}
    assert cat.appliquer_commentaires({e["id"]: e}, {e["id"]: recopie}, jour=JOUR) == [], "`source` n'est pas contrôlé option par option"
    f = entree(nom="f", usage="claude --resume [session]", source="Resume. See --continue too.")
    compose = {"exemple": "claude --resume projet && claude --continue", "exemple_origine": "compose"}
    assert cat.appliquer_commentaires({f["id"]: f}, {f["id"]: compose}, jour=JOUR) == []


def test_commentaire_complet_avec_exemple_exige_l_origine_et_l_efface_avec_null():
    e = entree(nom="c")
    complet = {"description": "Reprend une session de travail dans le projet.", "statut_usage": "inconnu",
               "recommandation": {"verdict": "tester", "pourquoi": "Reprise des sessions du projet de veille."},
               "contexte_sections": {}, "exemple": "claude --resume"}
    erreurs = cat.appliquer_commentaires({e["id"]: e}, {e["id"]: complet}, jour=JOUR, resoudre=lambda cs: cs)
    assert len(erreurs) == 1 and "exemple_origine" in erreurs[0]
    complet["exemple_origine"] = "source"
    assert cat.appliquer_commentaires({e["id"]: e}, {e["id"]: complet}, jour=JOUR, resoudre=lambda cs: cs) == []
    assert (e["exemple"], e["exemple_origine"]) == ("claude --resume", "source")
    assert cat.appliquer_commentaires({e["id"]: e}, {e["id"]: {**complet, "exemple": None, "exemple_origine": None}},
                                      jour=JOUR, resoudre=lambda cs: cs) == []
    assert e["exemple"] is None and "exemple_origine" not in e


# ----------------------------------------------------------------------------------------------- valider.py --kb

def kb(tmp_path, *entrees, perimetre="claude"):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    cat.ecrire(tmp_path, perimetre, base(*entrees))
    return ["--perimetre", perimetre, "--racine", str(tmp_path), "--kb"]


def test_valider_avertit_sans_changer_le_code(tmp_path, capsys):
    args = kb(tmp_path, entree(nom="a"), entree("fonctionnalites", "b"), entree(nom="c", exemple="claude --resume"),
              entree(nom="d", nature="etapes", usage="Menu > Réglages"), entree("skills", "s"))
    assert valider.main(args) == 0
    sortie = capsys.readouterr().out
    assert "! AVERTISSEMENT kb/claude: 2 entrées commandes/fonctionnalités sans exemple" in sortie
    # les skills et les entrées `etapes` n'entrent pas dans le compte


def test_valider_sans_avertissement_quand_tout_a_un_exemple(tmp_path, capsys):
    args = kb(tmp_path, entree(nom="a", exemple="claude --resume"))
    assert valider.main(args) == 0
    assert "AVERTISSEMENT" not in capsys.readouterr().out


@pytest.mark.parametrize("champs,erreur", [
    ({"exemple": "claude --resume", "exemple_origine": "source"}, None),
    ({"exemple": "claude --resume", "exemple_origine": "compose"}, None),
    ({"exemple": "claude --resume"}, None),  # entrées antérieures à D91
    ({"exemple": "claude --resume", "exemple_origine": "invente"}, "exemple_origine"),
    ({"exemple": None, "exemple_origine": "source"}, "sans `exemple`"),
    ({"exemple": 3}, "`exemple`"),
    ({"exemple": "  "}, "`exemple`"),
])
def test_valider_exemple_origine(tmp_path, capsys, champs, erreur):
    e = entree()
    e.update(champs)
    args = kb(tmp_path, e)
    code = valider.main(args)
    sortie = capsys.readouterr()
    if erreur is None:
        assert code == 0, sortie.err
    else:
        assert code == 1 and erreur in sortie.err, sortie.err


def test_valider_refuse_exemple_origine_sur_une_entree_etapes(tmp_path, capsys):
    e = entree(nature="etapes", usage="Menu > Réglages")
    e.update({"exemple": "Menu", "exemple_origine": "source"})
    assert valider.main(kb(tmp_path, e)) == 1
    assert "etapes" in capsys.readouterr().err


# ----------------------------------------------------------------------------------------------- CLI et orchestrateur

def test_cli_lots_a_commenter_appliquer_et_lots_dus(tmp_path, capsys):
    ent = [entree(nom=f"c{i:02}") for i in range(27)] + [entree("mcp", "serveur", "tester")]
    args = kb(tmp_path, *ent)[:-1]  # sans --kb
    assert cli.main(["lots", *args]) == 0
    assert "exemples" in capsys.readouterr().out
    assert cli.main(["a-commenter", *args, "--lot", "exemples"]) == 0
    lot = json.loads(capsys.readouterr().out)
    assert [x["nom"] for x in lot] == [f"c{i:02}" for i in range(25)] and all("exemple_origine" in x for x in lot)
    assert orchestrateur.lots_dus(tmp_path, "claude") == 28, "toutes les entrées dues comptent, pas seulement le plafond"
    f = tmp_path / "exemples.json"
    f.write_text(json.dumps({x["id"]: {"exemple": f"claude --resume {x['nom']}", "exemple_origine": "compose"} for x in lot}),
                 encoding="utf-8")
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 0
    capsys.readouterr()
    assert valider.main([*args, "--kb"]) == 0
    capsys.readouterr()
    assert orchestrateur.lots_dus(tmp_path, "claude") == 3
    assert cli.main(["a-commenter", *args, "--lot", "exemples"]) == 0
    assert [x["nom"] for x in json.loads(capsys.readouterr().out)] == ["c25", "c26", "serveur"]


def test_cli_appliquer_refuse_sans_rien_ecrire(tmp_path, capsys):
    e = entree()
    args = kb(tmp_path, e)[:-1]
    f = tmp_path / "exemples.json"
    f.write_text(json.dumps({e["id"]: {"exemple": "claude --resume"}}), encoding="utf-8")
    avant = (tmp_path / "docs/data/kb/claude/commandes.json").read_bytes()
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 1
    assert "exemple_origine" in capsys.readouterr().err
    assert (tmp_path / "docs/data/kb/claude/commandes.json").read_bytes() == avant


# ----------------------------------------------------------------------------------------------- skills et prompt

@pytest.mark.parametrize("chemin,perimetre", [(".claude/skills/delta-kb/SKILL.md", "claude"), (".agents/skills/delta-kb/SKILL.md", "openai"),
                                               ("prompts/codex-delta-kb.md", "openai")])
def test_skills_decrivent_le_lot_exemples_et_la_provenance(chemin, perimetre):
    t = (RACINE / chemin).read_text(encoding="utf-8")
    assert f"--perimetre {perimetre} --lot exemples" in t
    assert "exemple_origine" in t and "`source`" in t and "`compose`" in t
    assert f"delta-kb({perimetre}): exemples" in t
    assert "`etapes`" in t and "exemple: null" in t


def test_skills_miroirs_pour_le_lot_exemples():
    def item(chemin):
        t = (RACINE / chemin).read_text(encoding="utf-8")
        return next(l for l in t.splitlines() if "**Lot exemples (D91).**" in l).split(". ", 1)[1]
    assert item(".agents/skills/delta-kb/SKILL.md") == item("prompts/codex-delta-kb.md")
    assert item(".claude/skills/delta-kb/SKILL.md").replace("claude", "openai") == item(".agents/skills/delta-kb/SKILL.md")
