"""Capteur de la liste X officielle (décisions de Sylvain du 22/10/2026) : relevé par l'API X, analyseur, statuts d'échec, jeton du
trousseau, comptes de lectures, purge et branchement dans la chaîne. Aucun appel réseau ni accès au trousseau réel."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

import orchestrateur as orc
from conftest import FIXTURES
from deltalib import capteur_x
from deltalib.analyseurs import x_liste
from deltalib.modeles import ErreurSource, FormatInattendu
from deltalib.passage import recuperer
from deltalib.sources import Source

BRUT = json.loads((FIXTURES / "x_liste_brut.json").read_text(encoding="utf-8"))
API = json.loads((FIXTURES / "x_api_liste.json").read_text(encoding="utf-8"))
MAINTENANT = datetime(2026, 10, 22, 21, 30, tzinfo=timezone.utc)
JETON = "jeton-secret-de-test-0123456789"
ANTHROPIC = ("@AnthropicAI", "@claudeai", "@ClaudeDevs")
OPENAI = ("@OpenAI", "@ChatGPT", "@OpenAIDevs")


def source(sid="x-liste-anthropic", comptes=ANTHROPIC, **options) -> Source:
    return Source(id=sid, perimetre="claude", produit="claude", type="x_liste", url=capteur_x.LISTE_URL,
                  statut="a_valider", officielle=True, note="", options={"comptes": list(comptes), **options})


def brut(**changes) -> dict:
    return {**json.loads(json.dumps(BRUT)), **changes}


def attendus(comptes):
    return {p["id"] for p in BRUT["posts"] if p["compte"] in comptes and p["type"] not in ("repost", "reponse")}


# ------------------------------------------------------------------------------------------------ analyseur

def test_analyseur_filtre_par_compte_ecarte_reposts_et_reponses_et_date_l_identifiant():
    r = x_liste.parser_brut(brut(), source(), MAINTENANT)
    assert {e.id for e in r.elements} == {f"x-{i}" for i in attendus(ANTHROPIC)} and r.elements
    # ce qui n'est pas traité est inscrit dans `ignores` (D3) : jamais perdu, jamais relu comme nouveauté
    assert len(r.elements) + len(r.ignores) == len(BRUT["posts"])
    e = next(e for e in r.elements if e.titre.startswith("@claudeai"))
    assert e.titre == "@claudeai — post du 2026-10-22 20:04 UTC" and "Texte d'essai" not in e.titre and "Texte d'essai" in e.contenu
    assert e.date_publication == "2026-10-22" and e.url == "https://x.com/claudeai/status/2113360845409583307"
    assert e.officielle and e.produit == "claude" and e.source_id == "x-liste-anthropic"
    r2 = x_liste.parser_brut(brut(), source("x-liste-openai", OPENAI), MAINTENANT)
    assert {e.id for e in r2.elements} == {f"x-{i}" for i in attendus(OPENAI)}
    assert not ({e.id for e in r.elements} & {e.id for e in r2.elements})


@pytest.mark.parametrize("modif, attendu", [
    ({"statut": "jeton_absent", "message": "trousseau verrouillé"}, "jeton_absent — trousseau verrouillé"),
    ({"statut": "credits_epuises", "message": "crédits X épuisés (402)"}, "credits_epuises — crédits X épuisés"),
    ({"statut": "limite_atteinte", "message": None}, "limite_atteinte — sans message"),
    ({"releve_le": (MAINTENANT - timedelta(hours=40)).isoformat()}, "relevé X périmé"),
])
def test_un_releve_en_echec_est_une_erreur_de_source_explicite(modif, attendu):
    with pytest.raises(ErreurSource, match=attendu):
        x_liste.parser_brut(brut(**modif), source(), MAINTENANT)


def test_brut_mal_forme_ou_source_sans_comptes():
    with pytest.raises(FormatInattendu):
        x_liste.parser_brut({"statut": "ok"}, source(), MAINTENANT)
    with pytest.raises(FormatInattendu, match="comptes"):
        x_liste.parser_brut(brut(), source(comptes=()), MAINTENANT)
    with pytest.raises(FormatInattendu, match="date de relevé"):
        x_liste.parser_brut(brut(releve_le="hier"), source(), MAINTENANT)


def test_fichier_absent_donne_un_echec_de_source_et_le_passage_continue(tmp_path, client):
    elements, echecs, traitees, _ = recuperer([source(fichier=str(tmp_path / "absent.json"))], client)
    assert elements == [] and traitees == []
    assert len(echecs) == 1 and "relevé X absent" in echecs[0].en_dict()["erreur"]


def test_jeton_refuse_passage_non_bloque_autres_sources_intactes(tmp_path, sources, client):
    f = tmp_path / "x.json"
    f.write_text(json.dumps(brut(statut="jeton_refuse", message="X refuse le jeton (401)", releve_le=datetime.now(timezone.utc).isoformat())))
    elements, echecs, traitees, _ = recuperer([source(fichier=str(f)), sources["claude-code-changelog"]], client)
    assert traitees == ["claude-code-changelog"] and elements
    assert "jeton_refuse — X refuse le jeton (401)" in echecs[0].en_dict()["erreur"]


def test_relevé_partiel_est_signalé_sans_perdre_les_posts(tmp_path, client):
    f = tmp_path / "x.json"
    f.write_text(json.dumps(brut(partiel="page 2 non lue : limite de X atteinte (429)", releve_le=datetime.now(timezone.utc).isoformat())))
    elements, echecs, traitees, _ = recuperer([source(fichier=str(f))], client)
    assert elements and traitees == ["x-liste-anthropic"]
    assert [(e.partiel, "429" in e.erreur) for e in echecs] == [(True, True)]


def test_sources_inscrites_dans_sources_yaml(sources):
    for sid in ("x-liste-anthropic", "x-liste-openai"):
        s = sources[sid]
        assert s.type == "x_liste" and s.statut == "a_valider" and s.officielle
        assert s.options["comptes"] and s.url == capteur_x.LISTE_URL
    assert not ({c.lower() for c in sources["x-liste-anthropic"].options["comptes"]}
                & {c.lower() for c in sources["x-liste-openai"].options["comptes"]})


# ------------------------------------------------------------------------------------------------ poste_depuis_api

COMPTES = {"1": "claudeai", "2": "ClaudeDevs"}


def tweet(ident="2113360845409583307", auteur="1", **kw):
    return {"id": ident, "author_id": auteur, "text": "t", "created_at": "2026-10-22T20:04:24.000Z", **kw}


@pytest.mark.parametrize("kw, genre", [
    ({}, "original"),
    ({"referenced_tweets": [{"type": "retweeted", "id": "9"}]}, "repost"),
    ({"referenced_tweets": [{"type": "quoted", "id": "9"}]}, "citation"),
    ({"referenced_tweets": [{"type": "replied_to", "id": "9"}], "in_reply_to_user_id": "1"}, "reponse_a_soi"),
    ({"referenced_tweets": [{"type": "replied_to", "id": "9"}], "in_reply_to_user_id": "77"}, "reponse"),
])
def test_genre_du_post(kw, genre):
    assert capteur_x.poste_depuis_api(tweet(**kw), COMPTES)["type"] == genre


def test_post_mal_forme_ou_compte_inconnu_ecarte_et_date_lue_dans_l_identifiant():
    assert capteur_x.poste_depuis_api(tweet(auteur="99"), COMPTES) is None
    assert capteur_x.poste_depuis_api(tweet(ident="abc"), COMPTES) is None
    p = capteur_x.poste_depuis_api(tweet(created_at="1999-01-01T00:00:00.000Z"), COMPTES)
    assert p["date_iso"] == "2026-10-22T20:04:24.548000Z" and p["url"] == "https://x.com/claudeai/status/2113360845409583307"


# ------------------------------------------------------------------------------------------------ relevé

class Rep:
    def __init__(self, statut=200, corps=None, entetes=None, texte_json=True):
        self.status_code, self._corps, self.headers, self._json = statut, corps, entetes or {"x-rate-limit-remaining": "899"}, texte_json

    def json(self):
        if not self._json:
            raise ValueError("pas du JSON")
        return self._corps


class Session:
    def __init__(self, *reponses):
        self.reponses, self.appels = list(reponses), []

    def get(self, url, headers=None, params=None, timeout=None):
        self.appels.append({"url": url, "headers": headers, "params": dict(params), "timeout": timeout})
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def page(*idents, suivant="pg2", utilisateurs=None):
    """Page de l'API dont les posts sont tirés de la réponse enregistrée."""
    par_id = {t["id"]: t for t in API["data"]}
    return {"data": [par_id[i] for i in idents], "includes": {"users": utilisateurs or API["includes"]["users"]},
            "meta": {"next_token": suivant, "result_count": len(idents)} if suivant else {"result_count": len(idents)}}


