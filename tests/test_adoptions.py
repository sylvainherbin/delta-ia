"""m-a04181983623 : boucle d'adoption, projection par fiche des vues d'OPÉRER (scripts/deltalib/adoptions.py)."""

import json
import re
from pathlib import Path

import pytest

from deltalib import adoptions as a


def idee(fiche, nom="/add-dir", **champs):
    return {"verbatim": f"idée : intégrer la référence Delta-IA « {nom} » (Claude Code, commande, id {fiche}) dans un workflow "
                        "ou chez un agent de Delta. Juge sa pertinence pour mes projets.", "missions": [], **champs}


def test_fiche_de_idee():
    assert a.fiche_de_idee(idee("claude-code-commandes-goal", nom="/goal (mode « but »)")["verbatim"]) == "claude-code-commandes-goal"
    assert a.fiche_de_idee("j'ai une idée, ajouter un raccourci vers mes rapports") is None
    assert a.fiche_de_idee(None) is None


@pytest.mark.parametrize("sujet,attendu", [
    ({"position": "PERTINENTE"}, "retenu"), ({"position": "VERITE (PENCHE_POUR)"}, "retenu"),
    ({"position": "PAS_PERTINENTE", "sans_suite": True}, "ecarte"), ({"position": "VERITE (PENCHE_CONTRE)"}, "ecarte"),
    ({"position": "A_PRECISER"}, "propose"), ({"position": "VERITE"}, "propose"), ({"position": "?", "sans_suite": True}, "ecarte"),
    ({}, "propose"),
])
def test_etat_d_une_idee_sans_mission(sujet, attendu):
    f = a.projeter([idee("f", **sujet)], {})["f"]
    assert f["etat"] == attendu and f["missions"] == [] and f["installations"] == []


@pytest.mark.parametrize("mission,attendu,le", [
    ({"etat": "BRIEF"}, "retenu", None),
    ({"etat": "EN_COURS"}, "en_realisation", None), ({"etat": "A_RELIRE"}, "en_realisation", None),
    ({"etat": "POUSSEE"}, "en_realisation", None), ({"etat": "ECHEC"}, "en_realisation", None),
    ({"etat": "CLOSE", "issue": "livre", "preuves": {"verifie_ts": "2026-10-11T18:04:37+02:00", "sans_installation": False,
                                                     "fichiers": [{"source": "a", "destination": "b", "sha256": "c"}]}}, "installe", "2026-10-11"),
    # relecture fe21147f : livrée et fusionnée sans rien installer (preuves.py : sans_installation, fichiers []) → adoptée, pas installée
    ({"etat": "CLOSE", "issue": "livre", "preuves": {"verifie_ts": "2026-10-11T01:48:54+02:00", "sans_installation": True, "fichiers": []}},
     "adopte", "2026-10-11"),
    ({"etat": "CLOSE", "issue": "livre", "preuves": {"verifie_ts": "2026-10-11T01:48:54+02:00", "fichiers": []}}, "adopte", "2026-10-11"),
    ({"etat": "CLOSE", "issue": "livre", "preuves": None}, "retenu", None),    # conception livrée, rien d'installé
    ({"etat": "CLOSE", "issue": "remplace", "preuves": {"verifie_ts": "2026-10-11T00:00:00+02:00"}}, "retenu", None),
])
def test_etat_projete_d_une_mission(mission, attendu, le):
    f = a.projeter([idee("f", position="A_PRECISER", missions=[{"id": "m-1", "etat": mission["etat"]}])], {"m-1": mission})["f"]
    assert f["etat"] == attendu and f["missions"] == [{"id": "m-1", "etat": mission["etat"], "projete": attendu}]
    assert [i["le"] for i in f["installations"]] == ([le] if le else [])
    assert [i["par"] for i in f["installations"]] == ({"installe": ["mission"], "adopte": ["mission_sans_installation"]}.get(attendu, []))


def test_plusieurs_idees_et_missions_le_plus_haut_l_emporte():
    sujets = [idee("f", position="PAS_PERTINENTE", sans_suite=True, premier="2026-10-14T12:00:00+00:00"),
              idee("f", position="PERTINENTE", premier="2026-10-09T09:00:00+00:00",
                   missions=[{"id": "m-1", "etat": "CLOSE", "resultat": "installé"}, {"id": "m-2", "etat": "EN_COURS"}])]
    missions = {"m-1": {"etat": "CLOSE", "issue": "livre", "resultat": "Sous-agents installés",
                        "preuves": {"verifie_ts": "2026-10-11T01:00:00+02:00", "sans_installation": False, "fichiers": [{"source": "a"}]}},
                "m-2": {"etat": "EN_COURS"}}
    f = a.projeter(sujets, missions)["f"]
    assert f["etat"] == "installe" and f["propose_le"] == "2026-10-09"
    assert f["installations"] == [{"lot": "m-1", "le": "2026-10-11", "par": "mission", "resultat": "Sous-agents installés"}]
    assert [m["projete"] for m in f["missions"]] == ["installe", "en_realisation"]


