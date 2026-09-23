"""Phase 4 : base de référence. Extraction sans modèle (D40), fusion et D44, lots (D46), commentaires, validation."""

import copy
import json
from pathlib import Path

import pytest

import fetch
from conftest import FauxClient, RACINE
from deltalib.http import Reponse
from deltalib.kb import catalogue as cat
from deltalib.kb.documentation import charger_documentation, recuperer
from deltalib.kb.extracteurs import EXTRACTEURS, _garder_linux
from deltalib.kb.markdown import cellules, sections, tableaux, usage_de
from deltalib.kb.modeles import EntreeExtraite
from deltalib.modeles import ErreurReseau, FormatInattendu

KB = Path(__file__).parent / "fixtures" / "kb"


def lire(nom):
    return (KB / nom).read_text(encoding="utf-8")


@pytest.fixture
def docs():
    return {d.id: d for d in charger_documentation(RACINE / "sources.yaml")}


def extraire(doc, **fichiers):
    return EXTRACTEURS[doc.extracteur](doc, fichiers)


# --- sources.yaml : section documentation ------------------------------------------------------------------

def test_documentation_declaree(docs):
    assert len(docs) >= 15
    assert all("Testé le 2026-09-23" in d.note for d in docs.values()), "chaque page déclare la date de son test"
    pages = sum(len(d.options.get("pages", {})) for d in docs.values())
    assert pages >= 150
    assert {d.perimetre for d in docs.values()} == {"claude", "openai"}


# --- Markdown ---------------------------------------------------------------------------------------------

def test_markdown_titres_hors_code_et_tableaux():
    texte = "# T\n\n## A\n\n```md\n## pas un titre\n```\n\n| a | b |\n| - | - |\n| `x\\|y` | z |\n\n## B\n"
    lignes, secs = sections(texte)
    assert [s.titre for s in secs] == ["T", "A", "B"]
    assert cellules("| `x\\|y` | z |") == ["`x|y`", "z"]
    tabs = tableaux(lignes)
    assert len(tabs) == 1 and tabs[0].lignes == [["`x|y`", "z"]]
    assert usage_de(lignes, 2, len(lignes)) == "## pas un titre"


def test_filtre_plateforme_d42():
    assert _garder_linux("Ctrl+V or Cmd+V (iTerm2) or Alt+V (Windows and WSL)")
    assert _garder_linux("Option+P (macOS) or Alt+P (Windows/Linux)")
    assert not _garder_linux("Cmd+K (macOS)")
    assert not _garder_linux("Alt+M on Windows")


# --- extracteurs sur échantillons réels -------------------------------------------------------------------

def test_commandes_claude_code(docs):
    es = extraire(docs["cc-commandes"], page=lire("cc_commands.md"))
    noms = {e.nom: e for e in es}
    assert "/add-dir" in noms and noms["/add-dir"].usage == "/add-dir <path>" and noms["/add-dir"].categorie == "commandes"
    assert any(e.categorie == "skills" for e in es), "les lignes marquées **Skill** vont dans skills"
    assert not any(e.nom.startswith("/setup-") for e in es), "setup- (fournisseurs cloud) exclu, D42"
    e = noms["/add-dir"]
    assert e.id == "claude-code-commandes-add-dir" and e.url == "https://code.claude.com/docs/en/commands" and e.description_source


def test_cli_claude_code_commandes_et_options(docs):
    es = extraire(docs["cc-cli"], page=lire("cc_cli.md"))
    cats = {e.categorie for e in es}
    assert cats == {"commandes", "parametres"}
    assert any(e.nom == "claude" and e.categorie == "commandes" for e in es)
    assert any(e.nom.startswith("--") and e.categorie == "parametres" for e in es)


def test_reglages_claude_code(docs):
    es = extraire(docs["cc-reglages"], page=lire("cc_settings.md"))
    assert [e.nom for e in es] == ["advisorModel", "alwaysThinkingEnabled"], "section entreprise exclue"
    assert es[0].usage.startswith("{") and '"advisorModel"' in es[0].usage, "usage = bloc settings.json recopié"
    assert es[0].url.endswith("#advisormodel") and es[0].categorie == "parametres"


