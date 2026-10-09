"""D114 : index de recherche de la veille (scripts/recherche.py, deltalib/recherche.py), son contrôle par valider.py,
la recherche du site (onglet Archives) et le branchement dans la chaîne."""

import json
import shutil
from pathlib import Path

import pytest

import garde
import recherche as cli
import valider
from conftest import FIXTURES, RACINE
from deltalib import recherche as rech

PLEINE = FIXTURES / "semaine" / "pleine"
MAINTENANT = "2026-10-09T12:00:00+00:00"


def copie(modele: Path, tmp_path: Path) -> Path:
    racine = tmp_path / "depot"
    shutil.copytree(modele, racine)
    return racine


def ecrire_jour(racine: Path, perimetre: str, jour: str, elements: list[dict]) -> Path:
    f = racine / "docs" / "data" / perimetre / f"{jour}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"date": jour, "perimetre": perimetre, "elements": elements}), encoding="utf-8")
    return f


def element(i: str, **champs) -> dict:
    return {"id": i, "titre": f"Titre {i}", "resume": "résumé", "impact": "moyen", "pour_toi": None, "action": None, **champs}


def test_index_complet_sur_les_trois_perimetres():
    d = rech.construire(PLEINE, MAINTENANT)
    attendu = 0
    for p in rech.PERIMETRES:
        for f in (PLEINE / "docs" / "data" / p).glob("????-??-??.json"):
            attendu += len(json.loads(f.read_text(encoding="utf-8"))["elements"])
    assert attendu > 3 and d["total"] == attendu == len(d["elements"])
    assert d["statut"] == "ok" and d["raison"] is None and set(d) == rech.CHAMPS
    assert {l["perimetre"] for l in d["elements"]} == {"claude", "actu", "openai"}
    assert d["sources"]["claude"]["jours"] == ["2026-10-04", "2026-10-06", "2026-10-07", "2026-10-12"]
    assert all(set(l) == rech.CHAMPS_ELEMENT for l in d["elements"])


def test_tri_date_decroissante_puis_perimetre_et_id():
    d = rech.construire(PLEINE, MAINTENANT)
    cles = [(l["date"], l["perimetre"], l["id"]) for l in d["elements"]]
    assert cles == sorted(cles, reverse=True) and cles[0][0] == "2026-10-12"


def test_texte_recopie_resume_pour_toi_et_action(tmp_path):
    racine = tmp_path / "d"
    ecrire_jour(racine, "claude", "2026-10-08", [element(
        "a", titre="Le  titre\n sur deux lignes", resume="Le résumé\ndit `/code-review`.", pour_toi="Pour delta-ia.",
        action={"description": "Lancer `/code-review`.", "etapes": ["étape non indexée"], "effort": "5min"})])
    ecrire_jour(racine, "actu", "2026-10-08", [element("b", resume="seul", action="Action en texte simple.", impact=None)])
    l = {x["id"]: x for x in rech.construire(racine, MAINTENANT)["elements"]}
    assert l["a"]["titre"] == "Le titre sur deux lignes"  # espaces réduits, rien d'autre ne change
    assert l["a"]["texte"] == "Le résumé dit `/code-review`." + " · " + "Pour delta-ia." + " · " + "Lancer `/code-review`."
    assert "étape" not in l["a"]["texte"] and l["a"]["impact"] == "moyen"
    assert l["b"]["texte"] == "seul · Action en texte simple." and l["b"]["impact"] is None
    assert l["a"]["date"] == "2026-10-08" and l["a"]["perimetre"] == "claude"


def test_champ_vide_ou_absent_ne_laisse_pas_de_separateur(tmp_path):
    racine = tmp_path / "d"
    e = element("a", resume="", pour_toi=None, action={"description": "  "})
    del e["titre"]
    ecrire_jour(racine, "claude", "2026-10-08", [e])
    l = rech.construire(racine, MAINTENANT)["elements"][0]
    assert l["texte"] == "" and l["titre"] == ""