IDS = [t["id"] for t in API["data"]]


USAGE = {"data": {"cap_reset_day": 22, "project_cap": "3000000", "project_id": "1", "project_usage": "50"}}


def test_premier_releve_une_page_et_comptes_de_lectures(tmp_path):
    s = Session(Rep(corps=API), Rep(corps=USAGE))
    b = capteur_x.releve(tmp_path, JETON, s, connus=set())
    assert b["statut"] == "ok" and len(s.appels) == 2 and len(b["posts"]) == 33 and b["partiel"] is None
    assert b["lectures"] == {"pages": 1, "posts": 33, "utilisateurs": 6, "cout_estime_usd": 0.225, "limite_restante": "899",
                             "cycle_posts_lus": 50, "plafond_posts": 3000000, "jour_remise": 22}
    assert s.appels[1]["url"] == capteur_x.USAGE_URL
    a = s.appels[0]
    assert a["url"] == capteur_x.API_URL and a["headers"]["Authorization"] == f"Bearer {JETON}"
    assert a["params"]["max_results"] == capteur_x.MAX_RESULTS and a["params"]["expansions"] == "author_id" and a["timeout"] == capteur_x.DELAI_S
    assert JETON not in json.dumps(b)
    assert [p["id"] for p in b["posts"]] == sorted(IDS, reverse=True)[:33]