def test_variables_claude_code(docs):
    es = extraire(docs["cc-variables"], page=lire("cc_env.md"))
    assert es and all(e.nom.isupper() for e in es)
    assert not any("BEDROCK" in e.nom for e in es)


def test_raccourcis_claude_code(docs):
    es = extraire(docs["cc-raccourcis"], page=lire("cc_interactive.md"))
    assert es and all(e.categorie == "raccourcis" for e in es)
    assert any(e.usage == "Ctrl+C" for e in es)


def test_plugins_claude_code(docs):
    es = extraire(docs["cc-plugins"], page=lire("cc_plugins.md"))
    noms = {e.nom for e in es}
    assert {"clangd-lsp", "github", "commit-commands", "security-guidance"} <= noms
    assert all(e.categorie == "plugins" for e in es)


def test_hooks_claude_code(docs):
    es = extraire(docs["cc-hooks"], page=lire("cc_hooks.md"))
    assert [e.nom for e in es] == ["Hook Setup", "Hook SessionStart"] or all(e.nom.startswith("Hook ") for e in es)
    assert len(es) == 2


def test_pages_fonctionnalites(docs):
    d = docs["cc-fonctionnalites"]
    es = extraire(d, **{"page:remote-control": lire("page_remote-control.md")})
    assert len(es) == 1
    e = es[0]
    assert e.id == "claude-code-fonctionnalites-page-remote-control", "l'identifiant suit le chemin de la page"
    assert e.url == "https://code.claude.com/docs/en/remote-control" and e.usage and e.description_source
    d = docs["claude-apps"]
    es = extraire(d, **{"page:11101966-use-voice-mode": lire("page_support_voice.md")})
    assert es[0].produit == "claude" and es[0].nom == "Use voice mode"
    assert es[0].url == "https://support.claude.com/en/articles/11101966-use-voice-mode"


def test_configtable_codex(docs):
    es = extraire(docs["oa-config"], page=lire("oa_config.md"))
    assert len(es) >= 20 and all(e.categorie == "parametres" for e in es)
    assert es[0].nom == "model" and es[0].usage == "model" and es[0].description_source.startswith("Type : string.")
    assert not any("requirements" in e.groupe for e in es if e.groupe)


def test_cli_codex(docs):
    es = extraire(docs["oa-cli"], page=lire("oa_cli.html"), md=lire("oa_cli.md"))
    cats = {e.categorie for e in es}
    assert {"commandes", "parametres", "mcp", "raccourcis"} <= cats
    assert any(e.nom == "codex --add-dir" for e in es)
    assert any(e.nom.startswith("codex") and e.categorie == "commandes" for e in es)
    assert any(e.nom.startswith("codex exec ") and e.categorie == "parametres" for e in es)
    assert not any("sandbox" in e.nom and ("macos" in e.description_source.lower() or "windows" in e.description_source.lower())
                   for e in es if e.categorie == "parametres" and e.groupe == "codex sandbox" and False)
    assert any(e.categorie == "raccourcis" and "Ctrl+R" in e.nom for e in es)


def test_cli_codex_ecart_de_tableaux(docs):
    md = lire("oa_cli.md").replace("<ConfigTable client:load options={globalFlagOptions} />", "", 1)
    with pytest.raises(FormatInattendu):
        extraire(docs["oa-cli"], page=lire("oa_cli.html"), md=md)


def test_commandes_chatgpt(docs):
    es = extraire(docs["chatgpt-app-commandes"], page=lire("chatgpt_commands.md"))
    r = [e for e in es if e.categorie == "raccourcis"]
    c = [e for e in es if e.categorie == "commandes"]
    assert r and c and all(e.usage.startswith("codex://") for e in c)
    assert r[0].nom == "Open command menu" and "Ctrl+Shift+P" in r[0].usage, "nom = action, usage = raccourci Linux"


