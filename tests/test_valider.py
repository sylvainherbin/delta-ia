"""D13 (--valider piloté par le fichier quotidien) et D15 (scripts/valider.py) sur des fichiers synthétiques."""

import copy
import datetime
import hashlib
import json

import pytest

import fetch
import valider as v
from conftest import FauxClient, ecrire_quotidien, element_depuis_brut

JOUR = __import__("datetime").date.today().isoformat()
CONTEXTE = ("## 2. Projets\n<!-- ctx-id: projets -->\n\n### 2.1 carnet — PWA\n<!-- ctx-id: projet.carnet -->\n\n"
            "### 2.2 trading-sim — robot\n<!-- ctx-id: projet.trading-sim -->\n\nrobot\n\n"
            "### 2.3 chatgpt-trading-sim — espace\n<!-- ctx-id: projet.chatgpt-trading-sim -->\n<!-- ctx-id-deprecie: projet.ancien -->\n")


@pytest.fixture
def racine(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir(); (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    return tmp_path


_BRUTS: dict[str, str] = {}  # D87 : le brut d'un périmètre (échantillons figés, état vide) se calcule une fois par processus


def brut_de(racine, perimetre):
    chemin = racine / "raw" / f"{perimetre}-nouveautes.json"
    if perimetre not in _BRUTS:
        fetch.main(["--racine", str(racine), "--perimetre", perimetre])
        _BRUTS[perimetre] = chemin.read_text()
    chemin.write_text(_BRUTS[perimetre])
    return json.loads(_BRUTS[perimetre])


def lire_etat(racine, p):
    return json.loads((racine / "state" / f"{p}.json").read_text())


def validation(racine, perimetre, brut=True, jour=JOUR):
    args = ["--racine", str(racine), "--perimetre", perimetre, "--contexte", str(racine / "CONTEXTE.md"), "--date", jour]
    if brut:
        args += ["--brut", str(racine / "raw" / f"{perimetre}-nouveautes.json")]
    return v.main(args)


# --- D13 : fetch.py --valider -----------------------------------------------------------------------------------

def test_valider_partiel_laisse_les_autres_en_attente(racine, capsys):
    brut = brut_de(racine, "claude")
    ids = [n["id"] for n in brut["nouveautes"]]
    assert len(ids) >= 3
    couverts, ecarte = ids[:2], ids[2]
    ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=couverts, ecarter=[ecarte])
    code = fetch.main(["--racine", str(racine), "--perimetre", "claude", "--valider"])
    assert code == 4
    sortie = capsys.readouterr().out
    etat = lire_etat(racine, "claude")
    assert set(couverts) <= set(etat["vus"]) and ecarte in etat["vus"] and etat["vus"][ecarte]["ecarte"] is True
    en_attente = [i for i in ids if i not in etat["vus"]]
    assert en_attente == ids[3:] and all(i in sortie for i in en_attente) and "en attente" in sortie
    # la relance ne remonte que ce qui reste en attente
    fetch.main(["--racine", str(racine), "--perimetre", "claude"])
    brut2 = json.loads((racine / "raw" / "claude-nouveautes.json").read_text())
    assert sorted(n["id"] for n in brut2["nouveautes"]) == sorted(en_attente)
    # tout couvert : code 0
    ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=ids[:2] + ids[3:], ecarter=[ecarte])
    assert fetch.main(["--racine", str(racine), "--perimetre", "claude", "--valider"]) == 0


def test_valider_inscrit_les_ids_web_et_signale_les_inconnus(racine, capsys):
    brut = brut_de(racine, "openai")
    from deltalib.modeles import id_web
    web = {"id": id_web("https://help.openai.com/x", None, "Note ChatGPT"), "produit": "chatgpt", "titre": "Note ChatGPT",
           "version": None, "date_publication": None, "url": "https://help.openai.com/x", "officielle": False}
    e_web = element_depuis_brut(web)
    e_inconnu = element_depuis_brut({**web, "id": "oa-codex/inexistant", "url": "https://x.test"})
    ecrire_quotidien(racine, "openai", brut, JOUR, extra_elements=[e_web, e_inconnu])
    assert fetch.main(["--racine", str(racine), "--perimetre", "openai", "--valider"]) == 4
    etat = lire_etat(racine, "openai")
    assert etat["vus"][web["id"]]["source_id"] == "web" and "oa-codex/inexistant" not in etat["vus"]
    assert "inconnu" in capsys.readouterr().out


def test_valider_date_explicite(racine):
    brut = brut_de(racine, "actu")
    ecrire_quotidien(racine, "actu", brut, "2026-09-20")
    assert fetch.main(["--racine", str(racine), "--perimetre", "actu", "--valider"]) == 2  # pas de fichier du jour
    assert fetch.main(["--racine", str(racine), "--perimetre", "actu", "--valider", "--date", "2026-09-20"]) == 0


# --- D15 : valider.py ---------------------------------------------------------------------------------------------

def test_valider_py_fichier_valide(racine, capsys):
    brut = brut_de(racine, "claude")
    ids = [n["id"] for n in brut["nouveautes"]]
    ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=ids[1:], ecarter=[ids[0]])
    assert validation(racine, "claude") == 0
    assert "valide" in capsys.readouterr().out


def test_valider_py_couverture_du_brut(racine, capsys):
    brut = brut_de(racine, "claude")
    ids = [n["id"] for n in brut["nouveautes"]]
    ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=ids[1:])
    assert validation(racine, "claude") == 1
    err = capsys.readouterr().err
    assert "ni reprise dans `ids_bruts` ni dans `ecartes`" in err and ids[0] in err
    assert validation(racine, "claude", brut=False) == 0  # sans --brut, la couverture n'est pas exigée