def test_mission_illisible_garde_l_etat_du_resume_d_idee():
    f = a.projeter([idee("f", missions=[{"id": "m-9", "etat": "EN_COURS"}])], {})["f"]
    assert f["etat"] == "en_realisation" and f["missions_illisibles"] == []


@pytest.mark.parametrize("resume", [{"id": "m-9", "etat": "CLOSE"}, {"id": "m-9"}])
def test_mission_close_illisible_etat_inconnu_jamais_retenu(resume):
    """Relecture 9d0ce971 (4) : vue mission en échec et mission close au résumé → « inconnu », pas « retenu » en silence."""
    f = a.projeter([idee("f", position="PERTINENTE", missions=[resume])], {})["f"]
    assert f["etat"] == "inconnu" and f["missions_illisibles"] == ["m-9"] and f["installations"] == []
    # une autre mission lisible et installée : « installée » reste certaine (rien n'est plus haut)
    installee = {"etat": "CLOSE", "issue": "livre", "preuves": {"verifie_ts": "2026-10-11T01:00:00+02:00", "fichiers": [{"source": "a"}]}}
    f = a.projeter([idee("f", missions=[resume, {"id": "m-1", "etat": "CLOSE"}])], {"m-1": installee})["f"]
    assert f["etat"] == "installe" and f["missions_illisibles"] == ["m-9"]
    # une mission seulement en réalisation ne tranche pas : l'état reste inconnu
    f = a.projeter([idee("f", missions=[resume, {"id": "m-2", "etat": "EN_COURS"}])], {"m-2": {"etat": "EN_COURS"}})["f"]
    assert f["etat"] == "inconnu"


def test_resultat_observe_de_delta_lab_distinct_de_l_installation():
    essais = [{"id": "ess_0123456789ab", "statut": "en_essai", "maturite": "prometteur", "fige_le": "2026-10-20T10:00:00+02:00",
               "protocole": {"fiche": "f", "titre": "Plafond de contexte"}, "clos": None},
              {"id": "ess_ba9876543210", "statut": "adopte", "maturite": "confirme", "protocole": {"fiche": "g", "titre": "Effort"},
               "adoption": {"ts": "2026-10-22T08:00:00+02:00"}, "clos": {"ts": "2026-10-22T08:00:00+02:00", "explication": "gain 12 %"}}]
    fiches = a.projeter([idee("f", position="PERTINENTE")], {}, essais)
    assert fiches["f"]["etat"] == "retenu" and fiches["f"]["installations"] == []
    assert fiches["f"]["resultat_observe"] == [{"essai": "ess_0123456789ab", "statut": "en_essai", "maturite": "prometteur",
                                                "titre": "Plafond de contexte", "le": "2026-10-20", "explication": None}]
    # relecture 9d0ce971 (5) : essai sur une fiche jamais envoyée ni jugée → aucune entrée (comme au tri)
    assert "g" not in fiches
    # la même fiche envoyée : l'essai adopté est une amélioration appliquée, lot = essai
    g = a.projeter([], {}, essais, envois=[{"id": "g", "ok": True, "date": "2026-10-20T10:00:00+0200"}])["g"]
    assert g["etat"] == "installe"
    assert g["installations"] == [{"lot": "ess_ba9876543210", "le": "2026-10-22", "par": "essai", "resultat": "Effort"}]


def test_id_delta_lab_prefixe_kb_rejoint_sa_fiche():
    """Relecture 9d0ce971 (3) : OPÉRER écrit parfois « kb-<id de fiche> » (tri réel du 24/10/2026)."""
    tries = [("2026-10-24", "kb-codex-parametres-x", "raison"), ("2026-10-24", "kb-inconnue", "raison")]
    essais = [{"id": "ess_0123456789ab", "statut": "en_essai", "protocole": {"fiche": "kb-codex-parametres-x"}}]
    fiches = a.projeter([idee("codex-parametres-x")], {}, essais, tries)
    assert set(fiches) == {"codex-parametres-x"}
    assert [o["statut"] for o in fiches["codex-parametres-x"]["resultat_observe"]] == ["en_essai", "ecarte_au_tri"]
    # une fiche dont l'id commence vraiment par « kb- » garde la forme exacte
    assert a.projeter([idee("kb-x")], {}, tries=[("2026-10-24", "kb-x", "r")])["kb-x"]["resultat_observe"][0]["le"] == "2026-10-24"