def test_s_arrete_a_la_premiere_page_qui_contient_un_post_deja_vu(tmp_path):
    s = Session(Rep(corps=page(*IDS[:10])), Rep(corps=page(*IDS[10:20])))
    b = capteur_x.releve(tmp_path, JETON, s, connus={IDS[9]})
    assert len([a for a in s.appels if a["url"] == capteur_x.API_URL]) == 1 and b["lectures"]["pages"] == 1 and b["lectures"]["posts"] == 10


def test_pagine_tant_que_la_page_est_faite_de_posts_nouveaux(tmp_path):
    s = Session(Rep(corps=page(*IDS[:10])), Rep(corps=page(*IDS[10:20])), Rep(corps=page(*IDS[20:25], suivant=None)))
    b = capteur_x.releve(tmp_path, JETON, s, connus={IDS[22]})
    assert len([a for a in s.appels if a["url"] == capteur_x.API_URL]) == 3 and s.appels[1]["params"]["pagination_token"] == "pg2"
    assert b["lectures"]["posts"] == 25 and b["lectures"]["cout_estime_usd"] == round(25 * 0.005 + 6 * 0.010, 4) and b["partiel"] is None


def test_aucun_post_connu_dans_les_pages_lues_est_signale(tmp_path):
    s = Session(*[Rep(corps=page(*IDS[i * 5:(i + 1) * 5])) for i in range(capteur_x.MAX_PAGES)])
    b = capteur_x.releve(tmp_path, JETON, s, connus={"1"})
    assert len([a for a in s.appels if a["url"] == capteur_x.API_URL]) == capteur_x.MAX_PAGES and b["statut"] == "ok" and "des posts plus anciens ont pu échapper" in b["partiel"]


def test_page_suivante_en_echec_garde_la_premiere_et_le_dit(tmp_path):
    s = Session(Rep(corps=page(*IDS[:10])), Rep(429, {"title": "Too Many Requests"}))
    b = capteur_x.releve(tmp_path, JETON, s, connus={"1"})
    assert b["statut"] == "ok" and len(b["posts"]) == 10 and "page 2 non lue" in b["partiel"] and "429" in b["partiel"]