@pytest.mark.parametrize("doc_id, fichiers", [
    ("cc-commandes", {"page": "# Commands\n\nPlus de tableau.\n"}),
    ("cc-reglages", {"page": "# All settings\n\nTout a changé.\n"}),
    ("oa-config", {"page": "# Configuration Reference\n\n## `config.toml`\n\nplus de ConfigTable\n"}),
    ("cc-plugins", {"page": "# Discover plugins\n"}),
    ("cc-fonctionnalites", {}),
])
def test_format_change_leve_une_erreur(docs, doc_id, fichiers):
    with pytest.raises(FormatInattendu):
        EXTRACTEURS[docs[doc_id].extracteur](docs[doc_id], fichiers)


# --- fusion (D40, D44) ------------------------------------------------------------------------------------

def x(nom, usage, origine="doc-a", categorie="commandes"):
    return EntreeExtraite(produit="claude-code", categorie=categorie, nom=nom, usage=usage, description_source="src",
                          url="https://code.claude.com/docs/en/commands", libelle="commands", origine=origine)


def commenter(entrees, ident):
    return cat.appliquer_commentaires(entrees, {ident: {
        "description": "Ajoute un répertoire de travail pour la session en cours.", "statut_usage": "inconnu",
        "recommandation": {"verdict": "tester", "pourquoi": "Utile sur trading-sim pour lire le dossier de missions."}}})


def test_fusion_ajout_usage_modifie_retrait_reapparition():
    e1, e2 = x("/a", "/a <x>"), x("/b", "/b")
    ent, m = cat.fusionner({}, [e1, e2], {"doc-a"}, jour="2026-09-24")
    assert m["ajoutees"] == ["claude-code-commandes-a", "claude-code-commandes-b"]
    assert all(v["commentee"] is False and v["recommandation"] is None and v["statut_usage"] == "inconnu" for v in ent.values())
    assert commenter(ent, "claude-code-commandes-a") == [] and ent["claude-code-commandes-a"]["commentee"] is True
    # même usage : le commentaire est conservé
    ent, m = cat.fusionner(ent, [x("/a", "/a <x>"), x("/b", "/b")], {"doc-a"}, jour="2026-09-25")
    assert not any(m.values()) and ent["claude-code-commandes-a"]["commentee"] is True
    # usage changé : repasse en commentee false (D44), historique renseigné
    ent, m = cat.fusionner(ent, [x("/a", "/a <x> [--y]"), x("/b", "/b")], {"doc-a"}, jour="2026-09-26")
    a = ent["claude-code-commandes-a"]
    assert m["usage_modifie"] == [a["id"]] and a["commentee"] is False and a["usage"] == "/a <x> [--y]"
    assert a["historique"][-1] == {"date": "2026-09-26", "changement": "usage modifié dans la documentation"}
    # absente d'une page extraite avec succès : retirée, jamais supprimée
    ent, m = cat.fusionner(ent, [x("/a", "/a <x> [--y]")], {"doc-a"}, jour="2026-09-27")
    assert m["retirees"] == ["claude-code-commandes-b"] and ent["claude-code-commandes-b"]["retiree"] is True
    ent, m = cat.fusionner(ent, [x("/a", "/a <x> [--y]"), x("/b", "/b")], {"doc-a"}, jour="2026-09-28")
    assert m["reapparues"] == ["claude-code-commandes-b"] and ent["claude-code-commandes-b"]["retiree"] is False


def test_fusion_doc_en_echec_ne_retire_rien():
    ent, _ = cat.fusionner({}, [x("/a", "/a")], {"doc-a"})
    ent, m = cat.fusionner(ent, [], set())  # doc-a non extraite (échec réseau ou format)
    assert m["retirees"] == [] and ent["claude-code-commandes-a"]["retiree"] is False


