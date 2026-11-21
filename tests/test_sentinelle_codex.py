"""Sentinelle `.gitattributes` du pilote Codex : les quatre contrôles d'arbre tolèrent EXACTEMENT ce fichier (vide, 0444, régulier,
non suivi, à la racine) et refusent tout autre état à ce chemin. Dépôts temporaires uniquement."""

import importlib.util
import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

import commun_auto
import orchestrateur as orc
import selection_auto as auto
from deltalib import capteur_x
from deltalib.sentinelle import est_sentinelle_codex
from test_capteur_x import depot_publication  # noqa: F401  (fixture)
from test_orchestrateur import JOUR, chaine, codes, cfg, depot, etape, journal  # noqa: F401  (fixtures et aides)
from test_garde import lancer, pauses, racine  # noqa: F401  (fixtures et aide de garde.py)
from test_selection_auto import LUNDI, publication  # noqa: F401  (fixture)
from test_selection_auto import git as git_sel


@pytest.fixture(autouse=True)
def etat_xdg_de_test(tmp_path, monkeypatch):
    """SUITE 4, point 2 : une chaîne propre écrit la référence d'empreinte git sous XDG_STATE_HOME ; jamais le vrai ~/.local/state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "etat-xdg"))

DISCIPLINE = Path.home() / "projets" / "discipline" / "src" / "delta" / "operer" / "restes_bac.py"
CONTENU = "* merge=union\n"


def git(racine, *args):
    return subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture(autouse=True)
def git_isole(monkeypatch):
    """Ni configuration personnelle (excludesfile, attributs globaux), ni signature réelle dans ces dépôts d'essai."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t")


# --- états du chemin `.gitattributes` ---------------------------------------------------------------------------------

def _ecrire(chemin, texte, mode):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte)
    chemin.chmod(mode)



# nom -> (poseur, tolérée ?)
ETATS = {
    "vide-0444": (lambda r: _ecrire(r / ".gitattributes", "", 0o444), True),
    "vide-0644": (lambda r: _ecrire(r / ".gitattributes", "", 0o644), False),
    "vide-0000": (lambda r: _ecrire(r / ".gitattributes", "", 0o000), False),
    "vide-0400": (lambda r: _ecrire(r / ".gitattributes", "", 0o400), False),
    "vide-0555": (lambda r: _ecrire(r / ".gitattributes", "", 0o555), False),
    "contenu-0444": (lambda r: _ecrire(r / ".gitattributes", CONTENU, 0o444), False),
    "contenu-0644": (lambda r: _ecrire(r / ".gitattributes", CONTENU, 0o644), False),
    # cible hors du dépôt : seul le lien lui-même peut faire refuser (aucun `?? cible` à côté)
    "lien": (lambda r: ((r.parent / "cible-hors-depot").write_text(""), (r.parent / "cible-hors-depot").chmod(0o444),
                        (r / ".gitattributes").symlink_to(r.parent / "cible-hors-depot")), False),
    "lien-pendant": (lambda r: (r / ".gitattributes").symlink_to("absent"), False),
    "repertoire": (lambda r: _ecrire(r / ".gitattributes" / "x", "", 0o444), False),
    "sous-dossier": (lambda r: _ecrire(r / "sous" / ".gitattributes", "", 0o444), False),
    "indexe": (lambda r: (_ecrire(r / ".gitattributes", "", 0o444), git(r, "add", ".gitattributes")), False),
    "suivi-modifie": (lambda r: (_ecrire(r / ".gitattributes", CONTENU, 0o644), git(r, "add", ".gitattributes"),
                                 git(r, "commit", "-qm", "attributs"), _ecrire(r / ".gitattributes", "", 0o444)), False),
}
REFUSES = [n for n, (_, ok) in ETATS.items() if not ok]


@pytest.fixture
def dossier(tmp_path):
    racine = tmp_path / "depot"
    racine.mkdir()
    git(racine, "init", "-q", "-b", "main")
    (racine / "notes.txt").write_text("base\n")
    git(racine, "add", "notes.txt")
    git(racine, "commit", "-qm", "base")
    return racine


def lignes_statut(racine):
    return [l for l in git(racine, "status", "--porcelain=v1", "--untracked-files=all").splitlines() if l]


# --- la fonction ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("nom", list(ETATS))
def test_fonction_sentinelle_sur_les_lignes_reelles_de_git(dossier, nom):
    poser, attendu = ETATS[nom]
    poser(dossier)
    lignes = lignes_statut(dossier)
    assert lignes, "git doit voir le fichier"
    assert any(est_sentinelle_codex(dossier, l) for l in lignes) is attendu