def test_projets_du_contexte(racine):
    assert v.projets_du_contexte(racine / "CONTEXTE.md") == {"carnet", "trading-sim", "chatgpt-trading-sim"}


def test_projets_du_contexte_depot_reel():
    """Dépôt réel : le CONTEXTE.md courant déclare au moins un projet."""
    from pathlib import Path
    assert v.projets_du_contexte(Path(fetch.RACINE) / "CONTEXTE.md")


def test_projets_du_contexte_reel():
    from pathlib import Path
    assert v.projets_du_contexte(Path(fetch.RACINE) / "CONTEXTE.md") == {
        "carnet", "trading-sim", "chatgpt-trading-sim", "ceramist", "restoration-id",
        "discipline", "delta-desktop", "veille-shopify", "marketing", "experimentations"}


def test_projets_formats_varies_et_niveau_2(tmp_path):
    c = tmp_path / "CONTEXTE.md"
    c.write_text("## Projets\n<!-- ctx-id: projets -->\n\n### 1.1 atelier-resa (client)\n<!-- ctx-id: projet.atelier-resa -->\n\n"
                 "### Mon projet\n<!-- ctx-id: projet.mon-projet -->\n\n## Vue\n<!-- ctx-id: projet.vue-ensemble -->\n\n"
                 "### Autre\n<!-- ctx-id: outils.autre -->\n", encoding="utf-8")
    assert v.projets_du_contexte(c) == {"atelier-resa", "mon-projet"}


def test_contexte_sans_projet_valide(tmp_path):
    c = tmp_path / "CONTEXTE.md"
    c.write_text("## Moi\n<!-- ctx-id: moi -->\n\n### Outils\n<!-- ctx-id: outils -->\n", encoding="utf-8")
    assert v.projets_du_contexte(c) == set()
    r = v.Rapport()
    v.charger_ctx_ids(tmp_path, r)
    assert r.ok