def test_appliquer_commentaires_refuse_usage_et_champs_invalides():
    ent, _ = cat.fusionner({}, [x("/a", "/a")], {"doc-a"})
    k = "claude-code-commandes-a"
    erreurs = cat.appliquer_commentaires(ent, {k: {"usage": "/autre", "description": "d", "statut_usage": "inconnu",
                                                   "recommandation": {"verdict": "tester", "pourquoi": "p"}}})
    assert erreurs and "non modifiables" in erreurs[0] and ent[k]["usage"] == "/a"
    assert cat.appliquer_commentaires(ent, {k: {"description": "d", "statut_usage": "peut-etre",
                                                "recommandation": {"verdict": "tester", "pourquoi": "p"}}})
    assert cat.appliquer_commentaires(ent, {k: {"description": "d", "statut_usage": "inconnu", "recommandation": {"verdict": "adopter", "pourquoi": "p"}}})
    assert cat.appliquer_commentaires(ent, {"inconnu": {}})
    assert ent[k]["commentee"] is False


def test_lots_ordre_quarts_et_moities_d50_d51():
    ent, _ = cat.fusionner({}, [x(f"/c{i}", "u") for i in range(61)] + [x(f"P{i}", "p", categorie="parametres") for i in range(10)]
                           + [x(f"R{i}", "r", categorie="raccourcis") for i in range(3)] + [x(f"F{i}", "f", categorie="fonctionnalites") for i in range(2)]
                           + [x(f"M{i}", "m", categorie="mcp") for i in range(2)], {"doc-a"})
    lots = cat.lots(ent, "claude")
    assert [(l["lot"], l["entrees"]) for l in lots] == [
        ("commandes:1", 31), ("commandes:2", 30), ("fonctionnalites", 2), ("mcp", 2), ("raccourcis", 3),
        ("parametres:1", 3), ("parametres:2", 3), ("parametres:3", 3), ("parametres:4", 1)]
    assert lots[-1]["gabarit"] == "court" and lots[0]["gabarit"] == "complet"


def test_lots_openai_regroupe_skills_plugins_mcp():
    def y(nom, categorie):
        return EntreeExtraite(produit="codex", categorie=categorie, nom=nom, usage="u", description_source="s",
                              url="https://learn.chatgpt.com/docs/x", libelle="x", origine="doc-b")
    ent, _ = cat.fusionner({}, [y("s1", "skills"), y("p1", "plugins"), y("m1", "mcp"), y("m2", "mcp"), y("c1", "commandes")], {"doc-b"})
    assert [(l["lot"], l["entrees"]) for l in cat.lots(ent, "openai")] == [("commandes", 1), ("skills+plugins+mcp", 4)]


def test_d48_description_source_modifiee_repasse_en_attente():
    ent, _ = cat.fusionner({}, [x("/a", "/a")], {"doc-a"})
    k = "claude-code-commandes-a"
    assert commenter(ent, k) == []
    changee = x("/a", "/a"); changee.description_source = "New wording of the upstream description."
    ent, m = cat.fusionner(ent, [changee], {"doc-a"}, jour="2026-09-30")
    assert m["description_source_modifiee"] == [k] and m["usage_modifie"] == []
    assert ent[k]["commentee"] is False and ent[k]["description_source"] == changee.description_source
    assert ent[k]["historique"][-1]["changement"] == "description d'origine modifiée dans la documentation"


def test_d49_nature_de_l_usage(docs):
    e = extraire(docs["cc-fonctionnalites"], **{"page:remote-control": lire("page_remote-control.md")})[0]
    assert e.usage_nature == "syntaxe"
    e = extraire(docs["claude-apps"], **{"page:11101966-use-voice-mode": lire("page_support_voice.md")})[0]
    assert e.usage_nature == "etapes", "page narrative : étapes ou accès recopiés"
    assert all(x.usage_nature == "syntaxe" for x in extraire(docs["cc-commandes"], page=lire("cc_commands.md")))
    nouvelle = cat.nouvelle_entree(e, "2026-09-23")
    assert nouvelle["usage_nature"] == "etapes"


