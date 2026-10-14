"""Retours de Sylvain sur la sélection (scripts/retour.py, deltalib/selection.py) : écriture, bout en bout avec S1, bilan mensuel."""

import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import pytest
import yaml

import retour as cli
from deltalib import selection as sel
from test_selection import SEMAINE, depot, fiche, ids_de, lancer

RACINE_DEPOT = Path(__file__).resolve().parent.parent
FICHES = [fiche(f"f{i}", categorie=["commandes", "parametres", "skills", "mcp"][i % 4], nom=f"Fiche {i}") for i in range(1, 9)]


def retour(racine, *args, jour="2026-10-13"):
    return cli.main(["--racine", str(racine), "--jour", jour, *args])


def fichier(racine):
    return racine / "rapports" / "selection" / "retours.yaml"


def semaine_produite(tmp_path, fiches=FICHES):
    racine = depot(tmp_path, fiches)
    assert lancer(racine, "--json") == 0
    return racine


def test_ecrit_une_ligne_au_format_de_s1(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ident = ids_de(capsys, racine)[0]
    assert retour(racine, ident, "utile") == 0
    assert "enregistré" in capsys.readouterr().out
    assert yaml.safe_load(fichier(racine).read_text()) == [{"date": "2026-10-13", "id": ident, "retour": "utile"}]
    assert sel.lire_retours(racine / sel.DOSSIER) == [{"date": "2026-10-13", "id": ident, "retour": "utile"}]


def test_sortie_json(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ident = ids_de(capsys, racine)[0]
    assert retour(racine, ident, "connu", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"date": "2026-10-13", "id": ident, "retour": "connu", "enregistre": True}


def test_chaine_complete_la_selection_relit_ce_que_retour_ecrit(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    avant = ids_de(capsys, racine)
    utile, revoir, connu = avant[0], avant[1], avant[2]
    assert [retour(racine, i, r) for i, r in ((utile, "utile"), (revoir, "a_revoir"), (connu, "connu"))] == [0, 0, 0]
    capsys.readouterr()
    assert lancer(racine, "--json") == 0   # semaine figée : annotée à l'appel, fichier de la semaine inchangé
    annotes = {e["id"]: (e["retour"], e["retour_le"]) for e in json.loads(capsys.readouterr().out)["entrees"]}
    assert annotes[utile] == ("utile", "2026-10-13") and annotes[connu] == ("connu", "2026-10-13")
    suivante = ids_de(capsys, racine, jour="2026-10-19")  # 2026-W43 : rien ne revient, a_revoir attend
    assert utile not in suivante and connu not in suivante and revoir not in suivante
    assert revoir in ids_de(capsys, racine, jour="2026-11-16")  # 28 jours après le retour : l'entrée revient


def test_meme_retour_le_meme_jour_ne_fait_rien(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ident = ids_de(capsys, racine)[0]
    assert retour(racine, ident, "utile") == 0
    avant = fichier(racine).read_text()
    capsys.readouterr()
    assert retour(racine, ident, "utile", "--json") == 0
    assert json.loads(capsys.readouterr().out)["enregistre"] is False and fichier(racine).read_text() == avant


def test_autre_retour_le_meme_jour_le_remplace(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ident = ids_de(capsys, racine)[0]
    assert retour(racine, ident, "connu") == 0 and retour(racine, ident, "a_revoir") == 0
    assert sel.dernier_retour(sel.lire_retours(racine / sel.DOSSIER))[ident]["retour"] == "a_revoir"
    assert len(yaml.safe_load(fichier(racine).read_text())) == 2


def test_lignes_et_notes_existantes_sont_conservees(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    a, b = ids_de(capsys, racine)[:2]
    fichier(racine).write_text(yaml.safe_dump([{"date": "2026-10-01", "id": a, "retour": "connu", "note": "vu dans le bref"}]))
    assert retour(racine, b, "utile") == 0
    assert yaml.safe_load(fichier(racine).read_text())[0] == {"date": "2026-10-01", "id": a, "retour": "connu", "note": "vu dans le bref"}


def test_identifiant_inconnu_code_3_sans_rien_ecrire(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ids = ids_de(capsys, racine)
    assert retour(racine, "faute-de-frappe", "utile") == 3
    err = capsys.readouterr().err
    assert "faute-de-frappe" in err and ids[0] in err and not fichier(racine).exists()


def test_identifiant_inconnu_sans_aucune_selection(tmp_path, capsys):
    racine = depot(tmp_path, FICHES)
    assert retour(racine, "f1", "utile") == 3
    assert "aucune sélection produite" in capsys.readouterr().err and not fichier(racine).exists()


@pytest.mark.parametrize("args", [["f1", "bof"], ["f1"], [], ["--bilan", "2026-13"], ["--bilan", "f1", "utile"], ["--bilan", "2026-10", "f1"]])
def test_usage_invalide_code_2(tmp_path, capsys, args):
    racine = semaine_produite(tmp_path)
    assert retour(racine, *args) == 2
    assert capsys.readouterr().err and not fichier(racine).exists()


@pytest.mark.parametrize("contenu", ["texte seul", "- {date: hier, id: x, retour: connu}", "- {date: '2026-10-01', id: x, retour: bof}"])
def test_fichier_de_retours_mal_forme_code_1_sans_ecrire(tmp_path, capsys, contenu):
    racine = semaine_produite(tmp_path)
    ident = ids_de(capsys, racine)[0]
    fichier(racine).write_text(contenu, encoding="utf-8")
    assert retour(racine, ident, "utile") == 1
    assert "retours.yaml" in capsys.readouterr().err and fichier(racine).read_text() == contenu


def test_fichier_de_semaine_illisible_code_1(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    (racine / sel.DOSSIER / f"{SEMAINE}.json").write_text("{", encoding="utf-8")
    assert retour(racine, "f1", "utile") == 1
    assert SEMAINE in capsys.readouterr().err


def test_ecritures_simultanees_ne_perdent_aucune_ligne(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ids = ids_de(capsys, racine)
    dossier = racine / sel.DOSSIER
    fils = [threading.Thread(target=sel.enregistrer_retour, args=(dossier, i, "connu", date(2026, 10, 13))) for i in ids * 3]
    [t.start() for t in fils]
    [t.join() for t in fils]
    lignes = sel.lire_retours(dossier)
    assert sorted(r["id"] for r in lignes) == sorted(ids) and not list(dossier.glob("*.tmp"))


def test_lancee_depuis_un_autre_repertoire(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    ident = ids_de(capsys, racine)[0]
    sortie = subprocess.run([sys.executable, str(RACINE_DEPOT / "scripts" / "retour.py"), "--racine", str(racine), ident, "utile"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert sortie.returncode == 0 and ident in sortie.stdout
    mauvais = subprocess.run([sys.executable, str(RACINE_DEPOT / "scripts" / "retour.py"), "--racine", str(racine), ident, "bof"],
                             cwd=tmp_path, capture_output=True, text=True)
    assert mauvais.returncode == 2 and "bof" in mauvais.stderr


def test_ne_touche_ni_la_base_ni_le_site(tmp_path, capsys):
    racine = semaine_produite(tmp_path)
    avant = {p: p.read_bytes() for p in racine.rglob("*") if p.is_file() and sel.DOSSIER.parts[0] not in p.relative_to(racine).parts}
    assert retour(racine, ids_de(capsys, racine)[0], "utile") == 0
    assert {p: p.read_bytes() for p in racine.rglob("*") if p.is_file() and "rapports" not in p.relative_to(racine).parts} == avant
    assert not (racine / "kb-essais.yaml").exists()


# --- bilan mensuel -----------------------------------------------------------------------------------------------------

def semaines_fictives(racine, **semaines):
    dossier = racine / sel.DOSSIER
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, ids in semaines.items():
        (dossier / f"{nom.replace('_', '-')}.json").write_text(json.dumps({"semaine": nom.replace("_", "-"), "entrees": [{"id": i} for i in ids]}))
    return dossier


def test_bilan_mensuel(tmp_path, capsys):
    racine = tmp_path / "d"
    # W41 (lundi 5/10), W42 (12/10), W43 (19/10) : octobre ; W44 (26/10) : octobre ; W45 (2/11) : novembre
    semaines_fictives(racine, **{"2026_W41": ["a", "b", "c"], "2026_W42": ["c", "d", "e"], "2026_W45": ["z"]})
    (racine / sel.DOSSIER / "retours.yaml").write_text(yaml.safe_dump([
        {"date": "2026-10-06", "id": "a", "retour": "utile"}, {"date": "2026-10-06", "id": "b", "retour": "connu"},
        {"date": "2026-10-14", "id": "c", "retour": "a_revoir"}, {"date": "2026-10-20", "id": "c", "retour": "utile"},
        {"date": "2026-10-14", "id": "d", "retour": "sans_interet"}, {"date": "2026-11-03", "id": "z", "retour": "utile"}]))
    assert retour(racine, "--bilan", "2026-10", "--json") == 0
    b = json.loads(capsys.readouterr().out)
    assert b["semaines"] == ["2026-W41", "2026-W42"] and b["proposees"] == 5 and b["avec_retour"] == 4  # c compté une fois
    assert b["repartition"] == {"utile": 2, "connu": 1, "sans_interet": 1, "a_revoir": 0, "sans_retour": 1}
    assert b["taux_utiles"] == 40.0 and b["taux_utiles_sur_retours"] == 50.0
    assert retour(racine, "--bilan", "2026-11", "--json") == 0
    assert json.loads(capsys.readouterr().out)["taux_utiles"] == 100.0


def test_bilan_texte_et_mois_courant_par_defaut(tmp_path, capsys):
    racine = tmp_path / "d"
    semaines_fictives(racine, **{"2026_W42": ["a", "b"]})
    (racine / sel.DOSSIER / "retours.yaml").write_text(yaml.safe_dump([{"date": "2026-10-13", "id": "a", "retour": "utile"}]))
    assert retour(racine, "--bilan") == 0
    sortie = capsys.readouterr().out
    assert "2026-10" in sortie and "50 % des proposées" in sortie and "100 % des entrées avec retour" in sortie


def test_bilan_sans_selection_ni_retour(tmp_path, capsys):
    racine = tmp_path / "d"
    assert retour(racine, "--bilan", "2026-10", "--json") == 0
    b = json.loads(capsys.readouterr().out)
    assert b["proposees"] == 0 and b["taux_utiles"] is None and b["taux_utiles_sur_retours"] is None
    assert retour(racine, "--bilan", "2026-10") == 0 and "aucune entrée" in capsys.readouterr().out
    assert not (racine / sel.DOSSIER / "retours.yaml").exists()


def test_bilan_est_en_lecture_seule(tmp_path, capsys):
    racine = tmp_path / "d"
    dossier = semaines_fictives(racine, **{"2026_W42": ["a"]})
    avant = sorted(p.name for p in dossier.iterdir())
    assert retour(racine, "--bilan", "2026-10") == 0
    assert sorted(p.name for p in dossier.iterdir()) == avant
