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
    # D113 : un paramètre au nom de clé et au verdict `utiliser` est dû, après les commandes
    assert cat.exemples_detail(ent) == ["claude-code-commandes-due", "claude-code-parametres-reglage"]
    ent["claude-code-commandes-avec"]["exemple"] = "   "
    assert "claude-code-commandes-avec" in cat.exemples_detail(ent, maximum=None), "un exemple blanc compte comme absent"


def test_lot_exemples_plafond():
    ent = base(*(entree(nom=f"c{i:02}") for i in range(60)))
    assert cat.EXEMPLES_MAX == 50
    assert cat.exemples_detail(ent) == sorted(ent)[:50]
    assert len(cat.exemples_detail(ent, maximum=None)) == 60
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
    ent = [entree(nom=f"c{i:02}") for i in range(60)] + [entree("mcp", "serveur", "tester")]
    args = kb(tmp_path, *ent)[:-1]  # sans --kb
    assert cli.main(["lots", *args]) == 0
    assert "exemples" in capsys.readouterr().out
    assert cli.main(["a-commenter", *args, "--lot", "exemples"]) == 0
    lot = json.loads(capsys.readouterr().out)
    assert [x["nom"] for x in lot] == [f"c{i:02}" for i in range(50)] and all("exemple_origine" in x for x in lot)
    assert orchestrateur.lots_dus(tmp_path, "claude") == 61, "toutes les entrées dues comptent, pas seulement le plafond"
    f = tmp_path / "exemples.json"
    f.write_text(json.dumps({x["id"]: {"exemple": f"claude --resume {x['nom']}", "exemple_origine": "compose"} for x in lot}),
                 encoding="utf-8")
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 0
    capsys.readouterr()
    assert valider.main([*args, "--kb"]) == 0
    capsys.readouterr()
    assert orchestrateur.lots_dus(tmp_path, "claude") == 11
    assert cli.main(["a-commenter", *args, "--lot", "exemples"]) == 0
    assert [x["nom"] for x in json.loads(capsys.readouterr().out)] == [f"c{i:02}" for i in range(50, 60)] + ["serveur"]


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


# ----------------------------------------------------------------------------------------------- D113 : paramètres

def parametre(nom, verdict="utiliser", produit="claude-code", usage=None, source="Set it to false to omit the link.", **kw):
    return entree("parametres", nom, verdict, usage=usage or nom, produit=produit, source=source, **kw)


def test_lot_exemples_parametres_apres_les_quatre_categories_utiliser_puis_tester():
    ent = base(entree("mcp", "m"), parametre("attribution.sessionUrl", "tester"), parametre("autoMemoryEnabled", "utiliser"),
               parametre("zeta", "ignorer"), entree("commandes", "c"))
    assert cat.exemples_detail(ent) == ["claude-code-commandes-c", "claude-code-mcp-m", "claude-code-parametres-automemoryenabled",
                                        "claude-code-parametres-attribution-sessionurl"]


@pytest.mark.parametrize("nom", ["--add-dir", "CLAUDE_CODE_BG_TASKS_REPORT_RUNNING", "Hook SubagentStop", "Réglages : Appearance",
                                 "codex exec Resume subcommand", "-p"])
def test_lot_exemples_ignore_les_parametres_qui_ne_sont_pas_des_cles_de_reglage(nom):
    p = parametre(nom)
    assert cat.cle_de_reglage(p) is None and not cat.sans_exemple(p)
    assert cat.verifier_exemple(p, '{"a": true}', "compose") == (
        "pas d'exemple pour ce paramètre : ce n'est pas une clé de `settings.json` ni de `config.toml` (exemple: null)")


def test_cle_de_reglage_chemin_et_segment_libre():
    assert cat.cle_de_reglage(parametre("attribution.sessionUrl")) == ["attribution", "sessionUrl"]
    assert cat.cle_de_reglage(parametre("permissions.<name>.network.enable_socks5", produit="codex")) == [
        "permissions", "<name>", "network", "enable_socks5"]
    assert cat.cle_de_reglage(entree("commandes", "x")) is None


def test_exemple_json_de_reglage_valide():
    p = parametre("attribution.sessionUrl", usage='{\n  "attribution": {\n    "sessionUrl": false\n  }\n}')
    assert cat.verifier_exemple(p, '{"attribution": {"sessionUrl": false}}', "source") is None
    assert cat.verifier_exemple(p, '{\n  "attribution": {\n    "sessionUrl": true\n  }\n}', "compose") is None


