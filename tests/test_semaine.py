"""D98 : bilan de la semaine (scripts/semaine.py, deltalib/semaine.py), son contrôle par valider.py, l'onglet du site et le branchement."""

import json
import shutil
from pathlib import Path

import pytest

import semaine as cli
import valider
from conftest import FIXTURES, RACINE
from deltalib import semaine as sem

PLEINE = FIXTURES / "semaine" / "pleine"
VIDE = FIXTURES / "semaine" / "vide"
MAINTENANT = "2026-10-08T12:00:00+00:00"


def copie(modele: Path, tmp_path: Path) -> Path:
    racine = tmp_path / "depot"
    shutil.copytree(modele, racine)
    return racine


def ids(lignes):
    return [l["id"] for l in lignes]


def test_bornes_et_semaine_iso():
    from datetime import date
    assert sem.bornes("2026-W41") == (date(2026, 10, 5), date(2026, 10, 11))
    assert sem.semaine_de(date(2026, 10, 11)) == "2026-W41" and sem.semaine_de(date(2026, 10, 12)) == "2026-W42"
    assert sem.semaine_de(date(2026, 1, 1)) == "2026-W01" and sem.semaine_de(date(2027, 1, 1)) == "2026-W53"
    for faux in ("2026-41", "2026-W99", "", "26-W41", "2026-W4"):
        with pytest.raises(sem.SemaineInvalide):
            sem.bornes(faux)


def test_semaine_pleine():
    d = sem.construire(PLEINE, "2026-W41", MAINTENANT)
    assert d["statut"] == "ok" and d["raison"] is None and d["du"] == "2026-10-05" and d["au"] == "2026-10-11"
    assert d["sources"]["claude"]["jours"] == ["2026-10-06", "2026-10-07"]  # 04/10 et 12/10 hors semaine
    assert d["sources"]["openai"]["jours"] == ["2026-10-07"] and d["sources"]["actu"]["jours"] == ["2026-10-07"]
    # (b) D71 en tête : repéré aux mots-clés (crédits, quotas), tous périmètres
    assert ids(d["d71"]) == ["gpt-quota", "credits-max"]  # impact fort égal : jour le plus récent d'abord
    # (a) fort et moyen hors D71 ; un id repris garde le jour le plus récent ; faible, nul et hors semaine absents
    assert ids(d["elements"]) == ["cc-2-1-292", "actu-1"]  # fort avant moyen
    revise = d["elements"][0]
    assert revise["jour"] == "2026-10-07" and revise["impact"] == "fort" and revise["titre"] == "Claude Code 2.1.292 (révisé)"
    assert revise["action"] == "Ajouter l'effort dans les briefs, commande `claude -p`." and revise["version"] == "2.1.292"
    assert d["elements"][1]["action"] is None and d["elements"][1]["perimetre"] == "actu"
    assert set(revise) == {"perimetre", "id", "produit", "titre", "version", "impact", "certitude", "date_publication", "jour", "action"}


def test_base_ajoutee_et_verdicts():
    d = sem.construire(PLEINE, "2026-W41", MAINTENANT)
    # (c) date d'ajout comme D89 (ligne « ajoutée », à défaut la plus ancienne date), verdict utiliser, tester, ignorer, sans verdict
    assert ids(d["base_ajoutees"]) == ["oa-a", "cc-a", "cc-e", "cc-g", "cc-h"]
    a = {l["id"]: l for l in d["base_ajoutees"]}
    assert a["cc-a"]["exemple"] == "/nouvelle ~/projets/delta-ia" and a["cc-a"]["exemple_origine"] == "compose"
    assert a["cc-a"]["usage"] == "/nouvelle <chemin>" and a["cc-g"]["verdict"] is None and a["cc-g"]["date_ajout"] == "2026-10-09"
    assert "cc-f" not in a  # ajoutée la semaine d'avant
    # (d) verdict changé vers utiliser ou tester (dernière ligne de la semaine) et premier jugement d'une entrée plus ancienne
    assert ids(d["base_verdicts"]) == ["cc-b", "cc-c"]
    v = {l["id"]: l for l in d["base_verdicts"]}
    assert (v["cc-b"]["verdict_avant"], v["cc-b"]["verdict_apres"], v["cc-b"]["date"]) == ("tester", "utiliser", "2026-10-07")
    assert (v["cc-c"]["verdict_avant"], v["cc-c"]["verdict_apres"], v["cc-c"]["date"]) == (None, "tester", "2026-10-08")
    assert v["cc-b"]["pourquoi"] == "Promue cette semaine."
    assert not {"cc-a", "cc-d", "cc-f"} & set(v)  # déjà dans (c), passée à ignorer, hors semaine