@pytest.mark.parametrize("http, statut, mot", [
    (401, "jeton_refuse", "401"), (403, "acces_refuse", "403"), (402, "credits_epuises", "crédits"),
    (429, "limite_atteinte", "429"), (500, "erreur", "HTTP 500"),
])
def test_erreurs_http_donnent_un_statut_clair_sans_jeton(tmp_path, http, statut, mot):
    b = capteur_x.releve(tmp_path, JETON, Session(Rep(http, {"detail": "détail de X"})), connus={"1"})
    assert b["statut"] == statut and mot in b["message"] and b["posts"] == [] and JETON not in json.dumps(b)


def test_usage_en_echec_ne_gene_pas_le_releve(tmp_path):
    b = capteur_x.releve(tmp_path, JETON, Session(Rep(corps=API), Rep(500, {})), connus=set())
    assert b["statut"] == "ok" and "cycle_posts_lus" not in b["lectures"]


def test_jeton_absent_aucun_appel(tmp_path):
    s = Session()
    for jeton in (None, ""):
        b = capteur_x.releve(tmp_path, jeton, s)
        assert b["statut"] == "jeton_absent" and "secret-tool lookup service x compte delta" in b["message"]
    assert s.appels == []


def test_reseau_indisponible_reponse_illisible_et_liste_vide(tmp_path):
    b = capteur_x.releve(tmp_path, JETON, Session(requests.ConnectionError(f"boom {JETON}")), connus=set())
    assert b["statut"] == "erreur" and JETON not in json.dumps(b)
    assert capteur_x.releve(tmp_path, JETON, Session(Rep(texte_json=False)), connus=set())["statut"] == "illisible"
    b = capteur_x.releve(tmp_path, JETON, Session(Rep(corps={"meta": {"result_count": 0}})), connus=set())
    assert b["statut"] == "illisible" and "aucun post" in b["message"]


def test_identifiants_connus_lus_dans_les_etats_sans_texte(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "claude.json").write_text(json.dumps({"vus": {"x-111": {"vu_le": "x"}, "autre": {}, "x-222": {}}}))
    (tmp_path / "state" / "openai.json").write_text(json.dumps({"vus": {"x-333": {}}}))
    (tmp_path / "state" / "casse.json").write_text("{")
    assert capteur_x.identifiants_connus(tmp_path) == {"111", "222", "333"}
    assert capteur_x.identifiants_connus(tmp_path / "vide") == set()


# ------------------------------------------------------------------------------------------------ jeton du trousseau

def test_jeton_lu_dans_le_trousseau_au_moment_de_l_appel(monkeypatch):
    appels = []
    def faux(cmd, **k):
        appels.append((cmd, k["env"]))
        return type("R", (), {"returncode": 0, "stdout": f"{JETON}\n"})()
    monkeypatch.setattr(capteur_x.subprocess, "run", faux)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert capteur_x.lire_jeton() == JETON
    cmd, env = appels[0]
    assert cmd == ["secret-tool", "lookup", "service", "x", "compte", "delta"]
    assert env["XDG_RUNTIME_DIR"].startswith("/run/user/") and env["DBUS_SESSION_BUS_ADDRESS"].endswith("/bus")


@pytest.mark.parametrize("res", [type("R", (), {"returncode": 1, "stdout": ""})(), type("R", (), {"returncode": 0, "stdout": "\n"})(),
                                 OSError("secret-tool absent")])
def test_jeton_absent_ou_trousseau_inaccessible(monkeypatch, res):
    def faux(*a, **k):
        if isinstance(res, Exception):
            raise res
        return res
    monkeypatch.setattr(capteur_x.subprocess, "run", faux)
    assert capteur_x.lire_jeton() is None


# ------------------------------------------------------------------------------------------------ écriture, comptes, purge