@pytest.mark.parametrize("nom", ["vide-0444", "contenu-0444", "vide-0644", "lien", "sous-dossier"])
def test_fonction_sentinelle_sur_la_liste_des_non_suivis(dossier, nom):
    ETATS[nom][0](dossier)
    autres = git(dossier, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    assert any(est_sentinelle_codex(dossier, "?? " + c) for c in autres if c) is ETATS[nom][1]


def test_fonction_sentinelle_fichier_absent_ou_autre_nom(dossier):
    assert not est_sentinelle_codex(dossier, "?? .gitattributes")
    _ecrire(dossier / ".gitattributes", "", 0o444)
    assert est_sentinelle_codex(dossier, "?? .gitattributes")
    assert not est_sentinelle_codex(dossier, "?? notes.txt")
    assert not est_sentinelle_codex(dossier, "?? .gitattributes.bak")
    assert not est_sentinelle_codex(dossier, "?? ./.gitattributes")
    assert not est_sentinelle_codex(dossier, " M .gitattributes")
    assert not est_sentinelle_codex(dossier, "A  .gitattributes")
    assert not est_sentinelle_codex(dossier, ".gitattributes")


# --- épinglage contre discipline -------------------------------------------------------------------------------------

@pytest.mark.skipif(not DISCIPLINE.is_file(), reason=f"épinglage sauté : checkout de discipline absent ({DISCIPLINE})")
@pytest.mark.parametrize("nom", list(ETATS))
def test_accord_avec_le_critere_de_discipline(dossier, nom):
    spec = importlib.util.spec_from_file_location("restes_bac_discipline", DISCIPLINE)
    discipline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(discipline)
    ETATS[nom][0](dossier)
    lignes = lignes_statut(dossier)
    nous = [est_sentinelle_codex(dossier, l) for l in lignes]
    eux = [discipline.est_ligne_reste(dossier, l) for l in lignes]
    if nous != eux and nom in ("vide-0000", "vide-0400", "vide-0555") and not any(nous):
        pytest.skip(f"{nom} : discipline tolère encore tout fichier vide sans bit d'écriture ; le lot qui resserre à 0444 exact "
                    "n'est pas fusionné, comparaison bornée aux cas communs")
    assert nous == eux


# --- 1. orchestrateur.etat_depot (code 126) --------------------------------------------------------------------------

def test_etat_depot_tolere_la_sentinelle(dossier):
    ETATS["vide-0444"][0](dossier)
    assert orc.etat_depot(dossier, distant=False)["sales"] == []


@pytest.mark.parametrize("nom", REFUSES)
def test_etat_depot_refuse_tout_autre_etat(dossier, nom):
    ETATS[nom][0](dossier)
    avant = lignes_statut(dossier)
    sales = [l.strip() for l in orc.etat_depot(dossier, distant=False)["sales"]]
    # `git()` de l'orchestrateur mêle stderr à stdout : un avertissement de git (fichier illisible, lien en boucle) s'y ajoute, comme avant.
    assert sales and all(l.strip() in sales for l in avant)


def test_chaine_tolere_la_sentinelle_sans_la_toucher(depot, cfg):
    assert chaine(depot, cfg, [etape(depot, "delta", "sentinelle", checkout=["docs/data/claude"])]).executer() == 0
    assert codes(depot)["delta"] == 0
    assert (depot / ".gitattributes").read_text() == "", "la sentinelle n'est ni retirée ni modifiée"


def test_chaine_refuse_un_gitattributes_a_contenu_meme_code_et_meme_message(depot, cfg):
    assert chaine(depot, cfg, [etape(depot, "delta", "gitattributes-contenu", checkout=["docs/data/claude"])]).executer() == 1
    assert codes(depot)["delta"] == orc.CODE_ETAT == 126
    assert "arbre non propre après l'étape (1 fichier(s)) : .gitattributes" in (depot / "rapports" / "auto" / "2026-10-02-delta.log").read_text()


# --- 2. commun_auto (changements, verifier_arbre) --------------------------------------------------------------------

def test_commun_auto_tolere_la_sentinelle(dossier):
    ETATS["vide-0444"][0](dossier)
    assert commun_auto.changements(dossier) == set()
    commun_auto.verifier_arbre(dossier)


@pytest.mark.parametrize("nom", REFUSES)
def test_commun_auto_refuse_tout_autre_etat_meme_message(dossier, nom):
    ETATS[nom][0](dossier)
    assert commun_auto.changements(dossier)
    with pytest.raises(RuntimeError, match=r"arbre modifié hors de la route commune \(\d+ chemin\(s\)\) ; aucune publication"):
        commun_auto.verifier_arbre(dossier)


def test_commun_auto_la_sentinelle_ne_masque_pas_un_autre_chemin(dossier):
    ETATS["vide-0444"][0](dossier)
    (dossier / "hors-route.txt").write_text("x")
    assert commun_auto.changements(dossier) == {"hors-route.txt"}
    with pytest.raises(RuntimeError, match="hors de la route"):
        commun_auto.verifier_arbre(dossier)


# --- 3. capteur_x.publier_ids ----------------------------------------------------------------------------------------

def test_capteur_x_publie_avec_la_sentinelle(depot_publication):
    racine, g = depot_publication
    ETATS["vide-0444"][0](racine)
    code, commit, message = capteur_x.publier_ids(racine)
    assert (code, message) == (0, "identifiants publiés") and commit == g("rev-parse", "--short=12", "HEAD")
    assert g("show", "--format=", "--name-only", "HEAD") == str(capteur_x.FICHIER_IDS)
    assert (racine / ".gitattributes").read_text() == ""


@pytest.mark.parametrize("nom", REFUSES)
def test_capteur_x_refuse_tout_autre_etat_meme_code_et_message(depot_publication, nom):
    racine, g = depot_publication
    ETATS[nom][0](racine)
    avant = g("rev-parse", "HEAD")
    assert capteur_x.publier_ids(racine) == (1, "aucun", "publication X différée (ValueError)")
    assert g("rev-parse", "HEAD") == avant


# --- 4. selection_auto (changements_selection) et orchestrateur.publier_selection_en_attente -------------------------

def test_selection_auto_publie_avec_la_sentinelle(publication):
    racine, distant = publication
    ETATS["vide-0444"][0](racine)
    assert auto.changements_selection(racine) == set()
    auto.executer(racine, LUNDI)
    assert git_sel(distant, "rev-parse", "main") == git_sel(racine, "rev-parse", "HEAD")
    assert (racine / ".gitattributes").read_text() == ""


@pytest.mark.parametrize("nom", REFUSES)
def test_selection_auto_refuse_tout_autre_etat_meme_message(publication, nom):
    racine, distant = publication
    avant = git_sel(distant, "rev-parse", "main")
    ETATS[nom][0](racine)
    with pytest.raises(RuntimeError, match="arbre ou index modifié hors sélection ; aucune publication"):
        auto.executer(racine, LUNDI)
    assert git_sel(distant, "rev-parse", "main") == avant


def _selection_en_attente(depot):
    (depot / ".gitignore").write_text("rapports/*\n!rapports/selection/\nrapports/selection/*\n"
                                       "!rapports/selection/*.json\n!rapports/selection/*.md\n"
                                       "raw/\n__pycache__/\n.venv/\n")
    depot.sh("git", "add", ".gitignore")
    depot.sh("git", "commit", "-qm", "suivre les sorties de sélection")
    depot.sh("git", "push", "-q", "origin", "HEAD:refs/heads/main")
    selection = depot / "rapports" / "selection"
    selection.mkdir(parents=True)
    fichiers = [selection / "2026-W40.json", selection / "2026-W40.md"]
    for f in fichiers:
        f.write_text("sortie en attente\n")
    return fichiers


def test_selection_en_attente_est_publiee_malgre_la_sentinelle(depot, monkeypatch):
    fichiers = _selection_en_attente(depot)
    ETATS["vide-0444"][0](depot)
    appels = []
    monkeypatch.setattr(auto, "publier", lambda racine, jour: appels.append(jour))
    assert orc.publier_selection_en_attente(depot, JOUR) is None
    assert appels == [JOUR] and all(f.exists() for f in fichiers)


@pytest.mark.parametrize("nom", REFUSES)
def test_selection_en_attente_ne_publie_pas_avec_un_autre_etat(depot, monkeypatch, nom):
    _selection_en_attente(depot)
    ETATS[nom][0](depot)
    appels = []
    monkeypatch.setattr(auto, "publier", lambda racine, jour: appels.append(jour))
    assert orc.publier_selection_en_attente(depot, JOUR) is None
    assert appels == []


# --- garde.py, contrôle 4 (constat (iii) du 20/11) : un `.gitattributes` de racine arrête la garde, la sentinelle exceptée -----
# Avant la correction, un `??` ne comptait que sous CHEMINS_PASSAGE et, avec --etape, un suivi modifié hors CHEMINS_ETAPE
# passait : ni la sentinelle ni un vrai `.gitattributes` n'étaient vus. Désormais tout état de ce chemin autre que la
# sentinelle exacte (même table ETATS que les quatre autres contrôles) donne 13, quelle que soit l'étape.

ETAPES_GARDE = [[], ["--etape", "delta"], ["--etape", "codex-delta"], ["--etape", "delta-kb"], ["--etape", "codex-delta-kb"]]


@pytest.fixture
def depot_garde(tmp_path, racine):
    """Le dépôt de test de garde.py, un niveau plus bas : l'état « lien » pose sa cible dans le dossier parent, propre au test."""
    depot = tmp_path / "depot"
    depot.mkdir()
    for f in [p for p in racine.iterdir() if p.name != "depot"]:  # `racine` est tmp_path : le dépôt (et .git) y descend
        f.rename(depot / f.name)
    return depot


@pytest.mark.parametrize("nom", list(ETATS))
@pytest.mark.parametrize("etape", ETAPES_GARDE)
def test_garde_refuse_tout_gitattributes_hors_sentinelle(depot_garde, capsys, nom, etape):
    ETATS[nom][0](depot_garde)
    code, out = lancer(depot_garde, capsys, *etape)
    if ETATS[nom][1]:
        assert code == 0, out
    else:
        assert code == 13 and ".gitattributes" in out, out


@pytest.mark.parametrize("etape", ETAPES_GARDE)
def test_garde_refuse_un_gitattributes_cite_par_git(depot_garde, capsys, etape):
    """Un chemin à espace sort entre guillemets dans `git status` : le nom se lit sans eux."""
    _ecrire(depot_garde / "un dossier" / ".gitattributes", CONTENU, 0o644)
    code, out = lancer(depot_garde, capsys, *etape)
    assert code == 13 and "un dossier/.gitattributes" in out, out


# --- retouches de relecture : ligne brute, racine = haut du dépôt ----------------------------------------------------

@pytest.fixture
def sans_guillemets(monkeypatch):
    """core.quotePath=false : un nom à espace insécable sort de git sans guillemets."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.quotePath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")


@pytest.mark.parametrize("voisin", [".gitattributes\u00a0", " .gitattributes", ".gitattributes "])
def test_nom_a_espace_voisin_de_la_sentinelle_n_est_pas_tolere(dossier, sans_guillemets, voisin):
    ETATS["vide-0444"][0](dossier)
    _ecrire(dossier / voisin, "", 0o444)
    assert not any(est_sentinelle_codex(dossier, l) for l in lignes_statut(dossier) if l != "?? .gitattributes")
    assert [l for l in orc.etat_depot(dossier, distant=False)["sales"] if voisin in l], "l'orchestrateur voit le voisin"
    assert commun_auto.changements(dossier) == {voisin}
    with pytest.raises(RuntimeError, match="hors de la route"):
        commun_auto.verifier_arbre(dossier)


@pytest.mark.parametrize("voisin", [".gitattributes\u00a0", " .gitattributes"])
def test_capteur_x_refuse_un_nom_a_espace_voisin_de_la_sentinelle(depot_publication, sans_guillemets, voisin):
    racine, g = depot_publication
    ETATS["vide-0444"][0](racine)
    _ecrire(racine / voisin, "", 0o444)
    assert capteur_x.publier_ids(racine) == (1, "aucun", "publication X différée (ValueError)")


@pytest.mark.parametrize("voisin", [".gitattributes\u00a0", " .gitattributes"])
def test_selection_refuse_un_nom_a_espace_voisin_de_la_sentinelle(publication, sans_guillemets, voisin):
    racine, distant = publication
    ETATS["vide-0444"][0](racine)
    _ecrire(racine / voisin, "", 0o444)
    with pytest.raises(RuntimeError, match="hors sélection"):
        auto.changements_selection(racine)


def test_sentinelle_refusee_sans_depot_a_la_racine_passee(dossier, tmp_path):
    ETATS["vide-0444"][0](dossier)
    assert est_sentinelle_codex(dossier, "?? .gitattributes")
    hors = tmp_path / "hors-depot"
    hors.mkdir()
    _ecrire(hors / ".gitattributes", "", 0o444)
    assert not est_sentinelle_codex(hors, "?? .gitattributes")
    sous = dossier / "sous"
    _ecrire(sous / ".gitattributes", "", 0o444)  # sous-dossier d'un dépôt : ce n'est pas le haut, les chemins de git n'y sont pas relatifs
    assert not est_sentinelle_codex(sous, "?? .gitattributes")