def test_semaine_vide_ecrite_en_ok():
    d = sem.construire(VIDE, "2026-W41", MAINTENANT)
    assert d["statut"] == "ok" and d["raison"] is None
    assert d["d71"] == d["elements"] == d["base_ajoutees"] == d["base_verdicts"] == []
    assert all(s["statut"] == "ok" and s["raison"] is None for s in d["sources"].values())
    # aucun dossier du tout : toujours un bilan vide valide, jamais une exception
    d = sem.construire(Path("/nonexistent-delta-semaine"), "2026-W41", MAINTENANT)
    assert d["statut"] == "ok" and d["elements"] == []


def test_source_illisible_donne_echec_et_raison(tmp_path, capsys):
    racine = copie(PLEINE, tmp_path)
    (racine / "docs/data/claude/2026-10-07.json").write_text("{pas du json", encoding="utf-8")
    (racine / "docs/data/kb/claude/reevaluations.jsonl").write_text("{illisible\n", encoding="utf-8")
    (racine / "docs/data/openai/2026-10-07.json").write_text('{"elements": "non"}', encoding="utf-8")
    assert cli.main(["--semaine", "2026-W41", "--racine", str(racine)]) == 0  # fichier écrit, passage non interrompu
    sortie = capsys.readouterr().out
    assert "! AVERTISSEMENT" in sortie and "statut echec" in sortie
    d = json.loads((racine / "docs/data/semaine/2026-W41.json").read_text(encoding="utf-8"))
    assert d["statut"] == "echec"
    for attendu in ("claude/2026-10-07.json illisible", "openai/2026-10-07.json illisible", "reevaluations.jsonl ligne 1 illisible"):
        assert attendu in d["raison"], attendu
    assert d["sources"]["claude"]["statut"] == "echec" and d["sources"]["claude"]["jours"] == ["2026-10-06"]
    assert d["sources"]["actu"]["statut"] == "ok" and d["sources"]["kb-claude"]["statut"] == "echec"
    assert ids(d["elements"]) == ["actu-1", "cc-2-1-292"]  # le 06/10 de Claude et l'actu restent lus (tous deux moyen)
    r = valider.Rapport()
    valider.verifier_semaine(racine, r)
    assert r.ok, r.erreurs


def test_ecriture_index_et_idempotence(tmp_path):
    racine = copie(PLEINE, tmp_path)
    d = sem.construire(racine, "2026-W41", MAINTENANT)
    assert sem.ecrire(racine, d) is True
    chemin = racine / "docs/data/semaine/2026-W41.json"
    ecrit = chemin.read_text(encoding="utf-8")
    assert json.loads(ecrit) == d
    # un second passage au contenu identique n'écrit rien, même avec un autre horodatage
    assert sem.ecrire(racine, sem.construire(racine, "2026-W41", "2026-10-09T01:00:00+00:00")) is False
    assert chemin.read_text(encoding="utf-8") == ecrit
    # une donnée nouvelle réécrit
    (racine / "docs/data/claude/2026-10-08.json").write_text(
        (racine / "docs/data/claude/2026-10-06.json").read_text(encoding="utf-8").replace("credits-max", "autre-d71"), encoding="utf-8")
    assert sem.ecrire(racine, sem.construire(racine, "2026-W41", "2026-10-09T01:00:00+00:00")) is True
    sem.ecrire(racine, sem.construire(VIDE, "2026-W40", MAINTENANT))
    index = json.loads((racine / "docs/data/semaine/index.json").read_text(encoding="utf-8"))
    assert [s["semaine"] for s in index["semaines"]] == ["2026-W41", "2026-W40"]
    s41 = index["semaines"][0]
    assert (s41["d71"], s41["elements"], s41["base_ajoutees"], s41["base_verdicts"]) == (3, 2, 5, 2)
    assert not list((racine / "docs/data/semaine").glob("*.tmp"))


def test_cli_dry_run_et_arguments(tmp_path, capsys):
    racine = copie(PLEINE, tmp_path)
    assert cli.main(["--semaine", "2026-W41", "--dry-run", "--racine", str(racine)]) == 0
    assert json.loads(capsys.readouterr().out)["semaine"] == "2026-W41"
    assert not (racine / "docs/data/semaine").exists()
    assert cli.main(["--semaine", "2026-W99", "--racine", str(racine)]) == 2
    assert cli.main(["--racine", str(copie(VIDE, tmp_path / "v"))]) == 0  # semaine en cours, vide : fichier écrit


def valider_semaine(racine):
    r = valider.Rapport()
    valider.verifier_semaine(racine, r)
    return r