def test_texte_borne_chaque_champ_coupe_sur_un_mot(tmp_path):
    racine = tmp_path / "d"
    long = " ".join(["mot"] * 2000)
    ecrire_jour(racine, "claude", "2026-10-08", [element("a", resume=long, pour_toi=long, action={"description": long})])
    l = rech.construire(racine, MAINTENANT)["elements"][0]
    assert len(l["texte"]) <= rech.MAX_TEXTE
    morceaux = l["texte"].split(rech.SEPARATEUR)
    assert [len(m) <= m_max for m, m_max in zip(morceaux, (rech.MAX_RESUME, rech.MAX_POUR_TOI, rech.MAX_ACTION))] == [True] * 3
    assert all(m.endswith("mot…") for m in morceaux)  # coupé entre deux mots, jamais au milieu
    court = rech._coupe("x" * 10, 10)
    assert court == "x" * 10  # ce qui tient n'est pas touché
    assert rech._coupe("abcdefghij", 5) == "abcd…"  # pas d'espace : coupe sèche


def test_un_fichier_illisible_est_signale_et_les_autres_restent(tmp_path, capsys):
    racine = copie(PLEINE, tmp_path)
    (racine / "docs" / "data" / "claude" / "2026-10-06.json").write_text("{pas du json", encoding="utf-8")
    ecrire_jour(racine, "openai", "2026-10-08", [])
    (racine / "docs" / "data" / "openai" / "2026-10-08.json").write_text(json.dumps({"elements": "x"}), encoding="utf-8")
    d = rech.construire(racine, MAINTENANT)
    assert d["statut"] == "echec" and "claude/2026-10-06.json illisible" in d["raison"] and "openai/2026-10-08.json illisible" in d["raison"]
    assert d["sources"]["claude"]["statut"] == "echec" and d["sources"]["actu"]["statut"] == "ok"
    assert "2026-10-06" not in d["sources"]["claude"]["jours"] and "2026-10-07" in d["sources"]["claude"]["jours"]
    assert d["total"] > 0
    assert cli.main(["--racine", str(racine)]) == 0  # le fichier est écrit, avertissement à l'écran
    out = capsys.readouterr().out
    assert "! AVERTISSEMENT recherche : statut echec" in out and (racine / rech.FICHIER).exists()


def test_depot_sans_donnees_ecrit_un_index_vide_valide(tmp_path, capsys):
    racine = tmp_path / "vide"
    racine.mkdir()
    assert cli.main(["--racine", str(racine)]) == 0
    d = json.loads((racine / rech.FICHIER).read_text(encoding="utf-8"))
    assert d["total"] == 0 and d["elements"] == [] and d["statut"] == "ok"
    r = valider.Rapport()
    valider.verifier_recherche(racine, r)
    assert r.ok, r.erreurs


def test_idempotence_et_ecriture_atomique(tmp_path, capsys):
    racine = copie(PLEINE, tmp_path)
    assert cli.main(["--racine", str(racine)]) == 0 and "écrit" in capsys.readouterr().out
    chemin = racine / rech.FICHIER
    avant = chemin.read_text(encoding="utf-8")
    assert cli.main(["--racine", str(racine)]) == 0 and "inchangé" in capsys.readouterr().out
    assert chemin.read_text(encoding="utf-8") == avant  # `genere_le` n'est pas réécrit à contenu égal
    ecrire_jour(racine, "claude", "2026-10-13", [element("nouveau")])
    assert cli.main(["--racine", str(racine)]) == 0 and "écrit" in capsys.readouterr().out
    d = json.loads(chemin.read_text(encoding="utf-8"))
    assert d["elements"][0]["id"] == "nouveau" and not list(chemin.parent.glob("*.tmp"))


def test_dry_run_n_ecrit_rien(tmp_path, capsys):
    racine = copie(PLEINE, tmp_path)
    assert cli.main(["--racine", str(racine), "--dry-run"]) == 0
    assert not (racine / rech.FICHIER).exists() and json.loads(capsys.readouterr().out)["total"] > 0


def test_ecriture_impossible_code_1(tmp_path, capsys):
    racine = copie(PLEINE, tmp_path)
    (racine / "docs" / "data" / "recherche.json").mkdir()  # un dossier à la place du fichier
    assert cli.main(["--racine", str(racine)]) == 1 and "écriture impossible" in capsys.readouterr().err