# --- fetch.py --kb de bout en bout (D44) et valider.py --kb ------------------------------------------------

YAML = """
sources:
  - {id: s, perimetre: claude, produit: claude, type: rss, url: https://exemple.test/rss, statut: desactive}
documentation:
  - id: cc-commandes
    perimetre: claude
    produit: claude-code
    extracteur: tableau
    url: https://code.claude.com/docs/en/commands.md
    statut: ok
    note: test
    options: {section: "All commands", categorie: commandes, categorie_si_marque: {"Skill": skills}, exclure: "setup-"}
  - id: cc-reglages
    perimetre: claude
    produit: claude-code
    extracteur: sections
    url: https://code.claude.com/docs/en/settings-reference.md
    statut: ok
    note: test
    options: {niveau: 3, categorie: parametres, exclure_sections: "Enterprise and managed settings"}
  - id: oa-config
    perimetre: openai
    produit: codex
    extracteur: configtable
    url: https://learn.chatgpt.com/docs/config-file/config-reference.md
    statut: ok
    note: test
    options: {section: "config.toml", fin_section: "requirements.toml"}
"""
PAGES = {"https://code.claude.com/docs/en/commands.md": "cc_commands.md",
         "https://code.claude.com/docs/en/settings-reference.md": "cc_settings.md",
         "https://learn.chatgpt.com/docs/config-file/config-reference.md": "oa_config.md"}


class ClientDoc(FauxClient):
    def get(self, url, accept=None):
        self.appels.append(url)
        if url in self.pannes:
            p = self.pannes[url]
            if isinstance(p, Exception):
                raise p
            return Reponse(url, 200, "text/markdown", p)
        return Reponse(url, 200, "text/markdown", lire(PAGES[url]))


@pytest.fixture
def racine_kb(tmp_path):
    (tmp_path / "sources.yaml").write_text(YAML, encoding="utf-8")
    return tmp_path


def lancer_kb(racine, monkeypatch, pannes=None, *produits):
    monkeypatch.setattr(fetch, "Client", lambda: ClientDoc(pannes or {}))
    return fetch.main(["--racine", str(racine), "--sources", str(racine / "sources.yaml"), "--kb", *(produits or ("claude-code", "codex"))])


def test_fetch_kb_de_bout_en_bout(racine_kb, monkeypatch, capsys):
    assert lancer_kb(racine_kb, monkeypatch) == 0
    assert (racine_kb / "raw" / "kb" / "claude-code" / "empreintes.json").exists()
    modif = json.loads((racine_kb / "raw" / "kb" / "claude-modifications.json").read_text())
    assert modif["ajoutees"] and sorted(modif["ajoutees"]) == modif["a_commenter"]
    for per in ("claude", "openai"):
        fichiers = sorted(p.name for p in (racine_kb / "docs" / "data" / "kb" / per).glob("*.json"))
        assert len(fichiers) == 7, "les sept catégories sont écrites, même vides"
    import valider
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 0
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "openai", "--kb"]) == 0
    # deuxième passage identique : rien ne change
    assert lancer_kb(racine_kb, monkeypatch) == 0
    modif = json.loads((racine_kb / "raw" / "kb" / "claude-modifications.json").read_text())
    assert not modif["ajoutees"] and not modif["usage_modifie"] and not modif["retirees"]
    assert "0 modifiée(s)" in capsys.readouterr().out


