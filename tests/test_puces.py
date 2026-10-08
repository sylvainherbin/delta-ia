"""D95 : notes de version découpées en puces dans le brut, sur des extraits réels réduits (Claude Code 2.1.293,
Codex CLI 0.161.0), et avertissement R2 de valider.py."""

import json
from pathlib import Path

import pytest

import fetch
import valider as v
from conftest import FauxClient
from deltalib.modeles import Element
from deltalib.puces import ajouter_puces, decouper_puces, genre_de, noms_de
from deltalib.sources import Source

FIXTURES = Path(__file__).parent / "fixtures"


def lire(nom):
    return (FIXTURES / nom).read_text(encoding="utf-8")


def test_claude_code_2_1_293_ajouts_et_correctifs():
    puces = decouper_puces(lire("puces_cc_2_1_293.md"))
    assert [p["genre"] for p in puces] == ["ajout"] * 3 + ["correctif"] * 3 + ["modification"]
    assert puces[0]["noms"] == ["claude-haiku-5-5"]
    assert puces[1]["noms"] == ["agentType", "subagentStatusLine"]
    assert puces[2]["noms"] == ["isDeferred", "$.tool.register", "false"]
    assert puces[0]["texte"].startswith("Added Claude Haiku 5.5 (`claude-haiku-5-5`)")
    assert puces[5]["noms"] == ["←"]
    assert all(set(p) == {"genre", "texte", "noms"} for p in puces)


def test_codex_cli_0_161_0_genre_par_titre_de_section_et_etiquette_de_pr():
    puces = decouper_puces(lire("puces_codex_cli_0_161_0.md"))

    def puce(debut):
        return next(p for p in puces if p["texte"].startswith(debut))
    # « New Features » tranche quand le premier mot ne dit rien
    assert puce("GPT-6.1 Sol is now")["genre"] == "ajout"
    mcp = puce("Sign in to MCP servers")
    assert mcp["genre"] == "ajout" and mcp["noms"] == ["/mcp login <name>"]
    # « Bug Fixes » de même ; « Documentation » et « Chores » ne tranchent pas
    assert [puce(d)["genre"] for d in ("Approved", "Explicit", "Elevated")] == ["correctif"] * 3
    assert puce("Authentication guidance")["genre"] == "autre"
    assert puce("Publishing an older")["genre"] == "autre"
    # étiquette « #49290 » ignorée pour lire le verbe : « Add » = ajout, « Use » = autre, « Remove » = retrait
    assert puce("#49290 Add")["genre"] == "ajout"
    assert puce("#49246 Use")["genre"] == "autre"
    assert puce("#49395 Remove")["genre"] == "retrait"


def test_genres_par_premier_mot():
    cas = {"Added `x`": "ajout", "New: `x`": "ajout", "Introduced `x`": "ajout", "Changed `x`": "modification",
           "Improved `x`": "modification", "Updated `x`": "modification", "Renamed `x`": "modification",
           "Fixed `x`": "correctif", "Removed `x`": "retrait", "Deprecated `x`": "retrait", "Dropped `x`": "retrait",
           "Le reste": "autre", "Ajouté `x`": "ajout", "Corrigé `x`": "correctif", "Supprimé `x`": "retrait",
           "We've launched **Claude Haiku 5.5**": "ajout", "We've lowered the price": "modification",
           "[Claude Tag] Fixed Claude in Slack": "correctif", "Windows: Fixed stopping": "correctif"}
    for texte, genre in cas.items():
        assert genre_de(texte) == genre, texte
    assert genre_de("Autre chose", "Improvements and bug fixes") == "modification"
    assert genre_de("Autre chose", "Documentation") == "autre"


def test_puces_sur_plusieurs_lignes_et_sous_puces():
    contenu = "Intro\n\n* Added `/a`, qui fait\n  deux lignes\n  * sous-puce `b`\n* Fixed `c`\n\n## Fin\n\n- Removed `d`\n"
    puces = decouper_puces(contenu)
    assert [(p["genre"], p["texte"]) for p in puces] == [
        ("ajout", "Added `/a`, qui fait deux lignes sous-puce `b`"), ("correctif", "Fixed `c`"), ("retrait", "Removed `d`")]
    assert puces[0]["noms"] == ["/a", "b"]


def test_sans_puce_pas_de_champ():
    assert decouper_puces("Un paragraphe sans puce.\n\n**Titre**\n\nAutre paragraphe.") is None
    assert decouper_puces("") is None
    assert noms_de("`a` puis `a` et `b`") == ["a", "b"]
    e = Element(id="x", produit="claude", titre="t", version=None, date_publication=None, url="https://x", contenu="c",
                source_id="s", officielle=True)
    assert "puces" not in e.en_dict()
    e.puces = [{"genre": "ajout", "texte": "Added `x`", "noms": ["x"]}]
    assert e.en_dict()["puces"] == e.puces


def test_ajouter_puces_seulement_pour_les_sources_declarees():
    def source(sid, **options):
        return Source(id=sid, perimetre="claude", produit="claude", type="html", url="https://x", statut="ok", options=options)

    def element(sid, ident="a"):
        return Element(id=ident, produit="claude", titre="t", version=None, date_publication=None, url="https://x",
                       contenu="- Added `x`\n- Fixed y", source_id=sid, officielle=True)
    avec, sans, initial = element("notes"), element("blog", "b"), element("notes", "etat-initial-claude-1")
    contenu = avec.contenu
    ajouter_puces([avec, sans, initial], [source("notes", puces=True), source("blog")])
    assert [p["genre"] for p in avec.puces] == ["ajout", "correctif"] and avec.contenu == contenu
    assert sans.puces is None and initial.puces is None