def test_contexte_sans_projet_bout_en_bout(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    for e in q["elements"]:
        e.update(projets_concernes=[], contexte_sections={})
    _reecrire(chemin, q)
    (racine / "CONTEXTE.md").write_text("## Moi\n<!-- ctx-id: moi -->\n\ntexte\n", encoding="utf-8")
    assert validation(racine, "claude", brut=False) == 0
    assert "aucun projet" not in capsys.readouterr().err
    q["elements"][0]["projets_concernes"] = ["projet-fantome"]
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    assert "hors de CONTEXTE.md" in capsys.readouterr().err


def _quotidien_valide(racine, perimetre="claude"):
    brut = brut_de(racine, perimetre)
    chemin = ecrire_quotidien(racine, perimetre, brut, JOUR)
    return chemin, json.loads(chemin.read_text())


def _reecrire(chemin, q):
    chemin.write_text(json.dumps(q, ensure_ascii=False))


CAS_INVALIDES = {
    "impact nul avec pour_toi": (lambda e: e.update(impact="nul", pour_toi="quelque chose"), "`pour_toi` doit être null"),
    "impact fort sans pour_toi": (lambda e: e.update(impact="fort", pour_toi=None), "`pour_toi` doit être renseigné"),
    "certitude officiel sans source officielle": (lambda e: (e.update(certitude="officiel"), e["sources"][0].update(officielle=False)), "exige au moins une source `officielle: true`"),
    "sans source": (lambda e: e.update(sources=[]), "au moins une source"),
    "effort hors énumération": (lambda e: e.update(action={"description": "d", "etapes": ["x"], "effort": "1h"}), "`action.effort`"),
    "projet inconnu": (lambda e: e.update(projets_concernes=["projet-fantome"]), "hors de CONTEXTE.md §2"),
    "date mal formée": (lambda e: e.update(date_publication="22/09/2026"), "`date_publication`"),
    "type inconnu": (lambda e: e.update(type="rumeur"), "`type` inconnu"),
    "ids_bruts vide": (lambda e: e.update(ids_bruts=[]), "`ids_bruts`"),
    "id différent du premier id brut": (lambda e: e.update(id="autre"), "doit être le premier de `ids_bruts`"),
    "champ inconnu": (lambda e: e.update(bonus=1), "champs inconnus"),
    "produit hors périmètre": (lambda e: e.update(produit="codex"), "hors du périmètre"),
    "web- mal formé": (lambda e: e.update(id="web-abc", ids_bruts=["web-abc"]), "12 premiers hexadécimaux"),
}


@pytest.mark.parametrize("cas", list(CAS_INVALIDES))
def test_valider_py_element_invalide(racine, capsys, cas):
    chemin, q = _quotidien_valide(racine)
    modif, attendu = CAS_INVALIDES[cas]
    modif(q["elements"][0])
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    assert attendu in capsys.readouterr().err


def test_valider_py_identifiants_uniques(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    q["elements"].append(copy.deepcopy(q["elements"][0]))
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    err = capsys.readouterr().err
    assert "identifiant d'élément en double" in err and "identifiant brut présent dans deux éléments" in err
    chemin, q = _quotidien_valide(racine)
    q["ecartes"].append({"id": q["elements"][0]["id"], "raison": "test"})
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    assert "à la fois écarté et repris" in capsys.readouterr().err


@pytest.mark.parametrize("texte, libelle", [
    ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "ghp_"),
    ("github_pat_abcdefghijklmnopqrstuvwxyz0123", "github_pat_"),
    ("sk-abcdefghijklmnopqrstuv", "sk-"),
    ("AKIAABCDEFGHIJKLMNOP", "AKIA"),
    ("-----BEGIN RSA PRIVATE KEY-----", "-----BEGIN"),
    ("https://exemple.test/api?access_token=abc123", "token"),
    ("https://exemple.test/api?api_key=abc123", "key"),
    ("https://exemple.test/x?client_secret=abc", "secret"),
])
def test_valider_py_secrets(racine, capsys, texte, libelle):
    chemin, q = _quotidien_valide(racine)
    q["synthese"] = f"Synthèse avec {texte} dedans."
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    assert "secret possible" in capsys.readouterr().err


def test_valider_py_fichier_et_index(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    # champs de tête
    for champ, valeur, attendu in [("agent", "codex", "`agent`"), ("perimetre", "actu", "`perimetre`"), ("synthese", "", "`synthese` vide"),
                                   ("date", "2026-01-01", "égale au nom du fichier")]:
        q2 = copy.deepcopy(q); q2[champ] = valeur; _reecrire(chemin, q2)
        assert validation(racine, "claude", brut=False) == 1
        assert attendu in capsys.readouterr().err
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 0
    # index incohérent
    idx_chemin = racine / "docs" / "data" / "claude" / "index.json"
    idx = json.loads(idx_chemin.read_text())
    idx["jours"][0]["impact"]["fort"] += 1
    idx_chemin.write_text(json.dumps(idx))
    assert validation(racine, "claude", brut=False) == 1
    assert "`impact`" in capsys.readouterr().err
    idx_chemin.unlink()
    assert validation(racine, "claude", brut=False) == 1
    assert "index.json: absent" in capsys.readouterr().err


def test_valider_py_ecartes_et_nul_distincts(racine):
    """D14 : un élément `impact: nul` est valide et affiché ; `ecartes` est une liste séparée."""
    brut = brut_de(racine, "claude")
    ids = [n["id"] for n in brut["nouveautes"]]
    chemin = ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=ids[1:], ecarter=[ids[0]])
    q = json.loads(chemin.read_text())
    q["elements"][0].update(impact="nul", pour_toi=None, projets_concernes=[])
    _reecrire(chemin, q)
    idx = racine / "docs" / "data" / "claude" / "index.json"
    d = json.loads(idx.read_text()); d["jours"][0]["impact"]["nul"] += 1; d["jours"][0]["impact"]["faible"] -= 1; idx.write_text(json.dumps(d))
    assert validation(racine, "claude") == 0


def test_skill_codex_et_prompt_identiques():
    from pathlib import Path
    racine = Path(fetch.RACINE)
    skill = (racine / ".agents" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    prompt = (racine / "prompts" / "codex-delta.md").read_text(encoding="utf-8")
    corps = skill.split("---\n", 2)[2].lstrip("\n")
    assert corps == prompt, "le SKILL.md Codex et prompts/codex-delta.md doivent rester identiques"
    assert skill.startswith("---\nname: delta\n")
    cc = (racine / ".claude" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in cc.split("---\n", 2)[1]


def test_id_web_d20():
    from deltalib.modeles import id_web, normaliser_titre
    url = "https://help.openai.com/en/articles/6825453-chatgpt-release-notes"
    a = id_web(url, "2026-09-22", "Mémoire améliorée !")
    b = id_web(url, "2026-09-22", "memoire amelioree")
    assert a == b and a == "web-" + hashlib.sha1(f"{url}|2026-09-22|memoire amelioree".encode()).hexdigest()[:12]
    assert id_web(url, "2026-09-22", "Autre entrée") != a, "deux entrées d'une même page ne doivent pas entrer en collision"
    assert id_web(url, None, "x") == id_web(url, "", "x") != id_web(url, "2026-09-22", "x")
    assert normaliser_titre("Éléphant, GPT-6 !") == "elephant gpt 6"
    assert __import__("re").fullmatch(r"web-[0-9a-f]{12}", a)


def test_d58_contexte_empreinte(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    assert validation(racine, "claude", brut=False) == 0
    q["contexte_empreinte"] = "pas-un-sha1"; _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    assert "`contexte_empreinte` doit être le sha1" in capsys.readouterr().err
    # après le 23/09, l'absence est une erreur ; le 23/09, elle est tolérée
    q.pop("contexte_empreinte")
    ancien = racine / "docs" / "data" / "claude" / "2026-09-23.json"
    recent = racine / "docs" / "data" / "claude" / "2026-09-24.json"
    chemin.unlink()
    for f, d in ((ancien, "2026-09-23"), (recent, "2026-09-24")):
        f.write_text(json.dumps({**q, "date": d}, ensure_ascii=False))
    import valider as v
    r = v.Rapport()
    v.verifier_quotidien(ancien, "claude", {"carnet", "trading-sim", "chatgpt-trading-sim"}, r)
    assert r.ok, r.erreurs
    v.verifier_quotidien(recent, "claude", {"carnet", "trading-sim", "chatgpt-trading-sim"}, r)
    assert any("D58" in e for e in r.erreurs)


def test_d64bis_contexte_sections_des_elements(racine, capsys):
    import valider as v
    chemin, q = _quotidien_valide(racine)
    q["contexte_empreinte"] = "0" * 40
    projets = {"carnet", "trading-sim", "chatgpt-trading-sim"}
    f24 = racine / "docs" / "data" / "claude" / "2026-09-24.json"
    f25 = racine / "docs" / "data" / "claude" / "2026-09-25.json"
    v.charger_ctx_ids(racine, v.Rapport())

    def verifier(f, elements_cs=None, date_="2026-09-25"):
        d = copy.deepcopy(q)
        for e in d["elements"]:
            if elements_cs is None:
                e.pop("contexte_sections", None)
            else:
                e["contexte_sections"] = elements_cs
        f.write_text(json.dumps({**d, "date": date_}, ensure_ascii=False))
        r = v.Rapport(); v.verifier_quotidien(f, "claude", projets, r)
        return r.erreurs

    assert verifier(f24, date_="2026-09-24") == [], "jusqu'au 24/09, champ facultatif"
    assert any("D64" in e for e in verifier(f25)), "après le 24/09, obligatoire"
    ok = {"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "Le robot tourne sous tmux."}}
    assert verifier(f25, ok) == [] and verifier(f25, {}) == []
    assert any("ctx-id inconnu" in e for e in verifier(f25, {"2.2": {"sha1": "a" * 40, "pourquoi": "x"}}))
    assert any("`pourquoi` vide" in e for e in verifier(f25, {"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": " "}}))
    assert any("160" in e for e in verifier(f25, {"projet.trading-sim": {"sha1": "a" * 40, "pourquoi": "x" * 161}}))
    assert any("{sha1, pourquoi}" in e for e in verifier(f25, {"projet.trading-sim": "a" * 40})), "format de ae895e6 refusé"
    assert verifier(f25, {"projet.ancien": {"sha1": "a" * 40, "pourquoi": "x"}}) == [], "un ctx-id déprécié reste connu"
    vide = hashlib.sha1(b"").hexdigest()
    assert any("corps vide" in e for e in verifier(f25, {"projets": {"sha1": vide, "pourquoi": "Liste des projets."}}))
    assert v.analyser_contexte(CONTEXTE)[0]["projets"]["sha1"] == vide


# --- Audit du 25/09, point 2 : la borne D4 n'avance qu'avec une couverture complète -----------------------------

def test_borne_n_avance_pas_si_couverture_incomplete(racine, capsys):
    from deltalib import etat as mod_etat
    brut = brut_de(racine, "claude")
    ids = [n["id"] for n in brut["nouveautes"]]
    # premier passage complet : la borne est posée
    ecrire_quotidien(racine, "claude", brut, JOUR)
    assert fetch.main(["--racine", str(racine), "--perimetre", "claude", "--valider"]) == 0
    borne = lire_etat(racine, "claude")["maj_le"]
    assert borne
    # validation partielle (nouveautés en attente) : inscriptions faites, borne inchangée
    brut2 = {**brut, "nouveautes": [{**n, "id": n["id"] + "-bis"} for n in brut["nouveautes"]], "ignores": []}
    e, bilan = mod_etat.valider(lire_etat(racine, "claude"),
                                brut2, {"elements": [element_depuis_brut(brut2["nouveautes"][0])], "ecartes": []})
    assert bilan["en_attente"] and not bilan["borne_avancee"] and e["maj_le"] == borne
    assert brut2["nouveautes"][0]["id"] in e["vus"], "le reste de la validation s'applique"
    # identifiant inconnu : borne inchangée aussi
    e, bilan = mod_etat.valider(lire_etat(racine, "claude"), {"nouveautes": []},
                                {"elements": [element_depuis_brut({**brut["nouveautes"][0], "id": "inconnu-x"})], "ecartes": []})
    assert bilan["inconnus"] == ["inconnu-x"] and e["maj_le"] == borne
    # état neuf et couverture incomplète : pas de borne inventée
    e, bilan = mod_etat.valider({"vus": {}}, brut, {"elements": [], "ecartes": []})
    assert e["maj_le"] is None and bilan["en_attente"] == sorted(ids)


def test_borne_inchangee_de_bout_en_bout(racine, capsys):
    brut = brut_de(racine, "claude")
    ids = [n["id"] for n in brut["nouveautes"]]
    ecrire_quotidien(racine, "claude", brut, JOUR, couvrir=ids[:1])
    assert fetch.main(["--racine", str(racine), "--perimetre", "claude", "--valider"]) == 4
    assert lire_etat(racine, "claude")["maj_le"] is None and "borne (maj_le) inchangée" in capsys.readouterr().out
    ecrire_quotidien(racine, "claude", brut, JOUR)
    assert fetch.main(["--racine", str(racine), "--perimetre", "claude", "--valider"]) == 0
    assert lire_etat(racine, "claude")["maj_le"]


# --- Audit du 25/09, point 6 : identifiants web- recalculés (D20) ------------------------------------------------

def test_id_web_recalcule_dans_les_nouveaux_fichiers(racine):
    import valider as v
    from deltalib.modeles import id_web
    url, titre, date_pub = "https://help.openai.com/x", "Note ChatGPT", "2026-09-24"
    bon = id_web(url, date_pub, titre)
    base = {"id": bon, "ids_bruts": [bon], "titre": titre, "date_publication": date_pub,
            "sources": [{"url": "https://autre.test/y", "libelle": "l", "officielle": False}, {"url": url, "libelle": "l", "officielle": False}]}

    def erreurs(e):
        r = v.Rapport(); v.verifier_ids_web(e, "x", r); return r.erreurs
    assert erreurs(base) == [], "l'URL de n'importe quelle source convient"
    assert any("id_web" in m for m in erreurs({**base, "titre": "Titre changé"})), "titre modifié après calcul"
    assert any("id_web" in m for m in erreurs({**base, "date_publication": None}))
    faux = "web-" + "0" * 12
    assert any(faux in m for m in erreurs({**base, "id": faux, "ids_bruts": [faux, bon]}))
    assert erreurs({**base, "sources": []}) == [], "sans URL, rien n'est vérifié"
    assert erreurs({**base, "ids_bruts": ["oa-1"], "id": "oa-1"}) == []


def test_id_web_historique_non_verifie():
    """Les 6 identifiants web- du 23/09 ne se recalculent pas (titre de calcul absent de l'élément) : non vérifiés."""
    import valider as v
    assert v.DATE_ID_WEB == "2026-09-25"
    from conftest import RACINE
    r = v.Rapport()
    v.verifier_quotidien(RACINE / "docs" / "data" / "openai" / "2026-09-23.json", "openai",
                         {"carnet", "trading-sim", "chatgpt-trading-sim", "ceramist", "restoration-id"}, r)
    assert not any("id_web" in m for m in r.erreurs)


def test_section_disparue_toleree_dans_les_anciens_fichiers_du_jour(racine, capsys):
    """D58 et D64-bis amendées le 29/09/2026 : un ancien fichier du jour qui cite une section retirée de CONTEXTE.md
    ne bloque plus le passage suivant ; le fichier du jour (--date) garde le refus strict."""
    chemin, q = _quotidien_valide(racine)
    disparue = {"projet.disparu": {"sha1": "a" * 40, "pourquoi": "Section retirée depuis de CONTEXTE.md."}}
    ancien = copy.deepcopy(q)
    ancien["date"] = "2026-09-01"
    for e in ancien["elements"]:
        e["contexte_sections"] = disparue
    (chemin.parent / "2026-09-01.json").write_text(json.dumps(ancien, ensure_ascii=False))
    chemin, q = _quotidien_valide(racine)  # réécrit le fichier du jour et l'index, qui couvre maintenant 2026-09-01
    capsys.readouterr()
    assert validation(racine, "claude", brut=False) == 0, capsys.readouterr()
    for e in q["elements"]:
        e["contexte_sections"] = disparue
    _reecrire(chemin, q)
    capsys.readouterr()
    assert validation(racine, "claude", brut=False) != 0, "le fichier du jour garde le refus strict"
    err = capsys.readouterr().err
    assert f"{JOUR}.json" in err and "ctx-id inconnu" in err and "2026-09-01.json" not in err


def test_projet_retire_tolere_dans_les_anciens_fichiers_du_jour(racine, capsys):
    """29/09/2026 : un ancien fichier du jour qui cite un projet retiré de CONTEXTE.md §2 ne bloque plus le passage
    suivant ; le fichier du jour garde le refus strict."""
    chemin, q = _quotidien_valide(racine)
    ancien = copy.deepcopy(q)
    ancien["date"] = "2026-09-01"
    for e in ancien["elements"]:
        e["projets_concernes"] = ["projet-retire"]
    (chemin.parent / "2026-09-01.json").write_text(json.dumps(ancien, ensure_ascii=False))
    chemin, q = _quotidien_valide(racine)  # réécrit le fichier du jour et l'index, qui couvre maintenant 2026-09-01
    capsys.readouterr()
    assert validation(racine, "claude", brut=False) == 0, capsys.readouterr()
    for e in q["elements"]:
        e["projets_concernes"] = ["projet-retire"]
    _reecrire(chemin, q)
    capsys.readouterr()
    assert validation(racine, "claude", brut=False) != 0, "le fichier du jour garde le refus strict"
    err = capsys.readouterr().err
    assert f"{JOUR}.json" in err and "hors de CONTEXTE.md §2" in err and "2026-09-01.json" not in err


def test_skills_sans_stop_sur_regle_ambigue_ni_avant_de_lancer():
    from pathlib import Path
    racine = Path(fetch.RACINE)
    for chemin in (".claude/skills/delta/SKILL.md", ".agents/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md",
                   ".agents/skills/delta-kb/SKILL.md", "prompts/codex-delta.md", "prompts/codex-delta-kb.md"):
        t = (racine / chemin).read_text(encoding="utf-8")
        assert "Avant de lancer" not in t, chemin
        assert "règle ambiguë du dépôt ou un fichier inattendu" in t and "ne l'arrête pas" in t, chemin
        assert "à soumettre à Sylvain" not in t, chemin


# --- D86 : identifiants kb-<id d'entrée de la base> ----------------------------------------------------------------

def test_kb_id_accepte_dans_etat_si_entree_connue(tmp_path):
    from deltalib.etat import valider as valider_etat, ids_base
    kb = tmp_path / "docs" / "data" / "kb" / "claude"
    kb.mkdir(parents=True)
    (kb / "parametres.json").write_text(json.dumps({"entrees": [{"id": "param-x"}]}), encoding="utf-8")
    assert ids_base(tmp_path, "claude") == {"param-x"}
    assert ids_base(tmp_path, "actu") == {"param-x"}
    brut = {"perimetre": "claude", "nouveautes": []}
    quotidien = {"elements": [{"id": "kb-param-x", "ids_bruts": ["kb-param-x"]},
                              {"id": "kb-absente", "ids_bruts": ["kb-absente"]},
                              {"id": "web-" + "a" * 12, "ids_bruts": ["web-" + "a" * 12]}]}
    etat, bilan = valider_etat({}, brut, quotidien, ids_kb=ids_base(tmp_path, "claude"))
    assert "kb-param-x" in etat["vus"] and etat["vus"]["kb-param-x"]["source_id"] == "kb"
    assert "kb-absente" not in etat["vus"] and bilan["inconnus"] == ["kb-absente"]
    assert etat["vus"]["web-" + "a" * 12]["source_id"] == "web"
    _, sans_base = valider_etat({}, brut, {"elements": [{"id": "kb-param-x", "ids_bruts": ["kb-param-x"]}]})
    assert sans_base["inconnus"] == ["kb-param-x"]


def test_kb_id_verifie_par_valider_py():
    import valider as v

    def erreurs(e, connus):
        r = v.Rapport(); v.verifier_ids_kb(e, "x", r, connus); return r.erreurs
    e = {"id": "kb-param-x", "ids_bruts": ["kb-param-x"], "kb_refs": ["param-x"]}
    assert erreurs(e, {"param-x"}) == []
    assert any("inconnue" in m for m in erreurs(e, {"autre"}))
    assert any("kb_refs" in m for m in erreurs({**e, "kb_refs": []}, {"param-x"}))
    assert erreurs({"id": "oa-1", "ids_bruts": ["oa-1"], "kb_refs": []}, {"param-x"}) == []

# --- D85 : avertissements R1 (commande exacte) et R5 (date absolue D71), jamais bloquants ---------------------------

def _action(texte, etapes=("Fais-le.",)):
    return {"description": texte, "etapes": list(etapes), "effort": "5min"}


def _element_d85(**champs):
    """Élément neutre (ni D71 ni ajout) : chaque test ne change que ce qu'il éprouve."""
    n = {"id": "fx-1", "produit": "claude-code", "titre": "Commande /foo", "version": None, "date_publication": None,
         "url": "https://example.org/x", "officielle": True}
    e = element_depuis_brut(n, impact="faible")
    e.update(champs)
    return e


def _avert(**champs):
    r = v.Rapport()
    v.avertir_element(_element_d85(**champs), 0, r, "x.json")
    return r.avertissements


def test_r1_ajout_sans_commande_avertit():
    for action in (None, _action("Essayer la nouveauté si tu veux.", ["Vérifier."])):
        avert = _avert(type="nouveaute", action=action)
        assert len(avert) == 2 and all("R1" in a and "elements[0] (fx-1)" in a for a in avert)
        assert "sans commande exacte" in avert[0] and "résultat attendu" in avert[1]
    assert len(_avert(type="amelioration", produit="codex", impact="fort", action=None)) == 2


def test_r1_commande_entre_accents_graves_dans_description_ou_etapes():
    assert _avert(type="nouveaute", action=_action("Lance `/plugin enable x@builtin` ; résultat attendu : le plugin est actif.", ["Regarde."])) == []
    assert _avert(type="nouveaute", action=_action("Essaie.", ["Tape `claude purge --help` ; attendu : la liste des options."])) == []
    sans_attendu = _avert(type="nouveaute", action=_action("Lance `/plugin enable x@builtin`.", ["Regarde."]))
    assert len(sans_attendu) == 1 and "résultat attendu" in sans_attendu[0]


@pytest.mark.parametrize("champs", [
    {"type": "correction"}, {"type": "depreciation"}, {"type": "changement_rupture"},
    {"impact": "nul", "pour_toi": None}, {"produit": "actu"},
], ids=["correction", "depreciation", "rupture", "impact-nul", "produit-actu"])
def test_r1_hors_champ_pas_d_avertissement(champs):
    assert _avert(**{"type": "nouveaute", "action": None, **champs}) == []


# --- D107 : R1 complété (projet ou flux nommé, « résultat attendu ») ------------------------------------------------

ANCRAGE_R1 = {"projets": {"delta ia", "discipline"}, "sections": {"flux.passage": {"passage quotidien", "dev delta"}}}


def _avert_ancre(**champs):
    r = v.Rapport()
    v.avertir_element(_element_d85(**{"pour_toi": None, **champs}), 0, r, "x.json", ANCRAGE_R1)
    return r.avertissements


def test_r1_action_en_trois_parties_sans_avertissement():
    action = _action("Ajoute `subagentStatusLine` dans `~/.claude/settings.json`.",
                     ["Essai : lance deux sous-agents dans le projet delta-ia ; résultat attendu : `agentType` apparaît."])
    assert _avert_ancre(type="nouveaute", action=action, contexte_sections={}) == []


def test_r1_sans_projet_ni_flux_nomme_avertit():
    action = _action("Tape `/foo`.", ["Résultat attendu : ça marche."])
    avert = _avert_ancre(type="nouveaute", action=action, contexte_sections={})
    assert len(avert) == 1 and "sans projet ni flux de CONTEXTE.md nommé" in avert[0]


def test_r1_flux_nomme_par_section_citee():
    action = _action("Tape `/foo` pendant le passage quotidien.", ["Résultat attendu : ça marche."])
    assert len(_avert_ancre(type="nouveaute", action=action, contexte_sections={})) == 1
    assert _avert_ancre(type="nouveaute", action=action, contexte_sections={"flux.passage": "x"}) == []


def test_r1_sans_resultat_attendu_avertit_meme_ancre():
    action = _action("Tape `/foo` dans delta-ia.", ["Regarde."])
    avert = _avert_ancre(type="nouveaute", action=action, contexte_sections={})
    assert len(avert) == 1 and "résultat attendu" in avert[0]


def test_r1_sans_ancrage_pas_de_controle_du_projet():
    action = _action("Tape `/foo`.", ["Résultat attendu : ça marche."])
    assert _avert(type="nouveaute", action=action) == []


def test_r1_nouveaux_controles_hors_champ():
    for champs in ({"type": "correction"}, {"type": "depreciation"}, {"produit": "actu"}, {"impact": "nul", "pour_toi": None}):
        avert = _avert_ancre(**{"type": "nouveaute", "action": None, "pour_toi": None, **champs})
        assert not [a for a in avert if "R1" in a], champs


def test_r1_texte_des_trois_regles_identique_et_cite_la_base():
    from pathlib import Path
    racine = Path(fetch.RACINE)
    lignes = []
    for f in (".claude/skills/delta/SKILL.md", ".agents/skills/delta/SKILL.md", "prompts/codex-delta.md"):
        ligne = next(l for l in (racine / f).read_text(encoding="utf-8").splitlines() if "**R1 (D85" in l)
        lignes.append(ligne.strip())
        for attendu in ("docs/data/kb/noms.json", "`usage`", "`exemple`", "`kb_refs`", "résultat attendu", "subagentStatusLine"):
            assert attendu in ligne, f"{f} : {attendu} absent de R1"
    assert len(set(lignes)) == 1, "les trois textes de R1 doivent être identiques"


def test_r5_d71_sans_date_avertit_avec_date_non():
    d71 = {"titre": "Hausse des tarifs et des limites d'usage", "type": "correction", "impact": "fort"}
    for action in (None, _action("Avant la fin du mois, vérifie.", ["Ouvre Paramètres > Utilisation."])):
        avert = _avert(**d71, action=action)
        assert len(avert) == 1 and "R5" in avert[0]
    for date_ in ("2026-10-12", "12/10"):
        assert _avert(**d71, action=_action(f"Avant le {date_}, ouvre Paramètres > Utilisation.")) == []


def test_r5_titre_ou_resume_seuls_decident_pas_pour_toi():
    assert _avert(type="correction", pour_toi="Regarde Paramètres > Utilisation et tes crédits.", action=None) == []
    assert len(_avert(type="correction", resume="Les limites de débit (rate limit) changent.", action=None)) == 1


def test_avertissements_de_bout_en_bout_sans_changer_le_code(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    q["elements"][0].update(type="nouveaute", action=None)
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 0
    sortie = capsys.readouterr()
    assert "valide" in sortie.out
    assert any(l.startswith("! AVERTISSEMENT 2026-") and "R1" in l for l in sortie.out.splitlines())


def test_avertissements_accompagnent_une_erreur_sans_la_masquer(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    q["elements"][0].update(type="nouveaute", action=None, projets_concernes=["projet-fantome"])
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 1
    sortie = capsys.readouterr()
    assert "hors de CONTEXTE.md" in sortie.err and "! AVERTISSEMENT" in sortie.out


def test_regles_pour_toi_r1_a_r5_dans_les_trois_textes():
    from pathlib import Path
    racine = Path(fetch.RACINE)
    for f in (".claude/skills/delta/SKILL.md", ".agents/skills/delta/SKILL.md", "prompts/codex-delta.md"):
        texte = (racine / f).read_text(encoding="utf-8")
        for r in ("R1", "R2", "R3", "R4", "R5"):
            assert f"**{r} (D85" in texte, f"{f} : règle {r} absente (D85)"


def test_r5_disponibilite_sur_tous_les_forfaits_n_est_pas_d71():
    """Élément Google Workspace du 08/10 (titre réduit) : « forfaits payants » dit où la fonction est disponible."""
    gw = {"titre": "Claude pour Google Workspace en bêta publique sur tous les forfaits payants, avec des connecteurs",
          "resume": "Disponible pour les forfaits payants ; un module complémentaire ouvre Claude dans Google Docs.",
          "type": "correction", "action": None}
    assert _avert(**gw) == []


def test_r5_credits_api_mensuels_restent_detectes():
    """Élément D71 du 08/10 (titre réduit) : « crédits » et « forfaits Max » restent un sujet de compte."""
    d71 = {"titre": "Crédits API mensuels inclus dans Max et Team : 100 $ (Max 5x), 200 $ (Max 20x)",
           "resume": "Les forfaits Max et Team incluent des crédits mensuels pour l'API Claude.",
           "type": "correction", "action": None}
    avert = _avert(**d71)
    assert len(avert) == 1 and "R5" in avert[0]
    assert _avert(**{**d71, "titre": "Hausse des tarifs sur tous les forfaits"}) != []


# --- R4 (D96) : `pour_toi` conditionnel sans commande qui le tranche, `pour_toi` recopié d'un jour à l'autre ---------

@pytest.mark.parametrize("pour_toi", [
    "Si tu utilises ce réglage, il change ta session.", "SI TU veux l'essayer, ouvre un projet.",
    "Si vous activez les crédits, la facture suit.", "À activer au cas où ta limite saute.",
    "Tu peux éventuellement l'essayer.",
])
def test_r4_conditionnel_sans_commande_avertit(pour_toi):
    for action in (None, _action("Essaie dans un projet.", ["Vérifie."])):
        avert = _avert_r4(pour_toi=pour_toi, action=action)
        assert len(avert) == 1 and "R4" in avert[0] and "conditionnel" in avert[0] and "elements[0] (fx-1)" in avert[0]


def _avert_r4(**champs):
    return [a for a in _avert(**champs) if "R4" in a]


def test_r4_conditionnel_avec_commande_dans_action_pas_d_avertissement():
    pour_toi = "Si tu utilises encore l'ancien réglage, il saute."
    assert _avert_r4(pour_toi=pour_toi, action=_action("Lance `claude config list`.")) == []
    assert _avert_r4(pour_toi=pour_toi, action=_action("Vérifie.", ["Tape `grep ancien ~/.claude/settings.json`."])) == []


@pytest.mark.parametrize("pour_toi", [
    None, "", "Ton projet trading-sim lance ce flux chaque nuit.", "Aussi tu gagnes du temps.",
    "Tu changes de modèle ; sinon rien ne bouge.", "Un suivi des si tuiles n'est pas une condition.",
], ids=["null", "vide", "constat", "aussi-tu", "sinon", "mot-voisin"])
def test_r4_pas_de_conditionnel_pas_d_avertissement(pour_toi):
    assert _avert_r4(pour_toi=pour_toi, action=None) == []


def test_r4_conditionnel_ignore_un_element_nul():
    assert _avert_r4(impact="nul", pour_toi="Si tu veux.", action=None) == []


def test_r4_normalisation_casse_espaces_ponctuation():
    assert v.normaliser_texte("  Ta LIMITE,  est à\n83 % !  ") == v.normaliser_texte("ta limite est à 83")
    assert v.normaliser_texte("Ta limite est à 83 %") != v.normaliser_texte("Ta limite est à 92 %")


def _jours(**par_jour):
    """{'2026-10-05': [(id, pour_toi), ...]} -> quotidiens minimaux."""
    return {j: {"elements": [{"id": i, "pour_toi": p, "impact": "moyen"} for i, p in els]} for j, els in par_jour.items()}


def test_r4_recopie_identique_apres_normalisation():
    q = _jours(**{"2026-10-05": [("a", "Ta limite est à 83 %.")], "2026-10-08": [("a", "ta limite est  à 83 %")]})
    trouves = v.recopies_pour_toi(q, "2026-10-08")
    assert [(i, e["id"], d) for i, e, d in trouves] == [(0, "a", "2026-10-05")]
    r = v.Rapport()
    v.avertir_recopies(q, r)
    assert r.avertissements == ["2026-10-08.json elements[0] (a): R4 : `pour_toi` recopié du 05/10"]


def test_r4_recopie_signale_le_plus_recent_des_fichiers_identiques():
    q = _jours(**{"2026-10-02": [("a", "Texte.")], "2026-10-04": [("a", "Texte.")], "2026-10-06": [("a", "Texte.")]})
    assert [d for _, _, d in v.recopies_pour_toi(q, "2026-10-06")] == ["2026-10-04"]


@pytest.mark.parametrize("ancien, courant, motif", [
    ("2026-09-30", "2026-10-08", "huit jours"), ("2026-10-08", "2026-10-08", "même fichier"),
    ("2026-10-09", "2026-10-08", "fichier postérieur"),
], ids=["hors-fenetre", "meme-jour", "posterieur"])
def test_r4_recopie_hors_des_7_jours_precedents(ancien, courant, motif):
    q = _jours(**{ancien: [("a", "Texte.")], courant: [("a", "Texte.")]}) if ancien != courant \
        else _jours(**{courant: [("a", "Texte."), ("b", "Texte.")]})
    assert v.recopies_pour_toi(q, courant) == []


def test_r4_recopie_limite_inclusive_a_sept_jours():
    q = _jours(**{"2026-10-01": [("a", "Texte.")], "2026-10-08": [("a", "Texte.")]})
    assert len(v.recopies_pour_toi(q, "2026-10-08")) == 1


def test_r4_recopie_texte_different_ou_id_different_ou_null_ne_signale_pas():
    q = _jours(**{"2026-10-05": [("a", "Ta limite est à 83 %."), ("b", "Même texte."), ("c", None)],
                  "2026-10-08": [("a", "Ta limite est à 92 %."), ("autre", "Même texte."), ("c", None)]})
    assert v.recopies_pour_toi(q, "2026-10-08") == []
    q["2026-10-08"]["elements"].append({"id": "d", "pour_toi": "", "impact": "moyen"})
    q["2026-10-05"]["elements"].append({"id": "d", "pour_toi": "", "impact": "moyen"})
    assert v.recopies_pour_toi(q, "2026-10-08") == []  # un texte vide n'est pas une recopie


def test_r4_recopie_element_nul_n_avertit_pas():
    q = _jours(**{"2026-10-05": [("a", "Texte.")], "2026-10-08": [("a", "Texte.")]})
    q["2026-10-08"]["elements"][0]["impact"] = "nul"
    r = v.Rapport()
    v.avertir_recopies(q, r)
    assert r.avertissements == []


def test_r4_recopie_de_bout_en_bout_sans_changer_le_code(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    q["elements"][0].update(pour_toi="Ton projet trading-sim est concerné.", impact="moyen")
    _reecrire(chemin, q)
    jour_avant = (datetime.date.fromisoformat(JOUR) - datetime.timedelta(days=3)).isoformat()
    ancien = chemin.with_name(f"{jour_avant}.json")
    ancien.write_text(json.dumps({**q, "date": jour_avant}), encoding="utf-8")
    validation(racine, "claude", brut=False)
    sortie = capsys.readouterr().out
    attendu = f"{jour_avant[8:10]}/{jour_avant[5:7]}"
    assert any(l.startswith(f"! AVERTISSEMENT {JOUR}.json elements[0]") and f"R4 : `pour_toi` recopié du {attendu}" in l
               for l in sortie.splitlines())
    assert not any(f"{jour_avant}.json elements" in l and "recopié" in l for l in sortie.splitlines())


def test_r4_conditionnel_de_bout_en_bout_sans_changer_le_code(racine, capsys):
    chemin, q = _quotidien_valide(racine)
    q["elements"][0].update(pour_toi="Si tu lances trading-sim ce soir, ça change.", action=None)
    _reecrire(chemin, q)
    assert validation(racine, "claude", brut=False) == 0
    assert any("R4 : `pour_toi` conditionnel" in l for l in capsys.readouterr().out.splitlines())