def test_lire_essais_et_tri():
    liste = {"essais": ["ess_0123456789ab · en_essai · prometteur · operer.cle 1 → 2 · Titre",
                        "Examinés, écartés au tri (avant protocole) :",
                        "2026-10-24T15:43:58.592065+02:00 · f : m-3fa5c022b258 — W43 rang 1 : aucune clé de politique.",
                        "2026-10-24T15:45:00+02:00 · politique-locale [operer.reglage.x] : m-3 — candidat local",
                        "ligne illisible"]}
    ids, tries = a.lire_essais(liste)
    assert ids == ["ess_0123456789ab"]
    assert tries == [("2026-10-24", "f", "m-3fa5c022b258 — W43 rang 1 : aucune clé de politique."),
                     ("2026-10-24", "politique-locale", "m-3 — candidat local")]
    fiches = a.projeter([idee("f")], {}, tries=tries)
    assert fiches["f"]["resultat_observe"][0]["statut"] == "ecarte_au_tri" and "politique-locale" not in fiches


def test_suivi_lit_les_vues_et_nomme_les_echecs():
    vus = []

    def lire(*args):
        vus.append(args)
        if args == ("idees",):
            return {"sujets": [idee("f", missions=[{"id": "m-1"}]), {"verbatim": "autre idée", "missions": [{"id": "m-x"}]}]}
        if args == ("mission", "m-1"):
            raise a.LectureImpossible("mission m-1 : code de sortie 2")
        if args == ("essai", "liste"):
            return {"essais": ["ess_0123456789ab · en_essai · · c 1 → 2 · T"]}
        return {"essai": {"id": "ess_0123456789ab", "statut": "en_essai", "protocole": {"fiche": "f"}}}
    r = a.suivi([{"id": "f", "ok": True, "date": "2026-10-08T10:00:00+0200"}], lire=lire)
    assert ("mission", "m-x") not in vus     # mission d'une idée qui ne vient pas du bouton : jamais lue
    assert r["sources_en_echec"] == ["mission m-1 : mission m-1 : code de sortie 2"]
    f = r["fiches"]["f"]
    # vue de m-1 en échec, résumé sans état : la fiche est « inconnu », échec nommé (relecture 9d0ce971 (4))
    assert f["propose_le"] == "2026-10-08" and f["etat"] == "inconnu" and f["missions_illisibles"] == ["m-1"]
    assert f["resultat_observe"][0]["essai"] == "ess_0123456789ab"


def test_lire_operer_sans_executable(monkeypatch):
    monkeypatch.setenv("PATH", "/inexistant")
    with pytest.raises(a.LectureImpossible, match="exécutable operer absent"):
        a.lire_operer("idees")


def test_rien_de_la_projection_n_est_publie():
    """La projection reste locale : aucun fichier de docs/ ni de SPEC §3 ne la reçoit, seul le relais l'importe."""
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent
    importeurs = [p.name for p in (racine / "scripts").rglob("*.py") if re.search(r"from deltalib import adoptions|deltalib\.adoptions", p.read_text(encoding="utf-8"))]
    assert importeurs == ["relais_reference.py"]
    assert "ecrire_json" not in (racine / "scripts" / "deltalib" / "adoptions.py").read_text(encoding="utf-8")
    json.dumps(a.projeter([], {}))


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "operer"


def test_lire_essais_sur_la_forme_d_operer():
    """Lignes rendues par la vraie fonction delta.operer.essais.liste() sur un état synthétique (relecture 9d0ce971 (1) :
    aucune sortie réelle d'OPÉRER dans le dépôt public) : essais ouverts, puis tri, ids préfixés « kb- » et non-fiches."""
    ids, tries = a.lire_essais(json.loads((FIXTURES / "essai_liste_synthetique.json").read_text(encoding="utf-8")))
    assert ids == ["ess_0123456789ab", "ess_ba9876543210"]
    assert [f for _, f, _ in tries] == ["kb-produit-categorie-fiche-prefixee", "outil-v1.2.3", "produit-categorie-fiche-simple",
                                        "candidat-local-exemple"]
    assert {j for j, _, _ in tries} == {"2026-10-24"} and tries[3][2] == "m-000000000000 — candidat local de test."
    fiches = a.projeter([idee("produit-categorie-fiche-prefixee"), idee("produit-categorie-fiche-simple")], {}, tries=tries)
    assert set(fiches) == {"produit-categorie-fiche-prefixee", "produit-categorie-fiche-simple"}
    assert all(f["resultat_observe"][0]["statut"] == "ecarte_au_tri" for f in fiches.values())