@pytest.fixture
def racine(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    return tmp_path


def test_fetch_ecrit_les_puces_des_notes_de_version(racine):
    for p in ("claude", "openai"):
        fetch.main(["--racine", str(racine), "--perimetre", p])
    nouveautes = {}
    for p in ("claude", "openai"):
        nouveautes.update({n["id"]: n for n in json.loads((racine / "raw" / f"{p}-nouveautes.json").read_text())["nouveautes"]})
    cc = [n for n in nouveautes.values() if n["source_id"] == "claude-code-changelog"]
    assert cc and all("puces" in n for n in cc)
    assert any(p["genre"] == "ajout" for n in cc for p in n["puces"])
    assert all(n["contenu"] for n in cc)
    codex = [n for n in nouveautes.values() if n["source_id"] == "codex-cli-releases"]
    assert codex and all("puces" in n for n in codex)
    # une source qui ne déclare pas l'option n'a pas de champ ; aucune liste vide nulle part
    assert not any("puces" in n for n in nouveautes.values() if n["source_id"] in ("anthropic-newsroom", "openai-news"))
    assert not any(n.get("puces") == [] for n in nouveautes.values())


CONTEXTE = "Je travaille avec `/code-review` et `claude purge` dans le dépôt.\n"


def _brut(*puces):
    return {"nouveautes": [{"id": "claude-code-9", "puces": list(puces)}]}


def _element(**champs):
    return {"id": "claude-code-9", "ids_bruts": ["claude-code-9"], "resume": "Rien de neuf.", "pour_toi": None, **champs}


def _avert_puces(brut, element, base=frozenset()):
    r = v.Rapport()
    v.avertir_puces({"elements": [element]}, brut, CONTEXTE, set(base), r, "2026-10-08.json")
    return r.avertissements


def test_r2_ajout_au_nom_connu_et_non_cite_avertit():
    ajout = {"genre": "ajout", "texte": "Added `/code-review` option", "noms": ["/code-review"]}
    avert = _avert_puces(_brut(ajout), _element())
    assert len(avert) == 1 and "R2" in avert[0] and "`/code-review`" in avert[0] and "claude-code-9" in avert[0]
    assert _avert_puces(_brut(ajout), _element(resume="Nouvelle option pour /Code-Review.")) == []
    assert _avert_puces(_brut(ajout), _element(pour_toi="Tu utilises `/code-review`.")) == []


def test_r2_nom_de_la_base_et_nom_inconnu():
    ajout = {"genre": "ajout", "texte": "Added `/add-dir` flag", "noms": ["/add-dir"]}
    assert _avert_puces(_brut(ajout), _element()) == []
    assert len(_avert_puces(_brut(ajout), _element(), base={"/add-dir"})) == 1
    avec_argument = {"genre": "ajout", "texte": "Added `/add-dir <path>`", "noms": ["/add-dir <path>"]}
    assert len(_avert_puces(_brut(avec_argument), _element(), base={"/add-dir"})) == 1


def test_r2_ne_vise_que_les_ajouts_et_les_noms_utiles():
    correctif = {"genre": "correctif", "texte": "Fixed `/code-review`", "noms": ["/code-review"]}
    valeur = {"genre": "ajout", "texte": "Added `x` and `true`", "noms": ["x", "true"]}
    assert _avert_puces(_brut(correctif, valeur), _element()) == []
    sans_puces = {"nouveautes": [{"id": "claude-code-9"}]}
    assert _avert_puces(sans_puces, _element()) == []


def test_r2_de_bout_en_bout_sans_changer_le_code(racine, capsys):
    from conftest import ecrire_quotidien
    jour = __import__("datetime").date.today().isoformat()
    fetch.main(["--racine", str(racine), "--perimetre", "claude"])
    chemin = racine / "raw" / "claude-nouveautes.json"
    brut = json.loads(chemin.read_text())
    cc = [n for n in brut["nouveautes"] if n["source_id"] == "claude-code-changelog" and n.get("puces")]
    nom = next(nom for n in cc for p in n["puces"] if p["genre"] == "ajout" for nom in p["noms"] if len(nom) > 3)
    (racine / "CONTEXTE.md").write_text(f"## 2. Projets\n<!-- ctx-id: projets -->\n\n### 2.1 carnet — PWA\n"
                                        f"<!-- ctx-id: projet.carnet -->\n\nJe me sers de `{nom}`.\n", encoding="utf-8")
    ecrire_quotidien(racine, "claude", brut, jour)
    args = ["--racine", str(racine), "--perimetre", "claude", "--contexte", str(racine / "CONTEXTE.md"), "--date", jour]
    code_sans = v.main(args)
    capsys.readouterr()
    code = v.main(args + ["--brut", str(chemin)])
    sortie = capsys.readouterr()
    assert any("R2" in l and nom in l for l in sortie.out.splitlines() if l.startswith("! AVERTISSEMENT"))
    assert code == code_sans  # le code de sortie ne dépend pas de l'avertissement