def test_exemple_toml_de_reglage_valide_nombre_et_segment_libre():
    p = parametre("memories.max_unused_days", produit="codex", source="Type : number. Defaults to 30 and is clamped to 0-365.")
    assert cat.verifier_exemple(p, "[memories]\nmax_unused_days = 30\n", "compose") is None
    q = parametre("permissions.<name>.network.enable_socks5", produit="codex", source="Type : boolean.")
    assert cat.verifier_exemple(q, "[permissions.dev.network]\nenable_socks5 = true\n", "compose") is None


def test_exemple_de_reglage_refus():
    p = parametre("attribution.sessionUrl", usage='{"attribution": {"sessionUrl": false}}')
    assert "illisible en JSON" in cat.verifier_exemple(p, '{"attribution": ', "compose")
    assert "absente de l'extrait" in cat.verifier_exemple(p, '{"autre": {"sessionUrl": false}}', "compose")
    assert "absente de l'extrait" in cat.verifier_exemple(p, '{"attribution": {"autre": false}}', "compose")
    assert "non minimal" in cat.verifier_exemple(p, '{"attribution": {"sessionUrl": false}, "model": "x"}', "compose")
    t = parametre("memories.max_unused_days", produit="codex", source="Type : number.")
    assert "illisible en TOML" in cat.verifier_exemple(t, "[memories\nmax = 3", "compose")
    assert "absente de l'extrait" in cat.verifier_exemple(t, "max_unused_days = 30", "compose")


def test_exemple_de_reglage_valeur_inventee():
    p = parametre("attribution.sessionUrl", usage='{"attribution": {"sessionUrl": false}}', source="Set it to false to omit the link.")
    assert cat.verifier_exemple(p, '{"attribution": {"sessionUrl": "inventee"}}', "compose").startswith("exemple : valeur 'inventee'")
    d = parametre("disableAutoMode", usage='{"disableAutoMode": "disable"}', source="Remove auto mode.")
    assert cat.verifier_exemple(d, '{"disableAutoMode": "disable"}', "source") is None, "chaîne citée par `usage`"
    assert "valeur" in cat.verifier_exemple(d, '{"disableAutoMode": "enable"}', "source")


def test_appliquer_parametre_forme_verifiee_avant_ecriture():
    p = parametre("attribution.sessionUrl", usage='{"attribution": {"sessionUrl": false}}')
    ent = base(p)
    mauvais = {p["id"]: {"exemple": '{"model": "x"}', "exemple_origine": "compose"}}
    assert any("absente de l'extrait" in m for m in cat.appliquer_commentaires(ent, mauvais, jour=JOUR))
    assert ent[p["id"]]["exemple"] is None if "exemple" in ent[p["id"]] else True
    bon = {p["id"]: {"exemple": '{"attribution": {"sessionUrl": false}}', "exemple_origine": "source"}}
    assert cat.appliquer_commentaires(ent, bon, jour=JOUR) == []
    assert ent[p["id"]]["exemple"] == '{"attribution": {"sessionUrl": false}}'


# ----------------------------------------------------------------------------------------------- D113 : audit des exemples

def test_argument_obligatoire_non_rempli():
    e = entree(nom="apply", usage="codex apply <TASK_ID>", produit="codex")
    msg = cat.verifier_exemple(e, "codex apply", "source")
    assert msg and "<TASK_ID>" in msg and "exemple: null" in msg
    assert "gabarit" in cat.verifier_exemple(e, "codex apply <TASK_ID>", "source")
    assert cat.verifier_exemple(e, "codex apply task_abc123", "source") is None
    assert cat.verifier_exemple(e, "cd ~/projets/x && codex apply task_abc123 && git status", "compose") is None
    assert cat.verifier_exemple(e, "cd ~/projets/x && codex apply", "compose")
    # facultatifs, options et usage sans argument : rien à remplir
    assert cat.arguments_obligatoires("/goal [condition|clear]") == (["/goal"], [])
    assert cat.arguments_obligatoires("claude -p <prompt>") == (["claude"], [])
    assert cat.arguments_obligatoires("claude mcp add <name> <commandOrUrl> [args...]") == (["claude", "mcp", "add"], ["<name>", "<commandOrUrl>"])
    assert cat.verifier_exemple(entree(nom="agents", usage="/agents"), "/agents", "source") is None
    assert cat.verifier_exemple(entree(nom="mcp", usage="claude mcp add <name> <url>"), "claude mcp add sentry", "source")
    assert cat.verifier_exemple(entree(nom="mcp", usage="claude mcp add <name> <url>"), "claude mcp add sentry https://x.io/mcp", "source") is None