def test_lancer_ecrit_le_brut_et_une_ligne_de_comptes_sans_texte(tmp_path):
    b = capteur_x.lancer(tmp_path, jeton=lambda: JETON, session=Session(Rep(corps=API)))
    assert b["statut"] == "ok"
    ecrit = json.loads((tmp_path / "raw" / "x-liste.json").read_text(encoding="utf-8"))
    assert len(ecrit["posts"]) == 33 and JETON not in json.dumps(ecrit)
    ligne = json.loads((tmp_path / "raw" / "x-cout.jsonl").read_text(encoding="utf-8").strip())
    assert ligne["posts"] == 33 and ligne["cout_estime_usd"] == 0.225 and ligne["statut"] == "ok" and ligne["nouveaux"] == 21
    assert "Texte d'essai" not in json.dumps(ligne)
    capteur_x.lancer(tmp_path, jeton=lambda: None)
    assert len((tmp_path / "raw" / "x-cout.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_lancer_ne_leve_jamais(tmp_path):
    def plante():
        raise RuntimeError(f"boom {JETON}")
    b = capteur_x.lancer(tmp_path, jeton=plante)
    assert b["statut"] == "erreur" and "RuntimeError" in b["message"] and JETON not in json.dumps(b)


def test_purge_supprime_le_brut_et_vide_le_texte_des_posts_x_seulement(tmp_path):
    raw = tmp_path / "raw"
    (raw / "historique" / "2026-10-22").mkdir(parents=True)
    (raw / "x-liste.json").write_text("{}")
    (raw / "x-cout.jsonl").write_text('{"posts": 33}\n')
    def nouveautes(chemin):
        chemin.write_text(json.dumps({"nouveautes": [
            {"id": "x-1", "source_id": "x-liste-anthropic", "contenu": "texte du post", "empreinte": "abc"},
            {"id": "c-1", "source_id": "claude-code-changelog", "contenu": "notes de version"}]}))
    nouveautes(raw / "claude-nouveautes.json")
    nouveautes(raw / "historique" / "2026-10-22" / "claude-nouveautes-0400.json")
    touches = capteur_x.purger(tmp_path)
    assert len(touches) == 3 and not (raw / "x-liste.json").exists() and (raw / "x-cout.jsonl").exists()
    for chemin in (raw / "claude-nouveautes.json", raw / "historique" / "2026-10-22" / "claude-nouveautes-0400.json"):
        n = {e["id"]: e for e in json.loads(chemin.read_text())["nouveautes"]}
        assert n["x-1"]["contenu"] == "" and n["x-1"]["empreinte"] is None and n["c-1"]["contenu"] == "notes de version"
    assert capteur_x.purger(tmp_path) == []


# ------------------------------------------------------------------------------------------------ chaîne

def test_la_chaine_ne_lance_le_capteur_que_si_la_configuration_le_demande(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr(orc.subprocess, "run", lambda *a, **k: appels.append(a[0]) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(orc, "journaliser", lambda *a: appels.append(("journal", a[1], a[3])))
    cfg = orc.charger_config()
    assert cfg["chaine"]["capteur_x"]["delai_s"] > 0       # actif dans la configuration livrée
    sans = {**cfg, "chaine": {k: v for k, v in cfg["chaine"].items() if k != "capteur_x"}}
    orc.Chaine(tmp_path, sans, []).releve_x()
    assert appels == []
    orc.Chaine(tmp_path, cfg, []).releve_x()
    assert appels[0][0] == sys.executable and appels[0][1].endswith("scripts/capteur_x.py") and appels[1] == ("journal", "capteur-x", 0)
    assert "--claude" not in appels[0]


def test_un_capteur_en_echec_ne_bloque_pas_la_chaine(tmp_path, monkeypatch):
    journaux = []
    def plante(*a, **k):
        raise OSError("boom")
    monkeypatch.setattr(orc.subprocess, "run", plante)
    monkeypatch.setattr(orc, "journaliser", lambda *a: journaux.append((a[1], a[3])))
    orc.Chaine(tmp_path, orc.charger_config(), []).releve_x()
    assert journaux == [("capteur-x", 124)]


def test_purge_de_fin_de_chaine(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "x-liste.json").write_text("{}")
    orc.Chaine(tmp_path, orc.charger_config(), []).purge_x()
    assert not (tmp_path / "raw" / "x-liste.json").exists()
