"""CLI seulement (08/11/2026) : ORQYRA ne suit que Claude Code CLI et Codex CLI.

Claude Desktop, ChatGPT Desktop et le Codex de l'app ChatGPT ne sont plus suivis : ni versions, ni sources de veille
propres à ces apps, ni fiches de la base, et aucune ne doit naître au passage suivant. Les forfaits, quotas et remises
(ChatGPT Pro, comptes Claude) et Remote Control (fonction de Claude Code) restent."""

import json

import pytest

from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.documentation import charger_documentation
from deltalib.kb.modeles import EntreeExtraite
from deltalib.sources import charger_sources

DOCS = {d.id: d for d in charger_documentation(RACINE / "sources.yaml")}
SOURCES = {s.id: s for s in charger_sources(RACINE / "sources.yaml")}

# Documentations entières propres à une app de bureau : désactivées (conservées dans sources.yaml, jamais supprimées).
DOCS_DESKTOP = ("chatgpt-app-commandes", "chatgpt-app-reglages")
# Pages propres à une app de bureau, retirées des listes de pages de leur documentation.
PAGES_DESKTOP = {
    "cc-fonctionnalites": ("desktop", "desktop-linux", "desktop-scheduled-tasks"),
    "oa-fonctionnalites": ("app", "linux/linux-app"),
    "claude-apps": ("10065433-install-claude-desktop", "14729294-open-claude-desktop-with-a-link",
                    "10949351-getting-started-with-local-mcp-servers-on-claude-desktop",
                    "12592343-enabling-and-using-the-desktop-extension-allowlist"),
}
# Fiches de la base issues de ces pages ou documentations : elles doivent être retirées (`retiree`).
FICHES_DESKTOP = ("chatgpt-fonctionnalites-page-app", "chatgpt-fonctionnalites-page-linux-linux-app",
                  "claude-code-fonctionnalites-page-desktop", "claude-code-fonctionnalites-page-desktop-linux",
                  "claude-code-fonctionnalites-page-desktop-scheduled-tasks",
                  "claude-fonctionnalites-page-10065433-install-claude-desktop",
                  "claude-fonctionnalites-page-14729294-open-claude-desktop-with-a-link",
                  "claude-mcp-page-10949351-getting-started-with-local-mcp-servers-on-claude-desktop",
                  "claude-mcp-page-12592343-enabling-and-using-the-desktop-extension-allowlist")


def test_source_changelog_de_l_app_codex_desactivee():
    s = SOURCES["openai-changelog-codex-app"]
    assert s.statut == "desactive" and not s.active, "source conservée mais désactivée : elle n'est plus lue"
    assert "openai-changelog-general" in SOURCES and SOURCES["openai-changelog-general"].active, "le flux général reste suivi"
    assert SOURCES["codex-cli-releases"].active, "la CLI Codex reste suivie"


@pytest.mark.parametrize("doc_id", DOCS_DESKTOP)
def test_documentations_des_apps_de_bureau_desactivees(doc_id):
    assert DOCS[doc_id].statut == "desactive" and not DOCS[doc_id].active


@pytest.mark.parametrize("doc_id, pages", PAGES_DESKTOP.items())
def test_pages_des_apps_de_bureau_absentes_des_documentations(doc_id, pages):
    suivies = DOCS[doc_id].options["pages"]
    assert DOCS[doc_id].active
    assert not [p for p in pages if p in suivies], "page d'app de bureau encore suivie"
    assert not [p for p in suivies if "claude-desktop" in p or p in ("desktop", "desktop-linux", "linux/linux-app")]


def test_aucune_source_ni_page_active_ne_cible_une_app_de_bureau():
    """Garde générale : si une source active ou une page suivie redevient propre à une app de bureau, ce test échoue."""
    for s in SOURCES.values():
        if s.active:
            assert "codex-app" not in (s.url or "") and "desktop" not in (s.url or "").lower(), s.id
    for d in DOCS.values():
        if d.active:
            for page in (d.options.get("pages") or {}):
                assert "claude-desktop" not in page and page not in ("desktop", "desktop-linux", "desktop-scheduled-tasks"), (d.id, page)


def test_fiches_de_la_base_issues_des_apps_de_bureau_retirees():
    base = {k: e for per in ("claude", "openai") for k, e in cat.charger(RACINE, per).items()}
    for ident in FICHES_DESKTOP:
        assert base[ident]["retiree"] is True, ident
    # toute fiche d'une documentation désactivée est retirée
    actives = [k for k, e in base.items() if e["origine"] in DOCS_DESKTOP and not e["retiree"]]
    assert actives == []


