#!/usr/bin/env python3
"""Delta — état des fournisseurs en continu (mission m-f8034da39359, 13/10/2026).

Le passage de nuit lit déjà les pages d'état d'OpenAI et d'Anthropic (analyseur `statuspage`) ; un incident ouvert en
journée n'est donc connu que le lendemain. Ce relevé tourne toutes les 10 minutes (minuteur utilisateur
`delta-etat-fournisseurs.timer`), relit les deux pages avec le même analyseur et le même filtre `ignorer_impacts`
(`sources.yaml`, sources `openai-status` et `anthropic-status`), et écrit l'état courant dans
`~/.local/state/delta/etat-fournisseurs.json`. Il n'écrit rien dans `docs/data/`, `state/` ni `raw/`.

    .venv/bin/python scripts/etat_fournisseurs.py                  # relevé + message au rôle delta si changement
    .venv/bin/python scripts/etat_fournisseurs.py --sans-message   # relevé seul
    .venv/bin/python scripts/etat_fournisseurs.py --sortie /chemin/etat.json

Messages (`operer message envoyer delta`, un seul par relevé) : seulement quand un incident touchant Codex, Claude Code
ou l'API s'ouvre, change d'impact ou se résout. Le premier relevé d'un fournisseur (aucun état antérieur) n'envoie rien :
il amorce l'état. Une page injoignable ou au format inattendu conserve les incidents du dernier relevé réussi, est
inscrite dans le fichier (`lecture: "echec"`, `erreur`) et n'est jamais lue comme « tout est résolu » ; au sixième échec
de suite (une heure) un message le signale, une fois. Un message que `operer` refuse est gardé (`message_en_attente`) et
renvoyé au relevé suivant.

Schéma du fichier (`schema: 1`, lu par OBSERVATORY ; dates en UTC, format de la page d'état) :

    {"schema": 1, "maj": "2026-10-13T12:20:01Z",
     "fournisseurs": {
       "openai" | "anthropic": {
         "source": "openai-status", "url": "<page d'état>", "lecture": "ok" | "echec",
         "derniere_lecture_ok": "<maj>" | null, "erreur": null | "<raison>", "echecs_consecutifs": 0,
         "alerte_injoignable": false,
         "incidents_ouverts": [{"id", "nom", "impact", "statut", "ouvert_le", "maj_le", "lien",
                                "produits": ["codex" | "claude-code" | "api" | "chatgpt" | "claude.ai" | "claude"],
                                "composants": ["<nom>", …]}]}},
     "message_en_attente": null | "<texte>"}

Un incident est « ouvert » tant que son statut n'est ni `resolved`, `postmortem` ni `completed` ; les impacts ignorés
(`ignorer_impacts`, soit `none`) n'y figurent pas. `produits` : règles `produits_par_mot` de la source (tous les mots
reconnus, pas le premier seul) complétées par `api`, `chatgpt` et `claude.ai` (nom de l'incident et composants
touchés) ; sans correspondance, le produit de la source (`chatgpt` pour OpenAI, `claude` pour Anthropic).

Code de sortie : 0 relevé complet, 1 au moins un fournisseur en échec (le fichier est tout de même écrit), 2 impossible
d'écrire le fichier ou de charger `sources.yaml`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

from deltalib.analyseurs.statuspage import _base, incidents_lus  # noqa: E402
from deltalib.http import Client  # noqa: E402
from deltalib.modeles import ErreurSource, FormatInattendu  # noqa: E402
from deltalib.sources import ErreurConfiguration, charger_sources  # noqa: E402

SORTIE_DEFAUT = Path.home() / ".local/state/delta/etat-fournisseurs.json"
FOURNISSEURS = {"openai": "openai-status", "anthropic": "anthropic-status"}
NOMS = {"openai": "OpenAI", "anthropic": "Anthropic"}
STATUTS_FERMES = frozenset({"resolved", "postmortem", "completed"})
PRODUITS_SUIVIS = frozenset({"codex", "claude-code", "api"})  # ceux qui déclenchent un message
SEUIL_INJOIGNABLE = 6  # relevés de suite en échec (une heure) avant le message d'alerte
ROLE_DESTINATAIRE = "delta"
EXPEDITEUR = "etat-fournisseurs"
COMPLEMENTS = {"api": re.compile(r"\bapi\b"), "chatgpt": re.compile(r"chatgpt"), "claude.ai": re.compile(r"claude\.ai")}
PARIS = ZoneInfo("Europe/Paris")


def produits_de(nom: str, composants: list[str], source) -> list[str]:
    textes = [nom.lower()] + [c.lower() for c in composants]
    trouves: list[str] = []
    for produit, mots in (source.options.get("produits_par_mot") or {}).items():
        if any(str(m).lower() in t for m in mots for t in textes):
            trouves.append(produit)
    for produit, motif in COMPLEMENTS.items():
        if any(motif.search(t) for t in textes) and produit not in trouves:
            trouves.append(produit)
    return trouves or [source.produit]


def _maj_le(it: dict) -> str:
    dates = [str(it.get("updated_at") or "")] + [str(u.get("created_at") or "") for u in (it.get("incident_updates") or [])
                                                  if isinstance(u, dict)]
    return max(dates) or str(it["created_at"])


def releve_incidents(donnees, source) -> tuple[list[dict], dict[str, str]]:
    """`(ouverts, fermetures)` : incidents ouverts normalisés ; pour chaque incident lu qui ne l'est pas, pourquoi."""
    ignores = {str(i).lower() for i in (source.options.get("ignorer_impacts") or [])}
    base = _base(donnees, source)
    ouverts: list[dict] = []
    fermetures: dict[str, str] = {}
    for it, _ in incidents_lus(donnees):
        impact = str(it.get("impact") or "").lower()
        statut = str(it["status"]).lower()
        if statut in STATUTS_FERMES:
            fermetures[str(it["id"])] = f"résolu ({statut})"
            continue
        if impact in ignores:
            fermetures[str(it["id"])] = f"impact ramené à {impact}"
            continue
        composants = [str(c["name"]) for c in (it.get("components") or []) if isinstance(c, dict) and c.get("name")]
        ouverts.append({
            "id": str(it["id"]), "nom": str(it["name"]).strip(), "impact": impact or None, "statut": statut,
            "ouvert_le": str(it["created_at"]), "maj_le": _maj_le(it), "lien": f"{base}/incidents/{it['id']}",
            "produits": produits_de(str(it["name"]), composants, source), "composants": composants,
        })
    ouverts.sort(key=lambda i: i["ouvert_le"], reverse=True)
    return ouverts, fermetures