def test_aucune_sortie_reelle_d_operer_dans_les_fixtures():
    """Dépôt public : les fixtures d'OPÉRER ne portent ni id de mission réel ni clé de la politique d'instance."""
    for p in FIXTURES.glob("*.json"):
        texte = p.read_text(encoding="utf-8")
        assert not re.search(r"m-(?!0{12})[0-9a-f]{12}", texte) and "reglage_missions" not in texte, p.name


# ───────────────────────────── ajustements proposés (lot 4, m-3bfd4d23988f) ─────────────────────────────

AJ = "reglage-claude-code-effort-high-vers-medium"


def ajustement(ident=AJ, **champs):
    return {"id": ident, "statut": "propose", "actuel": True, "propose_le": "2026-10-26", "famille": "claude", "nature": "code",
            "sens": "economie", "reglage": {"cle": "operer.reglage_missions.claude.table.code.*.effort", "temoin": "high", "essai": "medium"},
            "motif": "m", "observations": {}, "limites": ["Aucun gain n'est attribué au réglage"],
            "qualification": {"par": "Delta Lab", "etat": "a_qualifier"}, **champs}


def essai_sur(ident, statut, **champs):
    return {"id": "ess_0123456789ab", "statut": statut, "maturite": None, "protocole": {"fiche": ident, "titre": "T"}, **champs}


def test_ajustement_entre_propose_dans_la_boucle():
    f = a.projeter([], {}, ajustements=[ajustement(), {"id": "x", "statut": "autre"}, "illisible"])
    assert set(f) == {AJ}
    assert f[AJ]["etat"] == "propose" and f[AJ]["propose_le"] == "2026-10-26" and f[AJ]["installations"] == []
    assert f[AJ]["ajustement"]["reglage"]["essai"] == "medium" and f[AJ]["ajustement"]["limites"]
    assert "id" not in f[AJ]["ajustement"] and "statut" not in f[AJ]["ajustement"]


@pytest.mark.parametrize("statut,etat", [("en_essai", "en_realisation"), ("propose", "en_realisation"),
                                         ("ecarte", "ecarte"), ("regressif", "ecarte"), ("remplace", "propose")])
def test_ajustement_suit_la_qualification_delta_lab(statut, etat):
    f = a.projeter([], {}, [essai_sur(AJ, statut)], ajustements=[ajustement()])[AJ]
    assert f["etat"] == etat and f["resultat_observe"][0]["statut"] == statut and f["installations"] == []


def test_ajustement_adopte_par_delta_lab_installe():
    x = essai_sur(AJ, "adopte", adoption={"ts": "2026-11-09T08:00:00+01:00"}, clos={"ts": "2026-11-09T08:00:00+01:00"})
    f = a.projeter([], {}, [x], ajustements=[ajustement()])[AJ]
    assert f["etat"] == "installe" and f["installations"] == [{"lot": "ess_0123456789ab", "le": "2026-11-09", "par": "essai", "resultat": "T"}]


def test_essai_sans_ajustement_reste_hors_boucle():
    assert a.projeter([], {}, [essai_sur(AJ, "en_essai")]) == {}


def test_suivi_lit_le_fichier_des_ajustements(tmp_path):
    def lire(*args):
        return {"sujets": []} if args == ("idees",) else {"essais": []}
    chemin = tmp_path / "ajustements-reglages.json"
    chemin.write_text(json.dumps({"version": 1, "vue": "ajustements_reglages", "ajustements": [ajustement()]}), encoding="utf-8")
    r = a.suivi([], lire=lire, ajustements=chemin)
    assert r["sources_en_echec"] == [] and r["fiches"][AJ]["etat"] == "propose"
    assert a.suivi([], lire=lire, ajustements=tmp_path / "absent.json") == {"fiches": {}, "sources_en_echec": []}
    chemin.write_text("{", encoding="utf-8")
    assert a.suivi([], lire=lire, ajustements=chemin)["sources_en_echec"] == ["ajustements : fichier illisible"]
    chemin.write_text(json.dumps({"vue": "autre"}), encoding="utf-8")
    assert a.suivi([], lire=lire, ajustements=chemin)["sources_en_echec"] == ["ajustements : fichier hors contrat"]