def test_a_tester_ne_propose_aucune_fiche_desktop():
    a_tester = json.loads(cat.chemin_a_tester(RACINE).read_text(encoding="utf-8"))
    ids = {e["id"] for e in a_tester["entrees"]}
    assert not ids & set(FICHES_DESKTOP)
    base = {k: e for per in ("claude", "openai") for k, e in cat.charger(RACINE, per).items()}
    assert not [i for i in ids if base[i]["origine"] in DOCS_DESKTOP]


def x(origine="chatgpt-app-commandes"):
    return EntreeExtraite(produit="chatgpt", categorie="raccourcis", nom="Open model picker", usage="Ctrl+Shift+M",
                          description_source="Open the model picker.", url="https://learn.chatgpt.com/docs/reference/commands",
                          libelle="commands", origine=origine)


def test_fusion_retire_les_fiches_d_une_documentation_desactivee():
    k = "chatgpt-raccourcis-open-model-picker"
    ent, _ = cat.fusionner({}, [x()], {"chatgpt-app-commandes"}, jour="2026-11-01")
    assert ent[k]["retiree"] is False
    # la doc est désactivée : plus extraite, donc absente de docs_ok ; sans le mécanisme, la fiche resterait « vivante »
    ent, m = cat.fusionner(ent, [], set(), jour="2026-11-08")
    assert ent[k]["retiree"] is False and m["retirees"] == []
    ent, m = cat.fusionner(ent, [], set(), jour="2026-11-08", docs_desactives={"chatgpt-app-commandes"})
    assert ent[k]["retiree"] is True and m["retirees"] == [k]
    assert ent[k]["historique"][-1] == {"date": "2026-11-08", "changement": "source désactivée (hors du périmètre suivi)"}
    # idempotent : pas de second historique ; une autre origine n'est pas touchée
    n = len(ent[k]["historique"])
    ent, m = cat.fusionner(ent, [], set(), jour="2026-11-09", docs_desactives={"chatgpt-app-commandes"})
    assert m["retirees"] == [] and len(ent[k]["historique"]) == n
    autre, m = cat.fusionner({}, [x("oa-fonctionnalites")], set(), jour="2026-11-08")
    autre, m = cat.fusionner(autre, [], set(), jour="2026-11-09", docs_desactives={"chatgpt-app-commandes"})
    assert autre[k]["retiree"] is False


def test_ids_docs_desactivees_lit_sources_yaml(tmp_path):
    assert cat.ids_docs_desactivees(tmp_path, "openai") == set(), "sans sources.yaml : aucune"
    assert cat.ids_docs_desactivees(RACINE, "openai") == set(DOCS_DESKTOP)
    assert cat.ids_docs_desactivees(RACINE, "claude") == set()


def test_mettre_a_jour_retire_aussi_les_fiches_sans_extraction(tmp_path):
    """Chaîne réelle : mettre_a_jour lit sources.yaml, voit la doc désactivée et retire ses fiches même sans autre doc."""
    (tmp_path / "CONTEXTE.md").write_text("# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n", encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(
        "documentation:\n  - id: chatgpt-app-commandes\n    perimetre: openai\n    produit: chatgpt\n    extracteur: tableau\n"
        "    url: https://learn.chatgpt.com/docs/reference/commands.md\n    statut: desactive\n", encoding="utf-8")
    k = "chatgpt-raccourcis-open-model-picker"
    ent, _ = cat.fusionner({}, [x()], {"chatgpt-app-commandes"}, jour="2026-11-01")
    cat.ecrire(tmp_path, "openai", ent)
    res = cat.mettre_a_jour(tmp_path, "openai", [], ecrire_fichiers=True)
    assert res["retirees"] == [k]
    assert cat.charger(tmp_path, "openai")[k]["retiree"] is True
    assert json.loads(cat.chemin_a_tester(tmp_path).read_text(encoding="utf-8"))["entrees"] == []


def test_forfaits_quotas_et_remote_control_restent_suivis():
    """Les forfaits, quotas et remises (ChatGPT Pro, comptes Claude) et Remote Control ne sont pas des apps de bureau."""
    assert "remote-control" in DOCS["cc-fonctionnalites"].options["pages"]
    assert "17007452-what-is-a-limit-reset" in DOCS["claude-apps"].options["pages"]
    assert "pricing" in DOCS["oa-fonctionnalites"].options["pages"]
    assert SOURCES["openai-tarifs"].active
