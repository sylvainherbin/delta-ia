"""D96 : réévaluation des éléments des 7 derniers jours dont une section citée de CONTEXTE.md a changé (profil fictif camille)."""

import json
from datetime import date, timedelta

import pytest

import fetch
import valider as v
from conftest import FIXTURES_PROFILS, FauxClient, ecrire_quotidien
from deltalib.contexte import REEVALUER_MAX, a_reevaluer, empreinte_fichier, sections

CAMILLE = (FIXTURES_PROFILS / "camille" / "CONTEXTE.md").read_text(encoding="utf-8")
JOUR = date.today()


@pytest.fixture
def racine(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    (tmp_path / "CONTEXTE.md").write_text(CAMILLE, encoding="utf-8")
    return tmp_path


def elt(ident, cles, impact="moyen", **extra):
    """Élément valide citant les sections `cles` de CAMILLE avec leur empreinte actuelle."""
    cs = {k: {"sha1": sections(CAMILLE)[k]["sha1"], "pourquoi": f"cite {k}"} for k in cles}
    return {"id": ident, "ids_bruts": [ident], "produit": "claude-code", "titre": f"Élément {ident}", "version": None,
            "date_publication": None, "type": "nouveaute", "resume": "Résumé de test.",
            "sources": [{"url": "https://x.test", "libelle": "s", "officielle": False}], "certitude": "rapporte",
            "impact": impact, "pour_toi": None if impact == "nul" else "Constat de test.", "projets_concernes": [],
            "action": None, "kb_refs": [], "contexte_sections": cs, **extra}


def jour_fichier(racine, jour, elements, ecartes=(), perimetre="claude", empreinte=None):
    d = racine / "docs" / "data" / perimetre
    d.mkdir(parents=True, exist_ok=True)
    q = {"date": jour.isoformat(), "perimetre": perimetre, "agent": "claude-code", "genere_le": f"{jour}T12:00:00+00:00",
         "synthese": "Synthèse de test.", "sources_en_echec": [], "elements": elements,
         "ecartes": [{"id": i, "raison": r} for i, r in ecartes], "contexte_empreinte": empreinte or "0" * 40}
    (d / f"{jour}.json").write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")


def modifier_section(racine, cle, ajout="\n- Nouvelle ligne de test.\n"):
    """Change le corps d'une section de CONTEXTE.md (ajout à la fin de son corps) et retourne le nouveau texte."""
    texte = (racine / "CONTEXTE.md").read_text(encoding="utf-8")
    lignes = texte.splitlines(keepends=True)
    i = next(n for n, l in enumerate(lignes) if f"ctx-id: {cle} " in l or l.strip() == f"<!-- ctx-id: {cle} -->")
    lignes.insert(i + 1, ajout)
    (racine / "CONTEXTE.md").write_text("".join(lignes), encoding="utf-8")


def ids(res):
    return [x["id"] for x in res["reevaluer"]]


def test_section_inchangee_rien_a_reevaluer(racine):
    jour_fichier(racine, JOUR - timedelta(days=1), [elt("a", ["config.codex"])])
    assert a_reevaluer(racine, "claude", JOUR) == {"reevaluer": [], "reevaluer_total": 0}


def test_section_modifiee_est_reperee_avec_sa_cle(racine):
    jour_fichier(racine, JOUR - timedelta(days=2), [elt("a", ["config.codex", "profil"], impact="fort"), elt("b", ["env.machine"])])
    modifier_section(racine, "config.codex", "- Codex passe en Business **[déclaré]**.\n")
    res = a_reevaluer(racine, "claude", JOUR)
    assert res["reevaluer"] == [{"id": "a", "date": (JOUR - timedelta(days=2)).isoformat(), "impact": "fort",
                                 "sections_modifiees": ["config.codex"]}]
    assert res["reevaluer_total"] == 1


def test_section_disparue_ou_depreciee_compte_comme_modifiee(racine):
    jour_fichier(racine, JOUR - timedelta(days=1), [elt("a", ["projet.site-vitrine"]), elt("b", ["config.claude-code"])])
    texte = (racine / "CONTEXTE.md").read_text(encoding="utf-8")
    texte = texte.replace("<!-- ctx-id: projet.site-vitrine -->", "<!-- ctx-id: projet.vitrine2 -->\n<!-- ctx-id-deprecie: projet.site-vitrine -->")
    (racine / "CONTEXTE.md").write_text(texte, encoding="utf-8")
    assert ids(a_reevaluer(racine, "claude", JOUR)) == ["a"]


def test_fenetre_de_7_jours_et_contexte_sections_absent_ou_vide(racine):
    jour_fichier(racine, JOUR - timedelta(days=8), [elt("vieux", ["profil"])])
    jour_fichier(racine, JOUR - timedelta(days=7), [elt("limite", ["profil"]), elt("sans", []),
                                                    {**elt("avant-d64", ["profil"]), "contexte_sections": None}])
    modifier_section(racine, "profil")
    assert ids(a_reevaluer(racine, "claude", JOUR)) == ["limite"]


def test_une_revision_remplace_l_element_et_n_est_plus_reperee(racine):
    jour_fichier(racine, JOUR - timedelta(days=3), [elt("a", ["env.machine"])])
    modifier_section(racine, "env.machine")
    assert ids(a_reevaluer(racine, "claude", JOUR)) == ["a"]
    revision = {**elt("a", ["env.machine"]), "revision": True}  # empreinte courante après la modification
    revision["contexte_sections"]["env.machine"]["sha1"] = sections((racine / "CONTEXTE.md").read_text(encoding="utf-8"))["env.machine"]["sha1"]
    jour_fichier(racine, JOUR - timedelta(days=1), [revision])
    assert ids(a_reevaluer(racine, "claude", JOUR)) == []
    modifier_section(racine, "env.machine", "- Autre changement.\n")  # la section change encore : de nouveau repérée, avec la date de la révision
    res = a_reevaluer(racine, "claude", JOUR)
    assert ids(res) == ["a"] and res["reevaluer"][0]["date"] == (JOUR - timedelta(days=1)).isoformat()


def test_reevalue_inchange_ecarte_jusqu_au_prochain_changement_de_contexte(racine):
    jour_fichier(racine, JOUR - timedelta(days=3), [elt("a", ["env.machine"])])
    modifier_section(racine, "env.machine")
    jour_fichier(racine, JOUR - timedelta(days=1), [], ecartes=[("a", "réévalué, inchangé : MacBook toujours sous macOS")],
                 empreinte=empreinte_fichier(racine))
    assert ids(a_reevaluer(racine, "claude", JOUR)) == []
    modifier_section(racine, "profil", "- Autre changement du profil.\n")  # CONTEXTE.md a une autre empreinte : on regarde de nouveau
    assert ids(a_reevaluer(racine, "claude", JOUR)) == ["a"]


def test_plafond_les_plus_forts_d_abord_puis_les_plus_recents(racine):
    forts = [elt(f"f{n:02d}", ["profil"], impact="fort") for n in range(4)]
    autres = [elt(f"m{n:02d}", ["profil"], impact="moyen") for n in range(8)]
    jour_fichier(racine, JOUR - timedelta(days=5), forts[:2] + autres[:4])
    jour_fichier(racine, JOUR - timedelta(days=2), forts[2:] + autres[4:] + [elt("nul", ["profil"], impact="nul")])
    modifier_section(racine, "profil")
    res = a_reevaluer(racine, "claude", JOUR)
    assert res["reevaluer_total"] == 13 and len(res["reevaluer"]) == REEVALUER_MAX == 10
    assert ids(res)[:4] == ["f02", "f03", "f00", "f01"]  # forts : le plus récent d'abord, puis par id
    assert ids(res)[4:] == ["m04", "m05", "m06", "m07", "m00", "m01"]
    assert "nul" not in ids(res)


def test_contexte_introuvable_leve_une_erreur_explicite(racine):
    (racine / "CONTEXTE.md").unlink()
    with pytest.raises(ValueError, match="CONTEXTE.md introuvable"):
        a_reevaluer(racine, "claude", JOUR)


# --- fetch.py : le brut porte `reevaluer` ; --valider et valider.py acceptent les révisions -------------------------

def brut_courant(racine, perimetre="claude"):
    fetch.main(["--racine", str(racine), "--perimetre", perimetre])
    return json.loads((racine / "raw" / f"{perimetre}-nouveautes.json").read_text(encoding="utf-8"))


def test_fetch_ecrit_reevaluer_dans_le_brut(racine, capsys):
    jour_fichier(racine, JOUR - timedelta(days=1), [elt("a", ["config.claude-code"], impact="fort")])
    modifier_section(racine, "config.claude-code")
    brut = brut_courant(racine)
    assert brut["reevaluer"] == [{"id": "a", "date": (JOUR - timedelta(days=1)).isoformat(), "impact": "fort",
                                  "sections_modifiees": ["config.claude-code"]}]
    assert brut["reevaluer_total"] == 1 and "reevaluer_erreur" not in brut
    assert "à réévaluer" in capsys.readouterr().out


def test_fetch_signale_un_contexte_invalide_sans_liste_vide_muette(racine, capsys):
    (racine / "CONTEXTE.md").write_text("# Titre sans ctx-id\n", encoding="utf-8")
    brut = brut_courant(racine)
    assert brut["reevaluer"] == [] and "ctx-id" in brut["reevaluer_erreur"]
    assert "RÉÉVALUATION impossible" in capsys.readouterr().out


def test_valider_et_valider_py_acceptent_la_revision_et_l_ecarte(racine, capsys):
    jour_fichier(racine, JOUR - timedelta(days=2), [elt("a", ["env.machine"]), elt("b", ["config.codex"]), elt("c", ["profil"])])
    for cle in ("env.machine", "config.codex", "profil"):
        modifier_section(racine, cle)
    brut = brut_courant(racine)
    assert sorted(ids(brut)) == ["a", "b", "c"]
    # a : révision du même id ; b : écarté « réévalué, inchangé » ; c : laissé de côté
    tout = [n["id"] for n in brut["nouveautes"]]
    ecrire_quotidien(racine, "claude", brut, JOUR.isoformat(), ecarter=[*tout, "b"], extra_elements=[{**elt("a", []), "revision": True}])
    assert fetch.main(["--racine", str(racine), "--perimetre", "claude", "--valider"]) == 0  # ni « inconnu » ni « en attente »
    sortie = capsys.readouterr().out
    assert "2 réévaluation(s) reprise(s)" in sortie and "non repris" in sortie and " c" in sortie
    etat = json.loads((racine / "state" / "claude.json").read_text())
    assert "a" not in etat["vus"] and "b" not in etat["vus"]  # reprise d'un élément déjà publié : rien n'est inscrit
    args = ["--racine", str(racine), "--perimetre", "claude", "--contexte", str(racine / "CONTEXTE.md"), "--date", JOUR.isoformat(),
            "--brut", str(racine / "raw" / "claude-nouveautes.json")]
    assert v.main(args) == 0  # un avertissement, jamais une erreur
    avert = capsys.readouterr().out
    assert "D96" in avert and "c" in avert and avert.count("D96") == 1


def test_valider_py_sans_avertissement_quand_tout_est_repris(racine, capsys):
    jour_fichier(racine, JOUR - timedelta(days=2), [elt("a", ["env.machine"])])
    modifier_section(racine, "env.machine")
    brut = brut_courant(racine)
    ecrire_quotidien(racine, "claude", brut, JOUR.isoformat(), ecarter=[n["id"] for n in brut["nouveautes"]],
                     extra_elements=[{**elt("a", []), "revision": True}])
    args = ["--racine", str(racine), "--perimetre", "claude", "--contexte", str(racine / "CONTEXTE.md"), "--date", JOUR.isoformat(),
            "--brut", str(racine / "raw" / "claude-nouveautes.json")]
    assert v.main(args) == 0
    assert "D96" not in capsys.readouterr().out


def test_les_trois_textes_decrivent_la_reevaluation_d95():
    from pathlib import Path
    racine = Path(fetch.RACINE)
    for f in (".claude/skills/delta/SKILL.md", ".agents/skills/delta/SKILL.md", "prompts/codex-delta.md"):
        texte = (racine / f).read_text(encoding="utf-8")
        assert "**Réévaluation en tête (D96).**" in texte and "réévalué, inchangé" in texte and "`reevaluer`" in texte, f