def test_fetch_kb_page_modifiee_repasse_en_attente(racine_kb, monkeypatch):
    lancer_kb(racine_kb, monkeypatch)
    ent = cat.charger(racine_kb, "claude")
    k = "claude-code-parametres-advisormodel"
    assert cat.appliquer_commentaires(ent, {k: {"description": "Choisit le modèle qui conseille la session.", "statut_usage": "inconnu",
                                                 "recommandation": {"verdict": "ignorer", "pourquoi": "Aucun lien avec les projets actuels."}}}) == []
    cat.ecrire(racine_kb, "claude", ent)
    page = lire("cc_settings.md").replace('"advisorModel": "opus"', '"advisorModel": "sonnet"')
    lancer_kb(racine_kb, monkeypatch, {"https://code.claude.com/docs/en/settings-reference.md": page})
    modif = json.loads((racine_kb / "raw" / "kb" / "claude-modifications.json").read_text())
    assert modif["usage_modifie"] == [k] and modif["pages"]["modifiees"] == ["cc-reglages/page"]
    e = cat.charger(racine_kb, "claude")[k]
    assert e["commentee"] is False and '"sonnet"' in e["usage"] and e["description"].startswith("Choisit")


def test_fetch_kb_echec_ou_format_change(racine_kb, monkeypatch, capsys):
    lancer_kb(racine_kb, monkeypatch)
    avant = cat.charger(racine_kb, "claude")
    # panne réseau : l'ancienne copie sert, rien n'est retiré
    code = lancer_kb(racine_kb, monkeypatch, {"https://code.claude.com/docs/en/commands.md": ErreurReseau("HTTP 503")})
    assert code == 0 and "ÉCHEC   cc-commandes/page" in capsys.readouterr().out
    assert cat.charger(racine_kb, "claude") == avant
    # format changé : erreur explicite, code 3, aucune entrée retirée
    code = lancer_kb(racine_kb, monkeypatch, {"https://code.claude.com/docs/en/commands.md": "# Commands\n\nRefonte.\n"})
    out = capsys.readouterr().out
    assert code == 3 and "FormatInattendu" in out
    assert not any(e["retiree"] for e in cat.charger(racine_kb, "claude").values())


def _base_valide(racine_kb, monkeypatch):
    lancer_kb(racine_kb, monkeypatch)
    return cat.charger(racine_kb, "claude")


@pytest.mark.parametrize("modif, attendu", [
    (lambda e: e.update(usage=""), "`usage` vide"),
    (lambda e: e.update(sources=[]), "`sources`"),
    (lambda e: e.update(commentee=True), "sans `description`"),
    (lambda e: e.update(commentee=True, description="Adds a directory for the session and the files.",
                        recommandation={"verdict": "tester", "pourquoi": "p"}), "en français"),
    (lambda e: e.update(commentee=True, description="Ajoute un répertoire à la session.", recommandation={"verdict": "adopter", "pourquoi": "p"}), "recommandation"),
    (lambda e: e.update(statut_usage="souvent"), "`statut_usage`"),
    (lambda e: e.update(gabarit="court"), "gabarit"),
    (lambda e: e.update(bonus=1), "champs inconnus"),
])
def test_valider_kb_invalide(racine_kb, monkeypatch, capsys, modif, attendu):
    ent = _base_valide(racine_kb, monkeypatch)
    e = next(v for v in ent.values() if v["categorie"] == "commandes")
    modif(e)
    cat.ecrire(racine_kb, "claude", ent) if "bonus" not in e else None
    if "bonus" in e:  # ecrire() garde les champs ; on passe par le fichier pour un champ inconnu
        cat.ecrire(racine_kb, "claude", ent)
    import valider
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 1
    assert attendu in capsys.readouterr().err


def test_valider_kb_identifiant_double(racine_kb, monkeypatch, capsys):
    _base_valide(racine_kb, monkeypatch)
    f = racine_kb / "docs" / "data" / "kb" / "claude" / "commandes.json"
    d = json.loads(f.read_text())
    d["entrees"].append(copy.deepcopy(d["entrees"][0]))
    d["total"] += 1
    f.write_text(json.dumps(d))
    import valider
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 1
    assert "identifiant en double" in capsys.readouterr().err


def test_valider_kb_commentaire_valide(racine_kb, monkeypatch):
    ent = _base_valide(racine_kb, monkeypatch)
    k = next(k for k, v in ent.items() if v["categorie"] == "commandes")
    assert commenter(ent, k) == []
    cat.ecrire(racine_kb, "claude", ent)
    import valider
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 0


