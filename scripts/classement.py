#!/usr/bin/env python3
"""Classement préalable des nouveautés de la veille sur la clé « delta » (A1, décision du 15/10/2026, priorité 4).

Pour chaque nouveauté brute de `raw/<p>-nouveautes.json`, une proposition : `verdict` (fort, moyen, faible, nul, ecarte)
et `pourquoi` (pour Sylvain, d'après CONTEXTE.md et `profil.yaml`). L'agent du passage `/delta` relit chaque proposition
contre les règles (REGLES.md, skill) et reste seul auteur du fichier publié : rien de ce script n'est publié tel quel.

    classement.py soumettre --perimetre p [--date J]   lot A1 (mode batch) ou appel `claude-cle` (mode direct)
    classement.py relever   --perimetre p [--date J] [--attendre S]
    classement.py couts     [--jours N]                coût par jour, lu dans les fichiers du classement

Réglage dans `scripts/classement.toml` (`mode` : batch, direct, aucun ; `aucun` = passage d'avant, rien d'écrit).
Sortie : `raw/classement/<J>-<p>.json` (`raw/` n'est jamais commité) :
  {date, perimetre, mode, modele, usage, statut, raison, lot, ids, classement: [{id, verdict, pourquoi}], manquants,
   cout_usd, cout_statut, soumis_le, releve_le}
  statut : en_cours (lot soumis), ok, en_attente (lot non terminé à temps), echec, solde_epuise (A1, code 5).
  cout_statut : mesure (coût rapporté par A1 ou par `claude-cle`), non_mesure (cout_usd null : jamais compté 0).
Un lot non terminé reste noté : le `soumettre` suivant le relève d'abord, pour que A1 le compte.
Codes : 0 ok, en_cours, en_attente, désactivé ou rien à classer ; 1 echec ; 5 solde A1 nul ou cycle échu ; 2 argument.
Aucun de ces codes n'arrête le passage : sans classement `ok`, l'agent classe seul (repli sans coût sur l'abonnement).

Clé jamais lue ni transmise ici : A1 la lit au trousseau (`apiKeyHelper` de `claude-cle`, ou `credits_api` pour les lots).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).resolve().parent / "classement.toml"
DOSSIER = Path("raw") / "classement"
VERDICTS = ("fort", "moyen", "faible", "nul", "ecarte")
PERIMETRES = ("claude", "actu", "openai")
CODE_SOLDE = 5  # A1 : solde nul ou cycle échu (`claude-cle`, `delta-cle-api`, `operer credits`)

CONSIGNES = """Tu proposes le classement des nouveautés de la veille quotidienne Delta pour Sylvain, décrit par CONTEXTE.md et profil.yaml ci-dessous.
Pour chaque nouveauté, un verdict et une phrase « pourquoi » :
- fort : change immédiatement sa façon de travailler sur un projet actif, ou casse / déprécie quelque chose qu'il utilise ;
- moyen : utile à court terme sur un projet ou une habitude identifiés, ou changement défavorable sans effet immédiat ;
- faible : potentiellement utile, sans lien direct avec les projets actuels ;
- nul : concerne le produit mais rien ne s'applique à Sylvain (outil non utilisé, réglage sans effet dans sa configuration) ;
- ecarte : sans rapport avec les modèles, les outils et agents IA ou les conditions de leur usage (marketing, procès, politique, faits divers, partenariats, applications sectorielles).
Règles : toute information sur limites, quotas, remises à zéro, crédits, offres, tarifs ou forfaits de Claude, ChatGPT ou Codex vaut au moins fort ; régression, hausse de prix ou baisse de quota vaut au moins moyen ; un projet ou une priorité ne compte que si la nouveauté change une commande, un réglage ou un flux de travail concret ; ne fabrique jamais de pertinence ; « pourquoi » commence par un constat tiré de CONTEXTE.md (projet, outil ou habitude nommés), une déduction s'écrit au conditionnel, 240 caractères au plus.
Réponds par un seul objet JSON, sans texte autour : {"classement": [{"id": "<id exact>", "verdict": "<verdict>", "pourquoi": "<phrase>"}]}, une entrée par nouveauté, ids recopiés exactement."""


class ErreurA1(RuntimeError):
    """A1 indisponible ou réponse inattendue ; `solde` vrai quand A1 refuse à solde nul ou cycle échu."""

    def __init__(self, message: str, solde: bool = False):
        super().__init__(message)
        self.solde = solde


def charger_config(chemin: Path = CONFIG) -> dict:
    with open(chemin, "rb") as f:
        cfg = tomllib.load(f)
    if cfg.get("mode") not in ("batch", "direct", "aucun"):
        raise ValueError(f"classement.toml : mode inconnu {cfg.get('mode')!r} (batch, direct, aucun)")
    return cfg


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chemin_sortie(racine: Path, jour: str, perimetre: str) -> Path:
    return racine / DOSSIER / f"{jour}-{perimetre}.json"


def ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(chemin)


def lire(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- requête ---------------------------------------------------------------------------------------------------------

def systeme(racine: Path) -> str:
    contexte = (racine / "CONTEXTE.md").read_text(encoding="utf-8")
    profil_chemin = racine / "profil.yaml"
    profil = profil_chemin.read_text(encoding="utf-8") if profil_chemin.exists() else "(profil.yaml absent : aucune priorité)"
    return f"{CONSIGNES}\n\n# CONTEXTE.md\n\n{contexte}\n\n# profil.yaml\n\n{profil}"


def a_classer(brut: dict) -> list[dict]:
    """Nouveautés et réévaluations (D96) n'ont pas le même traitement : seules les nouveautés sont proposées."""
    return [n for n in brut.get("nouveautes", []) if n.get("id")]