def test_disponibilite_hors_profil_sans_exemple():
    exclus = ["windows", "macos"]
    desktop = entree(nom="desktop", usage="/desktop")
    desktop["disponibilite"] = "macOS ou Windows x64, abonnement Claude"
    assert "exclut tous les systèmes du profil" in cat.verifier_exemple(desktop, "/desktop", "source", exclus)
    assert cat.verifier_exemple(desktop, "/desktop", "source") is None, "sans profil, rien à comparer"
    desktop["disponibilite"] = "macOS et Windows"
    assert "exclut" in cat.verifier_exemple(desktop, "/desktop", "source", exclus)
    for dispo in ("Linux, iOS, web", "macOS, Windows et Linux", "Max et Team", None):
        desktop["disponibilite"] = dispo
        assert cat.verifier_exemple(desktop, "/desktop", "source", exclus) is None, dispo


def test_disponibilite_d_un_commentaire_neuf_controle_l_exemple_du_meme_commentaire():
    e = entree(commentee=False, nom="app", usage="/app", produit="codex")
    c = {"description": "Ouvre l'app.", "statut_usage": "inconnu", "recommandation": {"verdict": "ignorer", "pourquoi": "Pas sur Linux."},
         "contexte_sections": {}, "disponibilite": "macOS et Windows", "exemple": "/app", "exemple_origine": "source"}
    erreurs = cat.appliquer_commentaires(base(e), {e["id"]: c}, jour=JOUR, contexte="a" * 40, resoudre=lambda cs: cs,
                                         exclure_systemes=["windows", "macos"])
    assert len(erreurs) == 1 and "exclut tous les systèmes du profil" in erreurs[0]
    c2 = dict(c, exemple=None)
    c2.pop("exemple_origine")
    assert cat.appliquer_commentaires(base(e), {e["id"]: c2}, jour=JOUR, contexte="a" * 40, resoudre=lambda cs: cs,
                                      exclure_systemes=["windows", "macos"]) == []


def test_exemple_compose_chemin_du_projet_nomme():
    e = entree(nom="subtask", usage="/subtask <description>")
    e["recommandation"] = {"verdict": "utiliser", "pourquoi": "Pour les audits de ~/projets/trading-sim."}
    assert cat.verifier_exemple(e, "/subtask relire ~/projets/trading-sim/scripts/garde.py", "compose") is None
    msg = cat.verifier_exemple(e, "/subtask relire ~/projets/delta-ia/scripts/garde.py", "compose")
    assert msg and "delta-ia" in msg and "trading-sim" in msg
    assert cat.verifier_exemple(e, "/subtask relire /home/herbin/projets/delta-ia/scripts/garde.py", "compose")
    assert cat.verifier_exemple(e, "/subtask relire ~/projets/delta-ia/scripts/garde.py", "source") is None, "contrôle des seuls composés"
    e["recommandation"] = {"verdict": "utiliser", "pourquoi": "Pour les audits de la veille."}
    assert cat.verifier_exemple(e, "/subtask relire ~/projets/delta-ia/scripts/garde.py", "compose") is None, "aucun projet nommé par chemin"


def test_cli_appliquer_lit_le_profil(tmp_path, capsys):
    e = entree(nom="desktop", usage="/desktop")
    e["disponibilite"] = "macOS ou Windows x64"
    args = kb(tmp_path, e)[:-1]
    (tmp_path / "profil.yaml").write_text("base:\n  exclure_systemes: [windows, macos]\n", encoding="utf-8")
    f = tmp_path / "exemples.json"
    f.write_text(json.dumps({e["id"]: {"exemple": "/desktop", "exemple_origine": "source"}}), encoding="utf-8")
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 1
    assert "exclut tous les systèmes du profil" in capsys.readouterr().err


def test_skills_regles_d113():
    for chemin in (".claude/skills/delta-kb/SKILL.md", ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta-kb.md"):
        t = (RACINE / chemin).read_text(encoding="utf-8")
        item = next(l for l in t.splitlines() if "**Lot exemples (D91).**" in l)
        for attendu in ("paramètres", "`source`", "`compose`", "/agents", "chemin absolu", "disponibilite", "`<…>`"):
            assert attendu in item, (chemin, attendu)
        assert "settings.json" in t and "config.toml" in t and "extrait minimal" in t, chemin