def test_kb_refs_inconnus_signales(tmp_path, monkeypatch, date_figee):
    from conftest import ecrire_quotidien
    import valider
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    (tmp_path / "CONTEXTE.md").write_text("### 2.1 trading-sim — x\n", encoding="utf-8")
    ent, _ = cat.fusionner({}, [x("/a", "/a")], {"doc-a"})
    cat.ecrire(tmp_path, "claude", ent)
    brut = {"nouveautes": [{"id": "n1", "produit": "claude-code", "titre": "t", "url": "https://x.test", "officielle": True}]}
    q = ecrire_quotidien(tmp_path, "claude", brut, "2026-09-23")
    d = json.loads(q.read_text()); d["elements"][0]["kb_refs"] = ["claude-code-commandes-a", "claude-code-commandes-zz"]; q.write_text(json.dumps(d))
    assert valider.main(["--racine", str(tmp_path), "--perimetre", "claude", "--date", "2026-09-23"]) == 1


# --- skills ---------------------------------------------------------------------------------------------------

def test_skills_delta_kb():
    racine = Path(fetch.RACINE)
    cc = (racine / ".claude" / "skills" / "delta-kb" / "SKILL.md").read_text(encoding="utf-8")
    tete = cc.split("---\n", 2)[1]
    assert "disable-model-invocation: true" in tete and "model: opus" in tete
    assert "deux premiers lots" in cc and "index.lock" in cc and "**Effets de bord**" in cc and "jamais `usage`" in cc.replace("Tu ne touches jamais à `usage`", "jamais `usage`")
    skill = (racine / ".agents" / "skills" / "delta-kb" / "SKILL.md").read_text(encoding="utf-8")
    prompt = (racine / "prompts" / "codex-delta-kb.md").read_text(encoding="utf-8")
    assert skill.split("---\n", 2)[2].lstrip("\n") == prompt and "**Effets de bord**" in prompt
    assert "allow_implicit_invocation: false" in (racine / ".agents" / "skills" / "delta-kb" / "agents" / "openai.yaml").read_text()
    for f in (racine / ".claude" / "skills" / "delta" / "SKILL.md", racine / "prompts" / "codex-delta.md"):
        assert "fetch.py --kb" in f.read_text(encoding="utf-8"), f"D44 absent de {f.name}"


def test_d47_dry_run_n_ecrit_rien(racine_kb, monkeypatch):
    monkeypatch.setattr(fetch, "Client", lambda: ClientDoc({}))
    args = ["--racine", str(racine_kb), "--sources", str(racine_kb / "sources.yaml"), "--kb", "claude-code", "codex"]
    assert fetch.main(args + ["--dry-run"]) == 0
    assert not (racine_kb / "raw").exists() and not (racine_kb / "docs").exists(), "dry-run : ni cache, ni catalogue"
    assert fetch.main(args) == 0
    empreintes = (racine_kb / "raw" / "kb" / "claude-code" / "empreintes.json").read_text()
    page = lire("cc_settings.md").replace('"advisorModel": "opus"', '"advisorModel": "sonnet"')
    url = "https://code.claude.com/docs/en/settings-reference.md"
    monkeypatch.setattr(fetch, "Client", lambda: ClientDoc({url: page}))
    assert fetch.main(args + ["--dry-run"]) == 0
    assert (racine_kb / "raw" / "kb" / "claude-code" / "empreintes.json").read_text() == empreintes, "empreinte intacte"
    assert '"opus"' in (racine_kb / "raw" / "kb" / "claude-code" / "cc-reglages" / "page.md").read_text()
    # le passage réel suivant voit donc bien le changement
    assert fetch.main(args) == 0
    modif = json.loads((racine_kb / "raw" / "kb" / "claude-modifications.json").read_text())
    assert modif["pages"]["modifiees"] == ["cc-reglages/page"] and modif["usage_modifie"] == ["claude-code-parametres-advisormodel"]