def test_json_compact_et_poids_borne(tmp_path):
    racine = copie(PLEINE, tmp_path)
    cli.main(["--racine", str(racine)])
    brut = (racine / rech.FICHIER).read_text(encoding="utf-8")
    assert "\n  " not in brut  # pas d'indentation : le fichier est lu par le navigateur
    assert len(brut.encode("utf-8")) < 40_000


def test_index_publie_conforme_et_de_poids_borne():
    chemin = RACINE / rech.FICHIER
    if not chemin.exists():
        pytest.skip("index non encore produit")
    octets = chemin.stat().st_size
    d = json.loads(chemin.read_text(encoding="utf-8"))
    # borne par élément : titre, texte au plus MAX_TEXTE caractères (2 octets au plus en UTF-8 pour ce texte), champs fixes
    assert octets <= max(d["total"], 1) * (2 * rech.MAX_TEXTE + 700) + 2_000
    assert all(len(l["texte"]) <= rech.MAX_TEXTE for l in d["elements"])
    r = valider.Rapport()
    valider.verifier_recherche(RACINE, r)
    assert r.ok, r.erreurs


# ---- valider.py ----

@pytest.fixture
def index_valide(tmp_path):
    racine = copie(PLEINE, tmp_path)
    cli.main(["--racine", str(racine)])
    return racine


def modifie(racine: Path, f):
    chemin = racine / rech.FICHIER
    d = json.loads(chemin.read_text(encoding="utf-8"))
    f(d)
    chemin.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = valider.Rapport()
    valider.verifier_recherche(racine, r)
    return r


def test_valider_accepte_l_index_et_l_absence(index_valide, tmp_path):
    r = valider.Rapport()
    valider.verifier_recherche(index_valide, r)
    assert r.ok, r.erreurs
    sans = tmp_path / "sans"
    sans.mkdir()
    r = valider.Rapport()
    valider.verifier_recherche(sans, r)
    assert r.ok


@pytest.mark.parametrize("nom, f, message", [
    ("champ en trop", lambda d: d.update(extra=1), "champs attendus"),
    ("statut inconnu", lambda d: d.update(statut="?"), "`statut`"),
    ("raison sans echec", lambda d: d.update(raison="x"), "`raison`"),
    ("total faux", lambda d: d.update(total=d["total"] + 1), "longueur égale `total`"),
    ("élément avec champ en trop", lambda d: d["elements"][0].update(extra=1), "champs attendus"),
    ("date invalide", lambda d: d["elements"][0].update(date="2026-13-40"), "invalide"),
    ("périmètre inconnu", lambda d: d["elements"][0].update(perimetre="autre"), "invalide"),
    ("impact inconnu", lambda d: d["elements"][0].update(impact="énorme"), "`impact`"),
    ("texte trop long", lambda d: d["elements"][0].update(texte="x" * (rech.MAX_TEXTE + 1)), "dépasse"),
    ("tri cassé", lambda d: d["elements"].reverse(), "tri attendu"),
    ("jour hors des sources", lambda d: d["sources"]["claude"]["jours"].remove(d["elements"][0]["date"]), "absente de `sources"),
    ("source manquante", lambda d: d["sources"].pop("actu"), "`sources` doit nommer"),
    ("statut incohérent avec les sources", lambda d: d["sources"]["actu"].update(statut="echec", raison="x"), "si et seulement si une source"),
])
def test_valider_refuse(index_valide, nom, f, message):
    r = modifie(index_valide, f)
    assert not r.ok and any(message in e for e in r.erreurs), (nom, r.erreurs)


def test_valider_refuse_un_secret(index_valide):
    r = modifie(index_valide, lambda d: d["elements"][0].update(texte="clé sk-ant-api03-" + "a" * 40))
    assert not r.ok


def test_valider_brancher_au_perimetre_claude():
    src = (RACINE / "scripts" / "valider.py").read_text(encoding="utf-8")
    assert "verifier_recherche(racine, r)  # D114" in src
    assert src.index("verifier_semaine(racine, r)  # D98") < src.index("verifier_recherche(racine, r)  # D114")