def lire_fournisseur(source, client) -> tuple[list[dict], dict[str, str]]:
    if not source.active:
        raise ErreurSource(f"source {source.id} désactivée dans sources.yaml")
    reponse = client.get(source.url, accept="application/json")
    try:
        donnees = json.loads(reponse.texte)
    except ValueError as e:
        raise FormatInattendu(f"JSON invalide : {str(e)[:120]}") from e
    return releve_incidents(donnees, source)


def changements(avant: list[dict], apres: list[dict], fermetures: dict[str, str]) -> list[dict]:
    """Ouvertures, changements d'impact et résolutions des incidents qui touchent un produit suivi."""
    avant_par_id = {i["id"]: i for i in avant}
    apres_par_id = {i["id"]: i for i in apres}
    sortie: list[dict] = []
    for i in apres:
        ancien = avant_par_id.get(i["id"])
        if ancien is None:
            sortie.append({"genre": "ouverture", "incident": i})
        elif ancien["impact"] != i["impact"]:
            sortie.append({"genre": "impact", "incident": i, "ancien": ancien["impact"]})
    for i in avant:
        if i["id"] not in apres_par_id:
            sortie.append({"genre": "resolution", "incident": i, "raison": fermetures.get(i["id"], "n'est plus listé")})
    return [c for c in sortie if PRODUITS_SUIVIS & set(c["incident"]["produits"])]


def _paris(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS)
    except ValueError:
        return iso
    return d.strftime("%d/%m %H:%M")


def ligne_message(fournisseur: str, c: dict) -> str:
    i = c["incident"]
    produits = ", ".join(i["produits"])
    base = f"{NOMS[fournisseur]} · {i['nom']} ({produits}) · {i['lien']}"
    if c["genre"] == "ouverture":
        return f"OUVERT {_paris(i['ouvert_le'])} Paris, impact {i['impact']}, statut {i['statut']} : {base}"
    if c["genre"] == "impact":
        return f"IMPACT {c['ancien']} → {i['impact']} (statut {i['statut']}) : {base}"
    return f"RÉSOLU ({c['raison']}) : {base}"


def texte_message(par_fournisseur: dict[str, list[dict]], injoignables: list[str]) -> str | None:
    lignes: list[str] = []
    for fournisseur, liste in par_fournisseur.items():
        lignes += [ligne_message(fournisseur, c) for c in liste]
    lignes += [f"{NOMS[f]} · page d'état injoignable depuis {SEUIL_INJOIGNABLE} relevés (une heure) : "
               f"voir erreur dans etat-fournisseurs.json" for f in injoignables]
    if not lignes:
        return None
    return "[ÉTAT FOURNISSEURS] " + "\n".join(lignes)


