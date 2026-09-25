"""D13 (--valider piloté par le fichier quotidien) et D15 (scripts/valider.py) sur des fichiers synthétiques."""

import copy
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


def brut_de(racine, perimetre):
    fetch.main(["--racine", str(racine), "--perimetre", perimetre])
    return json.loads((racine / "raw" / f"{perimetre}-nouveautes.json").read_text())


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
    from pathlib import Path
    assert v.projets_du_contexte(racine / "CONTEXTE.md") == {"carnet", "trading-sim", "chatgpt-trading-sim"}
    assert "trading-sim" in v.projets_du_contexte(Path(fetch.RACINE) / "CONTEXTE.md")


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