# ---- site ----

def test_site_recherche_des_archives():
    app = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    for attendu in ('lireJson("data/recherche.json")', 'case "archives": await Promise.all([chargerJoursArchive(), etat.archiveDate ? null : chargerRecherche()])',
                    'case "archives": main.append(pageArchives()); rendreResultatsRecherche(); break;', "const RECHERCHE_PAGE = 50;",
                    "etat.rq.limite += RECHERCHE_PAGE", "trouves.slice(0, etat.rq.limite)", 'new URLSearchParams(requete || "").get("q")',
                    "history.replaceState", "`#archives/${l.date}`", "termes.every("):
        assert attendu in app, attendu
    # sans casse ni accents : même pli pour l'index et pour la requête, longueur du texte conservée
    assert 'normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase()' in app and "p.length === c.length ? p : c" in app
    assert "plier(`" not in app and "_titre: plier(l.titre), _texte: plier(l.texte)" in app
    # recherche en place : l'index absent ou illisible se dit, il ne masque pas le reste des Archives
    assert "Recherche indisponible" in app and "Index incomplet" in app
    # jamais de HTML injecté depuis les données : les occurrences passent par <mark> et textContent
    bloc = app[app.index("/* ---------- Recherche dans toute la veille (D114)"):app.index("  function pageArchives()")]
    assert 'el("mark", { text:' in bloc and "innerHTML" not in bloc and "insertAdjacentHTML" not in app
    css = (RACINE / "docs" / "assets" / "style.css").read_text(encoding="utf-8")
    assert "mark {" in css and ".carte.resultat .extrait" in css and ".recherche" in css


def test_aide_dit_la_recherche():
    app = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    aide = app[app.index('{ id: "archives"'):app.index('{ id: "mcp"')]
    assert "`/code-review`" in aide and "sans casse ni accents" in aide and "Afficher plus" in aide and "recherche.json" in aide


# ---- branchement dans la chaîne ----

def test_branchement_du_passage_claude():
    skill = (RACINE / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "`.venv/bin/python scripts/recherche.py`" in skill and "git add docs/data/actu state/actu.json docs/data/semaine docs/data/recherche.json" in skill
    assert skill.index("**Bilan de la semaine (D98) et index de recherche (D114)") < skill.index("9. **Commit**")
    allow = json.loads((RACINE / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    for r in ("Bash(.venv/bin/python scripts/recherche.py)", "Bash(git add docs/data/actu state/actu.json docs/data/semaine docs/data/recherche.json)",
              "Bash(git checkout -- docs/data/semaine docs/data/recherche.json)",
              "Bash(git clean -f -- docs/data/claude docs/data/actu docs/data/semaine docs/data/recherche.json)"):
        assert r in allow, r
    assert "`git checkout -- docs/data/semaine docs/data/recherche.json`" in skill
    assert "`git clean -f -- docs/data/claude docs/data/actu docs/data/semaine docs/data/recherche.json`" in skill


def test_garde_orchestrateur_et_regles_de_perimetre():
    f = "docs/data/recherche.json"
    assert f in garde.CHEMINS_ETAPE["delta"] and f in garde.CHEMINS_PASSAGE
    assert f not in garde.CHEMINS_ETAPE["codex-delta"] and f not in garde.CHEMINS_ETAPE["delta-kb"]
    import orchestrateur as orc
    e = {x.nom: x for x in orc.construire_etapes(orc.charger_config(), RACINE)}
    assert f in e["delta"].checkout and f in e["delta"].clean
    assert all(f not in e[n].checkout for n in ("codex-delta", "delta-kb", "codex-delta-kb"))
    assert "`docs/data/semaine/`, `docs/data/recherche.json`, `state/claude.json`" in (RACINE / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`docs/data/recherche.json`" in (RACINE / "AGENTS.md").read_text(encoding="utf-8")
    spec = (RACINE / "SPEC.md").read_text(encoding="utf-8")
    assert "`docs/data/semaine/`, `docs/data/recherche.json`, `state/claude.json`" in spec and "| D114 |" in spec and "recherche.py" in spec