def envoyer_operer(texte: str) -> None:
    """`operer message envoyer delta <texte>` ; une exception si la commande échoue."""
    operer = shutil.which("operer") or str(Path.home() / ".local/bin/operer")  # PATH réduit sous systemd --user
    p = subprocess.run([operer, "message", "envoyer", "--de", EXPEDITEUR, "--maintenant", ROLE_DESTINATAIRE, texte],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"operer message envoyer : code {p.returncode} : {(p.stderr or p.stdout).strip()[:200]}")


def charger_precedent(chemin: Path) -> dict:
    try:
        doc = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) and doc.get("schema") == 1 else {}


def ecrire_atomique(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, chemin)


def releve(sources: dict, client, precedent: dict, maintenant: str, envoyer=envoyer_operer, avec_message: bool = True) -> tuple[dict, int]:
    """Un relevé complet : `(document à écrire, code de sortie)`. `envoyer` est remplaçable pour les tests."""
    anciens = precedent.get("fournisseurs") or {}
    fournisseurs: dict[str, dict] = {}
    par_fournisseur: dict[str, list[dict]] = {}
    injoignables: list[str] = []
    code = 0
    for nom, id_source in FOURNISSEURS.items():
        source = sources[id_source]
        ancien = anciens.get(nom) or {}
        entree = {"source": id_source, "url": source.url, "lecture": "ok", "derniere_lecture_ok": ancien.get("derniere_lecture_ok"),
                  "erreur": None, "echecs_consecutifs": 0, "alerte_injoignable": False,
                  "incidents_ouverts": list(ancien.get("incidents_ouverts") or [])}
        try:
            ouverts, fermetures = lire_fournisseur(source, client)
        except ErreurSource as e:
            code = 1
            echecs = int(ancien.get("echecs_consecutifs") or 0) + 1
            entree.update(lecture="echec", erreur=f"{type(e).__name__} : {e}"[:300], echecs_consecutifs=echecs,
                          alerte_injoignable=bool(ancien.get("alerte_injoignable")))
            if echecs >= SEUIL_INJOIGNABLE and not entree["alerte_injoignable"]:
                entree["alerte_injoignable"] = True
                injoignables.append(nom)
        else:
            if ancien.get("derniere_lecture_ok"):  # première lecture réussie du fournisseur : amorçage sans message
                par_fournisseur[nom] = changements(ancien.get("incidents_ouverts") or [], ouverts, fermetures)
            entree.update(derniere_lecture_ok=maintenant, incidents_ouverts=ouverts)
        fournisseurs[nom] = entree
    en_attente = precedent.get("message_en_attente")
    texte = texte_message(par_fournisseur, injoignables)
    if en_attente and texte:
        texte = en_attente + "\n" + texte
    texte = texte or en_attente
    if texte and avec_message:
        try:
            envoyer(texte)
            texte = None
        except Exception as e:  # noqa: BLE001 — le message reste en attente, jamais perdu
            print(f"message non remis, gardé pour le relevé suivant : {e}", file=sys.stderr)
    elif not avec_message:
        texte = en_attente
    return {"schema": 1, "maj": maintenant, "fournisseurs": fournisseurs, "message_en_attente": texte}, code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Relevé continu de l'état des fournisseurs (OpenAI, Anthropic).")
    p.add_argument("--sortie", type=Path, default=Path(os.environ.get("DELTA_ETAT_FOURNISSEURS") or SORTIE_DEFAUT))
    p.add_argument("--sans-message", action="store_true", help="relevé seul : aucun message au rôle delta")
    args = p.parse_args(argv)
    try:
        sources = {s.id: s for s in charger_sources(RACINE / "sources.yaml")}
        for id_source in FOURNISSEURS.values():
            if id_source not in sources:
                raise ErreurConfiguration(f"source {id_source} absente de sources.yaml")
    except (OSError, ErreurConfiguration) as e:
        print(f"sources.yaml inutilisable : {e}", file=sys.stderr)
        return 2
    maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc, code = releve(sources, Client(), charger_precedent(args.sortie), maintenant, avec_message=not args.sans_message)
    try:
        ecrire_atomique(args.sortie, doc)
    except OSError as e:
        print(f"écriture impossible ({args.sortie}) : {e}", file=sys.stderr)
        return 2
    for nom, f in doc["fournisseurs"].items():
        print(f"{NOMS[nom]} : lecture {f['lecture']}, {len(f['incidents_ouverts'])} incident(s) ouvert(s)"
              + (f" — {f['erreur']}" if f["erreur"] else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
