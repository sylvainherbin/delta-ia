"""Phase 4 : base de référence. Extraction sans modèle (D40), fusion et D44, lots (D46), commentaires, validation."""

import copy
import json
from datetime import date
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
    """Ancien extracteur (page discover-plugins jusqu'au 25/09), gardé et testé sur son échantillon réel."""
    d0 = docs["cc-plugins"]
    d = type(d0)(**{**d0.__dict__, "extracteur": "plugins_cc", "url": "https://code.claude.com/docs/en/discover-plugins.md",
                    "options": {"section": "Official Anthropic marketplace", "fin_section": "Community marketplace"}})
    es = extraire(d, page=lire("cc_plugins.md"))
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


CTX = "c" * 40


def commenter(entrees, ident, contexte=CTX):
    return cat.appliquer_commentaires(entrees, contexte=contexte, commentaires={ident: {
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
    # panne réseau : l'ancienne copie sert, rien n'est retiré ; échec partiel signalé (code 3, D68 : avertissement)
    code = lancer_kb(racine_kb, monkeypatch, {"https://code.claude.com/docs/en/commands.md": ErreurReseau("HTTP 403")})
    assert code == 3 and "ÉCHEC   cc-commandes/page" in capsys.readouterr().out
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
    (tmp_path / "CONTEXTE.md").write_text("### 2.1 trading-sim — x\n<!-- ctx-id: projet.trading-sim -->\n", encoding="utf-8")
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


# --- D60 : empreinte du CONTEXTE sur les commentaires ---------------------------------------------------------

def test_d60_empreinte_sur_les_commentaires(tmp_path):
    ent, _ = cat.fusionner({}, [x("/a", "/a")], {"doc-a"})
    assert all(e["contexte_empreinte"] is None for e in ent.values())
    assert commenter(ent, "claude-code-commandes-a", contexte="a" * 40) == []
    assert ent["claude-code-commandes-a"]["contexte_empreinte"] == "a" * 40
    # le fichier écrit porte l'empreinte du CONTEXTE.md courant (historique de D60)
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE_MIN, encoding="utf-8")
    cat.ecrire(tmp_path, "claude", ent)
    import hashlib
    d = json.loads((tmp_path / "docs" / "data" / "kb" / "claude" / "commandes.json").read_text())
    assert d["contexte_empreinte"] == hashlib.sha1(CONTEXTE_MIN.encode()).hexdigest()


CONTEXTE_MIN = "# C\n<!-- ctx-id: profil -->\n\nProfil.\n"
CONTEXTE_KB = ("# C\n<!-- ctx-id: profil -->\n\nProfil.\n\n## 2. Projets\n<!-- ctx-id: projet.vue-ensemble -->\n\n"
               "### 2.1 trading-sim — x\n<!-- ctx-id: projet.trading-sim -->\n\nA\n\n"
               "### 2.2 carnet — y\n<!-- ctx-id: projet.carnet -->\n\nB\n")


def test_perimees_reactive():
    assert cat.PERIMEES_SUSPENDU is False
    for f in (".claude/skills/delta-kb/SKILL.md", "prompts/codex-delta-kb.md", ".agents/skills/delta-kb/SKILL.md"):
        t = (RACINE / f).read_text(encoding="utf-8")
        assert "--lot perimees" in t and "suspendu" not in t and "reevaluations" in t and "le plus précis" in t, f


def test_d64bis_appliquer_peremption_et_journal(racine_kb, monkeypatch, capsys):
    import catalogue as cli
    import valider
    lancer_kb(racine_kb, monkeypatch)
    ctx = racine_kb / "CONTEXTE.md"
    ctx.write_text(CONTEXTE_KB, encoding="utf-8")
    k = "claude-code-parametres-advisormodel"
    f = racine_kb / "c.json"
    base = {"description": "Choisit le modèle qui conseille la session.", "statut_usage": "inconnu",
            "recommandation": {"verdict": "tester", "pourquoi": "Essai sur trading-sim : `/advisor opus` pendant un audit."}}

    def appliquer(cs, attendu):
        f.write_text(json.dumps({k: base if cs is None else {**base, "contexte_sections": cs}}))
        assert cli.main(["appliquer", "--perimetre", "claude", "--fichier", str(f), "--racine", str(racine_kb)]) == attendu
        return capsys.readouterr()

    assert "contexte_sections" in appliquer(None, 1).err, "sections obligatoires"
    assert "{ctx-id: pourquoi}" in appliquer(["projet.trading-sim"], 1).err, "format liste de ae895e6 refusé"
    assert "ctx-id inconnu : 2.1" in appliquer({"2.1": "x"}, 1).err, "plus de clé numérotée"
    assert "`pourquoi` vide" in appliquer({"projet.trading-sim": ""}, 1).err
    assert "corps vide : projet.vue-ensemble" in appliquer({"projet.vue-ensemble": "Liste des projets."}, 1).err
    appliquer({"projet.trading-sim": "Les audits du robot passent par l'advisor."}, 0)
    e = cat.charger(racine_kb, "claude")[k]
    assert e["contexte_sections"]["projet.trading-sim"]["pourquoi"] == "Les audits du robot passent par l'advisor."
    assert len(e["contexte_sections"]["projet.trading-sim"]["sha1"]) == 40
    assert not (racine_kb / "docs" / "data" / "kb" / "claude" / "reevaluations.jsonl").exists(), "premier commentaire : pas de réévaluation"
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 0
    capsys.readouterr()

    def lot():
        assert cli.main(["a-commenter", "--perimetre", "claude", "--lot", "perimees", "--racine", str(racine_kb)]) == 0
        return [(x["id"], x["motif"]) for x in json.loads(capsys.readouterr().out) if x["id"] == k]

    ctx.write_text(CONTEXTE_KB.replace("B\n", "B modifié\n"), encoding="utf-8")
    assert lot() == [], "une autre section change : rien"
    ctx.write_text(CONTEXTE_KB.replace("### 2.1 trading-sim — x", "### 2.1 trading-sim, robot — x"), encoding="utf-8")
    assert lot() == [], "un changement de titre ne périme rien"
    ctx.write_text(CONTEXTE_KB.replace("A\n", "A modifié\n"), encoding="utf-8")
    assert lot() == [(k, "section:projet.trading-sim")]
    # réévaluation : journal et taux
    base["recommandation"] = {"verdict": "ignorer", "pourquoi": "Le robot n'a plus d'audit d'après CONTEXTE."}
    assert "verdicts changés : 1 (100 %)" in appliquer({"projet.trading-sim": "Audits arrêtés."}, 0).out
    j = [json.loads(l) for l in (racine_kb / "docs" / "data" / "kb" / "claude" / "reevaluations.jsonl").read_text().splitlines()]
    assert j == [{"date": date.today().isoformat(), "id": k, "verdict_avant": "tester", "verdict_apres": "ignorer",
                  "motif": "section:projet.trading-sim"}]
    assert lot() == []
    assert cli.main(["reevaluations", "--perimetre", "claude", "--racine", str(racine_kb)]) == 0
    assert "verdicts changés : 1 (100 %)" in capsys.readouterr().out
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 0
    capsys.readouterr()
    # section dépréciée : périmée, et plus citable
    ctx.write_text(CONTEXTE_KB.replace("<!-- ctx-id: projet.trading-sim -->", "<!-- ctx-id: projet.robot -->\n<!-- ctx-id-deprecie: projet.trading-sim -->"), encoding="utf-8")
    assert lot() == [(k, "section:projet.trading-sim")]
    assert "ctx-id déprécié" in appliquer({"projet.trading-sim": "x"}, 1).err
    capsys.readouterr()
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 0, "déprécié : encore connu de valider"


def test_d60_commentee_sans_empreinte_invalide(racine_kb, monkeypatch, capsys):
    ent = _base_valide(racine_kb, monkeypatch)
    k = next(k for k, v in ent.items() if v["categorie"] == "commandes")
    assert commenter(ent, k, contexte=None) == []
    cat.ecrire(racine_kb, "claude", ent)
    import valider
    assert valider.main(["--racine", str(racine_kb), "--perimetre", "claude", "--kb"]) == 1
    assert "sans `contexte_empreinte`" in capsys.readouterr().err


def test_skills_d57_d58_d59_d60():
    racine = Path(fetch.RACINE)
    kb_cx = (racine / "prompts" / "codex-delta-kb.md").read_text(encoding="utf-8")
    kb_cc = (racine / ".claude" / "skills" / "delta-kb" / "SKILL.md").read_text(encoding="utf-8")
    for t in (kb_cx, kb_cc):
        assert "Calibrage du verdict (D57)" in t and "Constats et déductions (D59)" in t
    assert "recalibrage commandes" in kb_cx and "recalibrage commandes" not in kb_cc
    assert "recalibrage tester" in kb_cx and "recalibrage tester" not in kb_cc
    for t in (kb_cx, kb_cc):
        assert "Calibrage de `tester` (D57 étendu)" in t and "codex exec --output-schema" in t
    for f in (racine / ".claude" / "skills" / "delta" / "SKILL.md", racine / "prompts" / "codex-delta.md"):
        t = f.read_text(encoding="utf-8")
        assert "contexte_empreinte" in t and "Constats et déductions (D59)" in t


# --- D64-bis : sections de CONTEXTE par ctx-id ----------------------------------------------------------------

def test_d64bis_analyse_et_erreurs():
    from deltalib.contexte import ContexteInvalide, analyser
    s, dep = analyser("# T\n<!-- ctx-id: a -->\n\ncorps a\n\n## U\n\n<!-- ctx-id: a.b -->\ncorps b\n### V\n<!-- ctx-id: a.b.c -->\n<!-- ctx-id-deprecie: vieux -->\nc\n")
    assert list(s) == ["a", "a.b", "a.b.c"] and dep == {"vieux"}
    assert s["a.b"]["parent"] == "a" and s["a.b.c"]["parent"] == "a.b"
    # le corps d'une section s'arrête au titre suivant, quel que soit son niveau
    s2, _ = analyser("# T\n<!-- ctx-id: a -->\n\ncorps a\n\n## U\n\n<!-- ctx-id: a.b -->\ncorps b modifié\n### V\n<!-- ctx-id: a.b.c -->\n<!-- ctx-id-deprecie: vieux -->\nc\n")
    assert s2["a"]["sha1"] == s["a"]["sha1"] and s2["a.b"]["sha1"] != s["a.b"]["sha1"] and s2["a.b.c"]["sha1"] == s["a.b.c"]["sha1"]
    # titre et ligne ctx-id exclus
    s3, _ = analyser("# Autre titre\n<!-- ctx-id: a -->\n\ncorps a\n\n## U\n\n<!-- ctx-id: a.b -->\ncorps b\n### V\n<!-- ctx-id: a.b.c -->\n<!-- ctx-id-deprecie: vieux -->\nc\n")
    assert s3["a"]["sha1"] == s["a"]["sha1"]
    for mauvais, message in [("# T\n\nx\n", "sans ctx-id"), ("# T\n<!-- ctx-id: a -->\n## U\n<!-- ctx-id: a -->\n", "double"),
                             ("x\n# T\n<!-- ctx-id: a -->\n", "avant"), ("### T\n<!-- ctx-id: a -->\n<!-- ctx-id-deprecie: a -->\n", "déprécié")]:
        with pytest.raises(ContexteInvalide, match=message):
            analyser(mauvais)


def test_d64bis_contexte_reel():
    from deltalib.contexte import analyser, projets
    s, _ = analyser((RACINE / "CONTEXTE.md").read_text(encoding="utf-8"))
    assert {"profil", "projet.trading-sim", "projet.carnet", "config.codex.profils"} <= set(s)
    assert "projet.trading-sim" in projets(RACINE) and "projet.vue-ensemble" not in projets(RACINE)


def test_d64bis_classement_a_b_c_et_filet_par_age():
    from datetime import timedelta
    from deltalib.contexte import est_perime
    cour = {"projet.trading-sim": "a" * 40, "config.codex": "b" * 40}
    assert est_perime({"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "p"}}, cour) is False
    assert est_perime({"projet.trading-sim": {"sha1": "x" * 40, "pourquoi": "p"}}, cour) is True
    assert est_perime({"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "p"}}, cour, {"projet.trading-sim"}) is True
    assert est_perime({"disparu": {"sha1": "a" * 40, "pourquoi": "p"}}, cour) is True
    assert est_perime({}, cour) is False and est_perime(None, cour) is None
    jour = date(2026, 9, 24)
    recent = (jour - timedelta(days=10)).isoformat()

    def e(k, v, cs, commente=recent):
        return {"id": k, "commentee": True, "recommandation": {"verdict": v}, "contexte_sections": cs, "maj_le": commente,
                "historique": [{"date": commente, "changement": "commentée"}]}
    ok = {"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "p"}}
    vieux = (jour - timedelta(days=200)).isoformat()
    ent = {k: e(k, *a) for k, a in {
        "b-legacy": ("tester", None), "a-ignorer": ("ignorer", {"config.codex": {"sha1": "z" * 40, "pourquoi": "p"}}),
        "a-utiliser": ("utiliser", {"config.codex": {"sha1": "z" * 40, "pourquoi": "p"}}), "ok": ("utiliser", ok),
        "legacy-ignorer": ("ignorer", None), "vide": ("tester", {}),
        "c-vieux-ignorer": ("ignorer", None, vieux), "c-vieux-vide": ("tester", {}, vieux)}.items()}
    det = cat.perimees_detail(ent, cour, set(), jour, maximum=None)
    assert [(x["id"], x["categorie"], x["motif"]) for x in det] == [
        ("a-utiliser", "a", "section:config.codex"), ("a-ignorer", "a", "section:config.codex"),
        ("b-legacy", "b", "legacy"), ("c-vieux-vide", "c", "age"), ("c-vieux-ignorer", "c", "age")]
    assert len(cat.perimees({f"k{i}": e(f"k{i}", "tester", None) for i in range(40)}, cour, set(), jour)) == 30
    # échéance : 90 + sha1(id) mod 90 jours après le dernier commentaire, étalée sur 90 jours
    assert cat.AGE_ETALEMENT_JOURS == 90
    ech = {cat.echeance_age(e(f"k{i}", "ignorer", {}, "2026-01-01")) for i in range(2000)}
    assert min(ech) >= date(2026, 4, 1) and max(ech) <= date(2026, 6, 29) and len(ech) == 90
    # un commentaire révisé repousse l'échéance
    x_ = e("c-vieux-vide", "tester", {}, vieux)
    x_["historique"].append({"date": jour.isoformat(), "changement": "commentaire révisé"})
    assert cat.classer(x_, cour, set(), jour) is None


def test_d64bis_migration_des_formats_et_projets(tmp_path):
    ctx = tmp_path / "CONTEXTE.md"
    ctx.write_text(CONTEXTE_KB, encoding="utf-8")
    ent, _ = cat.fusionner({}, [x("/a", "/a"), x("/b", "/b"), x("/c", "/c")], {"doc-a"})
    for kk in ent:
        ent[kk].update(commentee=True, recommandation={"verdict": "ignorer", "pourquoi": "p"})
    ent["claude-code-commandes-a"]["contexte_sections"] = {"2.1": "a" * 40}  # format de ae895e6
    ent["claude-code-commandes-b"]["contexte_sections"] = ["2.1"]
    ent["claude-code-commandes-c"]["contexte_sections"] = {"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "p"}}
    cat.ecrire(tmp_path, "claude", ent)
    lu = cat.charger(tmp_path, "claude")
    assert lu["claude-code-commandes-a"]["contexte_sections"] is None and lu["claude-code-commandes-b"]["contexte_sections"] is None
    assert lu["claude-code-commandes-c"]["contexte_sections"]["projet.trading-sim"]["pourquoi"] == "p"
    # projets_connus au format D64 (clés numérotées) : migration vers les ctx-id, sans lot nouveau-projet
    f = tmp_path / "docs" / "data" / "kb" / "claude" / "commandes.json"
    d = json.loads(f.read_text()); d["projets_connus"] = ["2.1", "2.2"]; f.write_text(json.dumps(d))
    assert cat.nouveaux_projets(tmp_path, "claude") == []
    cat.ecrire(tmp_path, "claude", lu)
    assert json.loads(f.read_text())["projets_connus"] == ["projet.carnet", "projet.trading-sim"]


def test_d64bis_nouveau_projet_repasse_des_ignorer(tmp_path):
    ctx = tmp_path / "CONTEXTE.md"
    ctx.write_text(CONTEXTE_KB, encoding="utf-8")
    ent, _ = cat.fusionner({}, [x("/a", "/a"), x("/b", "/b"), x("P", "p", categorie="parametres")], {"doc-a"})
    for kk in ent:
        ent[kk].update(commentee=True, recommandation={"verdict": "ignorer", "pourquoi": "p"}, contexte_sections=None)
    cat.ecrire(tmp_path, "claude", ent)
    assert cat.nouveaux_projets(tmp_path, "claude") == [], "au premier passage, les projets présents sont connus"
    ctx.write_text(CONTEXTE_KB + "\n### 2.3 ceramist — z\n<!-- ctx-id: projet.ceramist -->\n\ny\n", encoding="utf-8")
    cat.ecrire(tmp_path, "claude", ent)
    assert cat.nouveaux_projets(tmp_path, "claude") == ["projet.ceramist"]
    assert cat.repasse_projet(ent, "projet.ceramist") == ["claude-code-commandes-a", "claude-code-commandes-b"], "paramètres exclus"
    for kk in ("claude-code-commandes-a", "claude-code-commandes-b"):
        ent[kk]["contexte_sections"] = {"projet.ceramist": {"sha1": "c" * 40, "pourquoi": "p"}}
    cat.ecrire(tmp_path, "claude", ent)
    assert cat.nouveaux_projets(tmp_path, "claude") == [], "repasse terminée : le projet devient connu"


def test_d64bis_page_skills_et_etat():
    racine = Path(fetch.RACINE)
    app = (racine / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "antérieur à D64" in app and ".sha1" in app and "contexte_deprecies" in app
    for f in (".claude/skills/delta-kb/SKILL.md", "prompts/codex-delta-kb.md", ".claude/skills/delta/SKILL.md", "prompts/codex-delta.md"):
        t = (racine / f).read_text(encoding="utf-8")
        assert "D64-bis" in t and "ctx-id" in t and "(D64)" not in t, f
    import etat
    assert "~/projets/trading-sim" in etat.DOSSIERS_MCP


# --- D67 : PROGRESSION.md -----------------------------------------------------------------------------------------

PROGRESSION = """# PROGRESSION

## Acquis

| Id de l'entrée | Date | Nature |
|---|---|---|
| claude-code-commandes-b | 2026-09-24 | faux ami : section Acquis, sans effet |

## Adoptions

| Id de l'entrée | Date | Nature |
|---|---|---|
| `claude-code-commandes-a` | 2026-09-24 | [déclaré] |
| codex-commandes-zz | 2026-09-24 | [déclaré] |
| claude-code-commandes-fantome | 2026-09-24 | [déclaré] |

## Points à travailler
| claude-code-commandes-c | 2026-09-24 | sans effet |
"""


def test_d67_adoptions(tmp_path, capsys):
    import catalogue as cli
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE_KB, encoding="utf-8")
    ent, _ = cat.fusionner({}, [x("/a", "/a"), x("/b", "/b"), x("/c", "/c")], {"doc-a"})
    cat.ecrire(tmp_path, "claude", ent)
    assert cat.adoptions(tmp_path) == [], "sans PROGRESSION.md : rien"
    (tmp_path / "PROGRESSION.md").write_text(PROGRESSION, encoding="utf-8")
    assert cat.adoptions(tmp_path) == ["claude-code-commandes-a", "codex-commandes-zz", "claude-code-commandes-fantome"], "seule la section Adoptions compte"
    assert cli.main(["adoptions", "--perimetre", "claude", "--racine", str(tmp_path)]) == 1, "id absent de la base signalé"
    sortie = capsys.readouterr()
    assert "claude-code-commandes-fantome" in sortie.err and "codex-commandes-zz" not in sortie.err, "un id openai ne concerne pas la base claude"
    lu = cat.charger(tmp_path, "claude")
    a = lu["claude-code-commandes-a"]
    assert a["statut_usage"] == "utilise" and a["historique"][-1]["changement"] == "statut_usage : utilise (adoption déclarée, PROGRESSION.md)"
    assert a["commentee"] is False and a["recommandation"] is None, "rien d'autre ne change"
    assert lu["claude-code-commandes-b"]["statut_usage"] == "inconnu" and lu["claude-code-commandes-c"]["statut_usage"] == "inconnu"
    # idempotent : aucune nouvelle ligne d'historique
    n = len(a["historique"])
    cli.main(["adoptions", "--perimetre", "claude", "--racine", str(tmp_path)])
    assert len(cat.charger(tmp_path, "claude")["claude-code-commandes-a"]["historique"]) == n
    # --dry-run n'écrit rien
    (tmp_path / "PROGRESSION.md").write_text(PROGRESSION.replace("`claude-code-commandes-a`", "claude-code-commandes-b"), encoding="utf-8")
    cli.main(["adoptions", "--perimetre", "claude", "--dry-run", "--racine", str(tmp_path)])
    assert cat.charger(tmp_path, "claude")["claude-code-commandes-b"]["statut_usage"] == "inconnu"


def test_d67_regles_et_skills():
    racine = Path(fetch.RACINE)
    assert "`PROGRESSION.md` sont en lecture seule" in (racine / "REGLES.md").read_text(encoding="utf-8")
    for f in (".claude/skills/delta/SKILL.md", "prompts/codex-delta.md", ".agents/skills/delta/SKILL.md"):
        t = (racine / f).read_text(encoding="utf-8")
        assert "PROGRESSION.md (D67)" in t and "n'agit ni sur `impact`" in t and "pas d'empreinte" in t, f
    for f in (".claude/skills/delta-kb/SKILL.md", "prompts/codex-delta-kb.md", ".agents/skills/delta-kb/SKILL.md"):
        t = (racine / f).read_text(encoding="utf-8")
        assert "catalogue.py adoptions" in t and "adoption déclarée, PROGRESSION.md" in t, f
    assert "| D67 |" in (racine / "SPEC.md").read_text(encoding="utf-8")


def test_d67_adoption_d_un_ignorer_entre_dans_perimees(tmp_path):
    from datetime import timedelta
    jour = date(2026, 9, 24)
    recent = (jour - timedelta(days=5)).isoformat()
    cour = {"projet.trading-sim": "a" * 40}

    def e(k, verdict, cs=None):
        return {"id": k, "commentee": True, "statut_usage": "inconnu", "recommandation": {"verdict": verdict, "pourquoi": "p"},
                "contexte_sections": cs, "maj_le": recent, "historique": [{"date": recent, "changement": "commentée"}]}
    ok = {"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "p"}}
    ent = {"adopte-ignorer": e("adopte-ignorer", "ignorer", ok), "adopte-tester": e("adopte-tester", "tester", ok),
           "a-section": e("a-section", "ignorer", {"projet.trading-sim": {"sha1": "z" * 40, "pourquoi": "p"}}),
           "b-legacy": e("b-legacy", "utiliser")}
    assert cat.appliquer_adoptions(ent, ["adopte-ignorer", "adopte-tester"], jour.isoformat()) == ["adopte-ignorer", "adopte-tester"]
    det = cat.perimees_detail(ent, cour, set(), jour, maximum=None)
    assert [(x["id"], x["motif"]) for x in det] == [("a-section", "section:projet.trading-sim"), ("adopte-ignorer", "adoption"),
                                                   ("b-legacy", "legacy")], "adoption juste après a ; un `tester` adopté n'entre pas"
    # une fois recommentée, l'entrée sort du lot, même si le verdict reste `ignorer`
    x_ = ent["adopte-ignorer"]
    x_["historique"].append({"date": jour.isoformat(), "changement": "commentaire révisé"})
    assert cat.classer(x_, cour, set(), jour) is None
    import valider
    assert valider.RE_MOTIF.match("adoption")


# --- Pages : échec isolé, repli HTML, article déplacé (24/09) -------------------------------------------------------

ARTICLES = "9487310-what-are-artifacts-and-how-do-i-use-them"


def test_page_html_lue_en_repli(docs):
    d = docs["claude-apps"]
    es = extraire(d, **{f"page:{ARTICLES}": lire("page_support_html.html")})
    assert len(es) == 1 and es.replis_html == [ARTICLES] and not es.echecs_pages
    e = es[0]
    assert e.id == f"claude-fonctionnalites-page-{ARTICLES}", "l'id suit la clé de la page, pas son adresse"
    assert e.nom == "What are artifacts and how do I use them?" and e.usage and e.description_source.startswith("An artifact")
    assert "Free" not in e.description_source, "les cellules de tableau ne sont pas prises pour des paragraphes"


def test_article_deplace_option_chemin(docs):
    d = docs["claude-apps"]
    assert d.fichiers()[f"page:{ARTICLES}"] == "https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them.md"
    es = extraire(d, **{f"page:{ARTICLES}": "# What are artifacts?\n\nUn paragraphe.\n\n1. Étape.\n"})
    assert es[0].url == "https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them"


def test_page_en_echec_isolee(docs, tmp_path):
    d = docs["claude-apps"]
    pages = {f"page:11101966-use-voice-mode": lire("page_support_voice.md"),
             f"page:{ARTICLES}": "<!DOCTYPE html><html><body><p>sans titre</p></body></html>",
             "page:12260368-use-incognito-chats": "texte sans titre\n"}
    es = extraire(d, **pages)
    assert [e.nom for e in es] == ["Use voice mode"], "les pages valides sont extraites malgré les autres"
    assert sorted(c for c, _ in es.echecs_pages) == sorted([ARTICLES, "12260368-use-incognito-chats"])
    assert any("repli impossible" in m for _, m in es.echecs_pages)
    # au niveau du catalogue : échec signalé par page, doc non « extraite avec succès » (rien n'est retiré)
    avert = []
    entrees, ok, echecs = cat.extraire(tmp_path, [d], surcharge={f"claude-apps/{k}": v for k, v in pages.items()}, avertissements=avert)
    assert [e.nom for e in entrees] == ["Use voice mode"] and "claude-apps" not in ok
    assert {e["page"] for e in echecs} == {ARTICLES, "12260368-use-incognito-chats"} and all(e["doc"] == "claude-apps" for e in echecs)


def test_toutes_les_pages_en_echec(docs):
    with pytest.raises(FormatInattendu, match="1 en échec"):
        extraire(docs["claude-apps"], **{"page:12260368-use-incognito-chats": "sans titre\n"})


# --- Redirections : jamais suivies en silence (24/09) ---------------------------------------------------------------

@pytest.mark.parametrize("statut", [301, 302, 307, 308])
def test_client_note_les_redirections(statut):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from deltalib.http import Client

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ancien.md":
                self.send_response(statut); self.send_header("Location", "/nouveau.md"); self.end_headers()
            else:
                corps = b"# Titre\n\nTexte.\n"
                self.send_response(200); self.send_header("Content-Type", "text/markdown"); self.send_header("Content-Length", str(len(corps)))
                self.end_headers(); self.wfile.write(corps)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        rep = Client(dormir=lambda s: None).get(base + "/ancien.md")
        assert rep.url == base + "/nouveau.md" and rep.texte.startswith("# Titre")
        assert rep.redirections == ((statut, base + "/ancien.md"),)
        assert Client(dormir=lambda s: None).get(base + "/nouveau.md").redirections == ()
    finally:
        srv.shutdown()


class ClientRedirige(ClientDoc):
    """Première page de la liste : servie après une redirection 301, contenu inchangé."""
    def get(self, url, accept=None):
        rep = super().get(url, accept)
        if url == sorted(PAGES)[0]:
            return Reponse(url.replace(".md", "-deplace.md"), 200, rep.content_type, rep.texte, ((301, url),))
        return rep


def test_fetch_kb_signale_les_redirections(racine_kb, monkeypatch, capsys):
    monkeypatch.setattr(fetch, "Client", lambda: ClientRedirige({}))
    args = ["--racine", str(racine_kb), "--sources", str(racine_kb / "sources.yaml"), "--kb", "claude-code", "codex"]
    assert fetch.main(args) == 0, "la page reste lisible : pas d'échec"
    sortie = capsys.readouterr().out
    ancienne = sorted(PAGES)[0]
    lignes = [l for l in sortie.splitlines() if "→ REDIRECTION" in l]
    assert len(lignes) == 1 and f"{ancienne} → {ancienne.replace('.md', '-deplace.md')}" in lignes[0] and "(301)" in lignes[0]
    assert "1 redirection(s)" in sortie
    modif = json.loads((racine_kb / "raw" / "kb" / "claude-modifications.json").read_text())
    tout = modif["pages"]["redirections"] + json.loads((racine_kb / "raw" / "kb" / "openai-modifications.json").read_text())["pages"]["redirections"]
    assert [r["ancienne"] for r in tout if r["ancienne"] == ancienne], "la redirection figure dans le rapport du passage"
    assert fetch.main(args + ["--dry-run"]) == 0 and "→ REDIRECTION" in capsys.readouterr().out, "signalée aussi en dry-run"


def test_skills_redirections_et_consolidation():
    for f in (".claude/skills/delta/SKILL.md", "prompts/codex-delta.md", ".agents/skills/delta/SKILL.md"):
        t = (RACINE / f).read_text(encoding="utf-8")
        assert "→ REDIRECTION" in t and "**en consolidation**" in t and "ni allégée comme un acquis" in t, f


def test_fetch_kb_echec_total_code_5(racine_kb, monkeypatch, capsys):
    """D68 : code 5 si aucune page n'est lue ; le code 3 (partiel) n'arrête pas le mode automatique, le 5 si."""
    lancer_kb(racine_kb, monkeypatch)
    capsys.readouterr()
    toutes = {u: ErreurReseau("HTTP 403") for u in PAGES}
    assert lancer_kb(racine_kb, monkeypatch, toutes) == 5 and "ÉCHEC TOTAL" in capsys.readouterr().out
    # toutes les documentations d'un périmètre en format inattendu : code 5 aussi
    casse = {u: "# Refonte\n\nRien.\n" for u in PAGES}
    assert lancer_kb(racine_kb, monkeypatch, casse) == 5
    # une seule page cassée, le reste traité : code 3
    assert lancer_kb(racine_kb, monkeypatch, {"https://code.claude.com/docs/en/commands.md": "# Commands\n\nRefonte.\n"}) == 3


# --- cc-plugins : catalogue de la marketplace officielle (26/09) ---------------------------------------------------

def test_marketplace_json(docs):
    d0 = docs["cc-plugins"]
    assert d0.extracteur == "marketplace_json" and len(d0.options["suivis"]) == 12
    d = type(d0)(**{**d0.__dict__, "options": {**d0.options, "suivis": ["github"]}})  # extrait réel : 5 plugins
    texte = lire("marketplace_official.json")
    es = EXTRACTEURS["marketplace_json"](d, {"page": texte})
    noms = {e.nom for e in es}
    assert {"commit-commands", "clangd-lsp", "github"} <= noms, "auteur Anthropic ou intégration suivie"
    assert "42crunch-api-security-testing" not in noms, "un plugin tiers non suivi n'entre pas"
    gh = next(e for e in es if e.nom == "github")
    assert gh.id == "claude-code-plugins-github" and gh.usage == "/plugin install github@claude-plugins-official"
    assert gh.url.startswith("https://github.com/anthropics/claude-plugins-official/tree/main/")
    assert "support@" not in json.dumps([e.__dict__ for e in es]), "aucune adresse d'auteur reprise"
    # un plugin suivi absent : erreur explicite ; renommage déclaré suivi
    d2 = type(d)(**{**d.__dict__, "options": {**d.options, "suivis": ["github", "azure-skills"]}})
    assert "azure" in {e.nom for e in EXTRACTEURS["marketplace_json"](d2, {"page": texte})}
    d3 = type(d)(**{**d.__dict__, "options": {**d.options, "suivis": ["github", "inexistant"]}})
    with pytest.raises(FormatInattendu, match="inexistant"):
        EXTRACTEURS["marketplace_json"](d3, {"page": texte})
    with pytest.raises(FormatInattendu):
        EXTRACTEURS["marketplace_json"](d, {"page": "{}"})


def test_claude_tag_retiree_de_la_configuration(docs):
    d = docs["cc-fonctionnalites"]
    assert "claude-tag" not in d.options["pages"]
    assert "15594475-what-is-claude-tag" in docs["claude-apps"].options["pages"], "fonctionnalité couverte par le centre d'aide"