def test_valider_accepte_le_fichier_et_refuse_les_ecarts(tmp_path):
    racine = copie(PLEINE, tmp_path)
    assert valider_semaine(racine).ok  # dossier absent : rien à contrôler
    sem.ecrire(racine, sem.construire(racine, "2026-W41", MAINTENANT))
    assert valider_semaine(racine).ok
    chemin = racine / "docs/data/semaine/2026-W41.json"
    d = json.loads(chemin.read_text(encoding="utf-8"))

    def avec(modif):
        copie_d = json.loads(json.dumps(d))
        modif(copie_d)
        chemin.write_text(json.dumps(copie_d, ensure_ascii=False), encoding="utf-8")
        return " | ".join(valider_semaine(racine).erreurs)

    assert "`statut` doit valoir ok ou echec" in avec(lambda x: x.update(statut="bidule"))
    assert "`raison` est null si et seulement si" in avec(lambda x: x.update(raison="pourquoi pas"))
    assert "correspondre au nom du fichier" in avec(lambda x: x.update(du="2026-10-06"))
    assert "champs attendus" in avec(lambda x: x.pop("d71"))
    assert "`sources` doit nommer exactement" in avec(lambda x: x["sources"].pop("actu"))
    assert "`date_ajout` hors de la semaine" in avec(lambda x: x["base_ajoutees"][0].update(date_ajout="2026-10-12"))
    assert "`verdict_apres` doit valoir utiliser ou tester" in avec(lambda x: x["base_verdicts"][0].update(verdict_apres="ignorer"))
    assert "`elements` ne reprend que" in avec(lambda x: x["elements"][0].update(impact="faible"))
    assert "`impact` ou `jour` invalide" in avec(lambda x: x["d71"][0].update(jour="hier"))
    assert "secret possible" in avec(lambda x: x["d71"][0].update(action="clé sk-abcdefghijklmnopqrstuvwxyz0123"))
    chemin.write_text("{illisible", encoding="utf-8")
    assert "JSON invalide" in " ".join(valider_semaine(racine).erreurs)
    chemin.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    index = racine / "docs/data/semaine/index.json"
    index.write_text(json.dumps({"maj_le": None, "semaines": []}), encoding="utf-8")
    assert "doit correspondre exactement" in " ".join(valider_semaine(racine).erreurs)
    index.unlink()
    assert "index absent" in " ".join(valider_semaine(racine).erreurs)


def test_valider_refuse_les_traces_operer(tmp_path):
    racine = copie(PLEINE, tmp_path)
    (racine / "docs/data/claude/2026-10-07.json").write_text(
        (racine / "docs/data/claude/2026-10-07.json").read_text(encoding="utf-8").replace("Ajouter l'effort", "mission m-0123456789ab Ajouter l'effort"), encoding="utf-8")
    sem.ecrire(racine, sem.construire(racine, "2026-W41", MAINTENANT))
    r = valider.Rapport()
    valider.verifier_organisation_privee(racine, r)
    assert not r.ok  # le motif d'une mission recopié dans le bilan reste refusé par D77 sur tout docs/data


def test_site_onglet_semaine():
    html = (RACINE / "docs" / "index.html").read_text(encoding="utf-8")
    aujourdhui = '<a href="#aujourdhui" data-page="aujourdhui">Aujourd\'hui</a>'
    assert aujourdhui + '\n        <a href="#semaine" data-page="semaine">Semaine</a>' in html
    app = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    for attendu in ('lireJson("data/semaine/index.json")', 'lireJson(`data/semaine/${semaine}.json`)', 'case "semaine": main.append(pageSemaine())',
                    '"aujourdhui", "semaine", "changelogs"', "RE_SEMAINE.test(param || \"\")", "location.hash = `#semaine/${choixSemaine.value}`",
                    '"Compte et quotas", d.d71', "d.base_ajoutees", "d.base_verdicts", "`#archives/${l.jour}`"):
        assert attendu in app, attendu
    # jamais de HTML injecté depuis les données (même règle que le reste du site)
    assert ".innerHTML" not in app and "insertAdjacentHTML" not in app
    css = (RACINE / "docs" / "assets" / "style.css").read_text(encoding="utf-8")
    assert ".ligne-semaine" in css and ".bloc-semaine" in css


def test_branchement_du_passage_claude():
    skill = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "`.venv/bin/python scripts/semaine.py`" in skill and "git add docs/data/actu state/actu.json docs/data/semaine" in skill
    assert skill.index("**Bilan de la semaine (D98)") < skill.index("9. **Commit**") and "périmètre `actu` seulement, avant le commit" in skill
    allow = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    for r in ("Bash(.venv/bin/python scripts/semaine.py)", "Bash(git add docs/data/actu state/actu.json docs/data/semaine)",
              "Bash(git checkout -- docs/data/semaine)", "Bash(git clean -f -- docs/data/claude docs/data/actu docs/data/semaine)"):
        assert r in allow, r
    import garde
    assert "docs/data/semaine/" in garde.CHEMINS_ETAPE["delta"] and "docs/data/semaine/" in garde.CHEMINS_PASSAGE
    assert "docs/data/semaine/" not in garde.CHEMINS_ETAPE["codex-delta"]
    spec = (RACINE / "SPEC.md").read_text(encoding="utf-8")
    assert "`docs/data/etat.json`, `docs/data/semaine/`, `state/claude.json`" in spec and "| D98 |" in spec
    assert "`docs/data/semaine/`, `state/claude.json`" in (RACINE / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`docs/data/semaine/`" in (RACINE / "AGENTS.md").read_text(encoding="utf-8")