def message_utilisateur(nouveautes: list[dict], contenu_max: int) -> str:
    lignes = [f"{len(nouveautes)} nouveauté(s) :"]
    for n in nouveautes:
        contenu = (n.get("contenu") or "").strip()
        if len(contenu) > contenu_max:
            contenu = contenu[:contenu_max] + " […]"
        entree = {"id": n["id"], "produit": n.get("produit"), "titre": n.get("titre"), "version": n.get("version"),
                  "date_publication": n.get("date_publication"), "source_id": n.get("source_id"),
                  "officielle": n.get("officielle"), "revision": n.get("revision", False), "contenu": contenu}
        if n.get("changements"):
            entree["changements"] = n["changements"]
        lignes.append(json.dumps(entree, ensure_ascii=False))
    return "\n".join(lignes)


def requete_lot(custom_id: str, cfg: dict, sys_texte: str, texte: str) -> dict:
    """Requête au format Message Batches ; CONTEXTE.md en tête, mis en cache (les deux périmètres le partagent)."""
    return {"custom_id": custom_id, "params": {
        "model": cfg["modele"], "max_tokens": int(cfg["max_tokens"]),
        "system": [{"type": "text", "text": sys_texte, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": texte}]}}


# --- réponse ---------------------------------------------------------------------------------------------------------

def analyser(texte: str, ids: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """(classement retenu, ids sans proposition, anomalies). Une entrée hors format est écartée et dite, jamais devinée."""
    m = re.search(r"\{.*\}", texte or "", re.S)
    if not m:
        raise ValueError("réponse sans objet JSON")
    doc = json.loads(m.group(0))
    entrees = doc.get("classement")
    if not isinstance(entrees, list):
        raise ValueError("réponse sans liste `classement`")
    attendus, retenus, anomalies = set(ids), {}, []
    for e in entrees:
        if not isinstance(e, dict):
            anomalies.append("entrée non objet")
            continue
        i, v, p = e.get("id"), e.get("verdict"), e.get("pourquoi")
        if i not in attendus:
            anomalies.append(f"id inconnu : {i!r}")
        elif i in retenus:
            anomalies.append(f"id en double : {i}")
        elif v not in VERDICTS:
            anomalies.append(f"verdict inconnu pour {i} : {v!r}")
        elif not isinstance(p, str) or not p.strip():
            anomalies.append(f"pourquoi vide pour {i}")
        else:
            retenus[i] = {"id": i, "verdict": v, "pourquoi": p.strip()}
    return [retenus[i] for i in ids if i in retenus], [i for i in ids if i not in retenus], anomalies


def texte_message(message: dict) -> str:
    return "".join(b.get("text", "") for b in message.get("content", []) if b.get("type") == "text")


# --- A1 : appels directs (`claude-cle`) et lots (`credits_api`) -------------------------------------------------------

def appeler_direct(cfg: dict, sys_texte: str, texte: str, executer=subprocess.run) -> tuple[str, float | None]:
    """Un appel `claude-cle --usage <usage>` (A1 : `claude -p --bare --output-format json`, compté au registre).
    Rend (texte de la réponse, coût rapporté par claude) ; ErreurA1 sinon."""
    binaire = os.path.expanduser(cfg["claude_cle"])
    entree = f"{sys_texte}\n\n# Nouveautés à classer\n\n{texte}"
    try:
        p = executer([binaire, "--usage", cfg["usage"], "--model", cfg["modele"]], input=entree,
                     capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        raise ErreurA1(f"{binaire} introuvable (lanceur A1 non lié dans ~/.local/bin)") from None
    except subprocess.TimeoutExpired:
        raise ErreurA1("claude-cle : délai de 600 s dépassé") from None
    if p.returncode == CODE_SOLDE:
        raise ErreurA1("A1 : solde nul ou cycle échu (code 5)", solde=True)
    try:
        sortie = json.loads(p.stdout)
    except ValueError:
        raise ErreurA1(f"claude-cle : code {p.returncode}, sortie non JSON : {(p.stderr or p.stdout).strip()[:200]}") from None
    if p.returncode or sortie.get("is_error"):
        raise ErreurA1(f"claude-cle : code {p.returncode}, {str(sortie.get('result'))[:200]}")
    cout = sortie.get("total_cost_usd")
    return str(sortie.get("result") or ""), (float(cout) if isinstance(cout, (int, float)) else None)


def charger_a1(cfg: dict, racine: Path):
    """Module `delta.operer.credits_api` d'A1 (dépôt discipline). ErreurA1 s'il est absent ou sans les fonctions de lot."""
    src = (racine / os.path.expanduser(cfg["a1_src"])).resolve()
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from delta.operer import credits_api  # type: ignore
    except Exception as exc:  # paquet absent ou cassé : repli dit, jamais silencieux
        raise ErreurA1(f"A1 introuvable sous {src} : {exc}") from None
    for nom in ("soumettre_lot", "relever_lot"):
        if not callable(getattr(credits_api, nom, None)):
            raise ErreurA1(f"A1 sans `{nom}`")
    return credits_api


def _appel(fonction, usage: str, argument):
    """Appelle une fonction d'A1 sous sa signature réelle `f(usage, argument)`. Signature inattendue : ErreurA1."""
    try:
        return fonction(usage, argument)
    except TypeError as exc:
        raise ErreurA1(f"A1 : signature inattendue de {getattr(fonction, '__name__', fonction)} : {exc}") from None
    except Exception as exc:
        solde = "solde" in str(exc).lower() or getattr(exc, "code", None) == CODE_SOLDE
        raise ErreurA1(f"A1 : {type(exc).__name__} : {exc}", solde=solde) from None


class LotA1:
    """Interface d'A1 (`delta.operer.credits_api`) : `soumettre_lot(usage, requetes)` rend `{id, usage, statut}` ;
    `relever_lot(usage, id)` rend `{statut, comptes, resultats}`, `statut` différent de `ended` tant que le lot n'est pas
    terminé, puis les résultats au format Message Batches (`[{custom_id, result: {type, message}}]`). A1 compte la
    dépense au registre (50 % du tarif public) au relevé ; `cout_usd` par résultat seulement quand A1 le donne."""

    def __init__(self, cfg: dict, racine: Path, module=None):
        self.usage = cfg["usage"]
        self.api = module or charger_a1(cfg, racine)

    def soumettre(self, requetes: list[dict]) -> str:
        r = _appel(self.api.soumettre_lot, self.usage, requetes)
        lot = r.get("id") if isinstance(r, dict) else r
        if not isinstance(lot, str) or not lot:
            raise ErreurA1(f"A1 : soumettre_lot sans id de lot ({type(r).__name__})")
        return lot

    def relever(self, lot: str) -> list[dict] | None:
        r = _appel(self.api.relever_lot, self.usage, lot)
        if r is None:
            return None
        if isinstance(r, dict):
            if r.get("statut", "ended") != "ended" or r.get("processing_status") == "in_progress":
                return None
            r = r.get("resultats", r.get("results"))
        if not isinstance(r, list):
            raise ErreurA1(f"A1 : relever_lot, résultats illisibles ({type(r).__name__})")
        return r


# --- commandes -------------------------------------------------------------------------------------------------------

def _base(cfg: dict, jour: str, perimetre: str, ids: list[str]) -> dict:
    return {"date": jour, "perimetre": perimetre, "mode": cfg["mode"], "modele": cfg["modele"], "usage": cfg["usage"],
            "statut": None, "raison": None, "lot": None, "ids": ids, "classement": [], "manquants": [], "anomalies": [],
            "cout_usd": None, "cout_statut": "non_mesure", "soumis_le": maintenant(), "releve_le": None}


def _completer(doc: dict, texte: str, cout: float | None) -> None:
    classement, manquants, anomalies = analyser(texte, doc["ids"])
    doc.update(statut="ok", classement=classement, manquants=manquants, anomalies=anomalies, releve_le=maintenant())
    if cout is not None:
        doc.update(cout_usd=round(cout, 6), cout_statut="mesure")


def _echec(doc: dict, exc: Exception) -> int:
    solde = isinstance(exc, ErreurA1) and exc.solde
    doc.update(statut="solde_epuise" if solde else "echec", raison=str(exc)[:300], releve_le=maintenant())
    return CODE_SOLDE if solde else 1


def appliquer_resultats(doc: dict, resultats: list[dict]) -> None:
    """Un lot par périmètre : une seule requête, `custom_id` = `<jour>-<perimetre>`."""
    attendu = f"{doc['date']}-{doc['perimetre']}"
    res = next((r for r in resultats if isinstance(r, dict) and r.get("custom_id") == attendu), None)
    if res is None:
        raise ErreurA1(f"lot {doc['lot']} sans résultat pour {attendu}")
    resultat = res.get("result") or {}
    if resultat.get("type") != "succeeded":
        raise ErreurA1(f"lot {doc['lot']} : requête {resultat.get('type')!r} ({str(resultat.get('error'))[:200]})")
    cout = res.get("cout_usd")
    _completer(doc, texte_message(resultat.get("message") or {}), float(cout) if isinstance(cout, (int, float)) else None)


def relever_doc(doc: dict, lot_a1, attendre_s: float = 0, intervalle_s: float = 30, dormir=time.sleep,
                horloge=time.monotonic) -> int:
    """Relève le lot de `doc` (modifié sur place). 0 ok ou en_attente ; 1 echec ; 5 solde."""
    fin = horloge() + attendre_s
    while True:
        try:
            resultats = lot_a1.relever(doc["lot"])
            if resultats is not None:
                appliquer_resultats(doc, resultats)
                return 0
        except (ErreurA1, ValueError) as exc:
            return _echec(doc, exc)
        if horloge() + intervalle_s > fin:
            doc.update(statut="en_attente", raison=f"lot non terminé après {int(attendre_s)} s ; relevé au passage suivant")
            return 0
        dormir(intervalle_s)


def relever_en_attente(racine: Path, cfg: dict, lot_a1_fabrique, sauf: Path | None = None) -> list[str]:
    """Relève sans attendre les lots restés en_cours ou en_attente des jours passés : A1 ne compte un lot qu'au relevé."""
    notes = []
    for chemin in sorted((racine / DOSSIER).glob("*.json")):
        doc = lire(chemin)
        if chemin == sauf or not doc or doc.get("mode") != "batch" or doc.get("statut") not in ("en_cours", "en_attente"):
            continue
        try:
            lot_a1 = lot_a1_fabrique()
        except ErreurA1 as exc:
            return notes + [f"{chemin.name} : non relevé ({exc})"]
        relever_doc(doc, lot_a1)
        ecrire(chemin, doc)
        notes.append(f"{chemin.name} : {doc['statut']}")
    return notes


def soumettre(racine: Path, cfg: dict, perimetre: str, jour: str, executer=subprocess.run, lot_a1_fabrique=None) -> int:
    if cfg["mode"] == "aucun":
        print("classement : désactivé (classement.toml, mode = \"aucun\") ; l'agent classe seul")
        return 0
    brut = lire(racine / "raw" / f"{perimetre}-nouveautes.json")
    if brut is None:
        print(f"classement : raw/{perimetre}-nouveautes.json absent ou illisible ; lance d'abord fetch.py", file=sys.stderr)
        return 1
    nouveautes = a_classer(brut)
    sortie = chemin_sortie(racine, jour, perimetre)
    fabrique = lot_a1_fabrique or (lambda: LotA1(cfg, racine))
    if cfg["mode"] == "batch":
        for note in relever_en_attente(racine, cfg, fabrique, sauf=sortie):
            print(f"classement : lot précédent {note}")
    if not nouveautes:
        print(f"classement : aucune nouveauté à classer pour {perimetre}")
        return 0
    ids = [n["id"] for n in nouveautes]
    doc = _base(cfg, jour, perimetre, ids)
    sys_texte, texte = systeme(racine), message_utilisateur(nouveautes, int(cfg["contenu_max"]))
    try:
        if cfg["mode"] == "direct":
            reponse, cout = appeler_direct(cfg, sys_texte, texte, executer)
            _completer(doc, reponse, cout)
            code = 0
        else:
            doc["lot"] = fabrique().soumettre([requete_lot(f"{jour}-{perimetre}", cfg, sys_texte, texte)])
            doc.update(statut="en_cours")
            code = 0
    except (ErreurA1, ValueError) as exc:
        code = _echec(doc, exc)
    ecrire(sortie, doc)
    print(resume(doc))
    return code


def relever(racine: Path, cfg: dict, perimetre: str, jour: str, attendre_s: float, lot_a1=None,
            dormir=time.sleep, horloge=time.monotonic) -> int:
    sortie = chemin_sortie(racine, jour, perimetre)
    doc = lire(sortie)
    if doc is None:
        print(f"classement : aucun classement pour {perimetre} le {jour} ; l'agent classe seul")
        return 0
    if doc.get("statut") in ("en_cours", "en_attente"):
        try:
            lot_a1 = lot_a1 or LotA1(cfg, racine)
        except ErreurA1 as exc:
            code = _echec(doc, exc)
        else:
            code = relever_doc(doc, lot_a1, attendre_s, float(cfg["intervalle_s"]), dormir, horloge)
        ecrire(sortie, doc)
    else:
        code = {"ok": 0, "solde_epuise": CODE_SOLDE}.get(doc.get("statut"), 1)
    print(resume(doc))
    return code


def resume(doc: dict) -> str:
    tete = f"classement {doc['perimetre']} {doc['date']} ({doc['mode']}) : {doc['statut']}"
    if doc["statut"] == "ok":
        compte = {v: sum(1 for e in doc["classement"] if e["verdict"] == v) for v in VERDICTS}
        cout = f"{doc['cout_usd']:.4f} $" if doc["cout_usd"] is not None else "coût non mesuré"
        tete += f", {len(doc['classement'])}/{len(doc['ids'])} proposés " + \
                ", ".join(f"{n} {v}" for v, n in compte.items() if n) + f" ; {cout}"
        if doc["manquants"]:
            tete += f" ; sans proposition : {', '.join(doc['manquants'])}"
        if doc["anomalies"]:
            tete += f" ; {len(doc['anomalies'])} anomalie(s)"
    elif doc.get("raison"):
        tete += f" ({doc['raison']})"
    if doc.get("lot"):
        tete += f" ; lot {doc['lot']}"
    return tete


def couts(racine: Path, jours: int, aujourd_hui: date | None = None) -> list[dict]:
    """Coût par jour : somme des `cout_usd` mesurés des fichiers du classement ; un appel non mesuré est compté à part."""
    debut = (aujourd_hui or date.today()) - timedelta(days=jours - 1)
    parjour: dict[str, dict] = {}
    for chemin in sorted((racine / DOSSIER).glob("*.json")):
        doc = lire(chemin)
        if not doc or not doc.get("date") or doc["date"] < debut.isoformat() or doc.get("statut") not in ("ok",):
            continue
        j = parjour.setdefault(doc["date"], {"date": doc["date"], "cout_usd": 0.0, "appels": 0, "non_mesures": 0})
        j["appels"] += 1
        if doc.get("cout_usd") is None:
            j["non_mesures"] += 1
        else:
            j["cout_usd"] = round(j["cout_usd"] + doc["cout_usd"], 6)
    return [parjour[k] for k in sorted(parjour)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sous = ap.add_subparsers(dest="commande", required=True)
    for nom in ("soumettre", "relever"):
        s = sous.add_parser(nom)
        s.add_argument("--perimetre", required=True, choices=PERIMETRES)
        s.add_argument("--date", default=date.today().isoformat())
        if nom == "relever":
            s.add_argument("--attendre", type=float, default=None, help="secondes ; défaut : attente_s de classement.toml")
    c = sous.add_parser("couts")
    c.add_argument("--jours", type=int, default=7)
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cfg = charger_config()
    if args.commande == "soumettre":
        return soumettre(RACINE, cfg, args.perimetre, args.date)
    if args.commande == "relever":
        attendre = float(cfg["attente_s"]) if args.attendre is None else args.attendre
        return relever(RACINE, cfg, args.perimetre, args.date, attendre)
    lignes = couts(RACINE, args.jours)
    if args.json:
        print(json.dumps(lignes, ensure_ascii=False, indent=2))
    else:
        for j in lignes:
            extra = f" ({j['non_mesures']} non mesuré(s) : total minoré)" if j["non_mesures"] else ""
            print(f"{j['date']} : {j['cout_usd']:.4f} $, {j['appels']} appel(s){extra}")
        if not lignes:
            print("aucun classement mesuré sur la période")
    return 0


if __name__ == "__main__":
    sys.exit(main())
