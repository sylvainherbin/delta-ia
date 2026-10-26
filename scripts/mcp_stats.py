#!/usr/bin/env python3
"""Delta — relevé hebdomadaire de l'usage du serveur MCP (amende D66).

Lit `GET /stats?jours=N` du serveur MCP (compteur agrégé et anonyme, Upstash) et imprime, pour une semaine
du lundi au dimanche (UTC), les appels par outil, les recherches à zéro résultat, les erreurs et les clients,
avec la comparaison à la semaine précédente. Aucune écriture : ni fichier, ni état, ni `docs/data`.

    .venv/bin/python scripts/mcp_stats.py                       # semaine écoulée
    .venv/bin/python scripts/mcp_stats.py --semaine 2026-W41
    .venv/bin/python scripts/mcp_stats.py --url https://hote.exemple

Code de sortie : 0 relevé imprimé, 1 compteur inactif, illisible ou injoignable (jamais de relevé vide muet).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

RACINE = Path(__file__).resolve().parent.parent
DELAI = 20
GROUPES = (("req", "Requêtes par méthode"), ("outils", "Appels par outil"),
           ("zero", "Recherches à zéro résultat"), ("erreurs", "Erreurs"), ("clients", "Clients (initialize)"),
           ("causes_erreurs", "Causes des erreurs d'outil (codes sans arguments)"))
OUTILS = ("resume_du_jour", "chercher_reference", "fiche_reference", "etat_versions", "a_tester", "nouveautes_base")
# Champs `erreur:<nom>` qui sont la réponse -32601 du serveur à une méthode qu'il ne déclare pas (resources, prompts,
# méthode inconnue) : pas une panne. `autre` vaut -32601 aussi pour les jours comptés avant 0.2.2, où une requête ou un
# JSON invalide (-32600, -32700) y figurait ; depuis, ceux-ci sont comptés sous `invalide`.
NON_PRISES_EN_CHARGE = frozenset({"resources/list", "resources/templates/list", "prompts/list", "autre"})


class Indisponible(RuntimeError):
    """Raison contrôlée, imprimée telle quelle."""


def hote_depuis_contexte(texte: str) -> str | None:
    """URL de base du serveur MCP : première adresse `https://…/mcp` de CONTEXTE.md (section MCP), sans le `/mcp`."""
    m = re.search(r"https://[A-Za-z0-9.-]+(?::\d+)?/mcp\b", texte)
    return m.group(0)[: -len("/mcp")] if m else None


def url_de_base(option: str | None, racine: Path = RACINE) -> str:
    if option:
        return option.rstrip("/")
    try:
        hote = hote_depuis_contexte((racine / "CONTEXTE.md").read_text(encoding="utf-8"))
    except OSError:
        hote = None
    if not hote:
        raise Indisponible("hôte du serveur MCP introuvable dans CONTEXTE.md : utilisez --url")
    return hote


def lundi_de(semaine: str) -> date:
    m = re.fullmatch(r"(\d{4})-W(\d{2})", semaine)
    if not m:
        raise ValueError(f"semaine attendue au format AAAA-Www, reçu {semaine!r}")
    try:
        return date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError:
        raise ValueError(f"semaine inexistante : {semaine}") from None


def nom_semaine(lundi: date) -> str:
    iso = lundi.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def semaine_ecoulee(aujourdhui: date) -> str:
    return nom_semaine(aujourdhui - timedelta(days=aujourdhui.weekday() + 7))


def jours_a_lire(lundi: date, aujourdhui: date) -> int:
    """Jours à demander pour couvrir la semaine et la précédente (14 au moins, 90 au plus)."""
    return max(14, min(90, (aujourdhui - (lundi - timedelta(days=7))).days + 1))


def lire_stats(base: str, jours: int) -> dict:
    try:
        r = requests.get(f"{base}/stats", params={"jours": jours}, timeout=DELAI, headers={"User-Agent": "Delta-mcp-stats/1"})
        donnees = r.json()
    except requests.RequestException as e:
        raise Indisponible(f"{base}/stats injoignable ({type(e).__name__})") from None
    except ValueError:
        raise Indisponible(f"{base}/stats : réponse JSON illisible") from None
    if not isinstance(donnees, dict):
        raise Indisponible(f"{base}/stats : structure inattendue")
    if donnees.get("statut") == "inactif":
        raise Indisponible("compteur inactif : le stockage Upstash n'est pas relié au projet Vercel (variables KV_REST_API_URL et KV_REST_API_TOKEN absentes)")
    if donnees.get("statut") != "ok" or not isinstance(donnees.get("jours"), list):
        raise Indisponible(f"{base}/stats : statut {donnees.get('statut')!r}, {donnees.get('raison') or 'sans raison'}")
    return donnees


def cumuler(stats: dict, lundi: date) -> dict:
    """Somme des jours du lundi au dimanche ; `jours_lus` dit combien de ces 7 jours figurent dans la réponse."""
    voulus = {(lundi + timedelta(days=i)).isoformat() for i in range(7)}
    total: dict = {g: {} for g, _ in GROUPES}
    lus = 0
    for j in stats["jours"]:
        if not isinstance(j, dict) or j.get("jour") not in voulus:
            continue
        lus += 1
        for g, _ in GROUPES:
            for cle, n in (j.get(g) or {}).items():
                total[g][cle] = total[g].get(cle, 0) + int(n)
    total["jours_lus"] = lus
    return total


def _delta(n: int, avant: int) -> str:
    return f"{n} (préc. {avant}, {n - avant:+d})"


def _erreurs(cette: dict, avant: dict) -> list[str]:
    """Erreurs réelles (outil en isError, -32600, -32602, -32700) séparées des méthodes non prises en charge (-32601)."""
    lignes = []
    for titre, retenue in (("Erreurs réelles (outil en erreur, requête invalide, outil inconnu)", lambda c: c not in NON_PRISES_EN_CHARGE),
                           ("Méthodes non prises en charge (-32601, réponse normale du serveur)", lambda c: c in NON_PRISES_EN_CHARGE)):
        cles = sorted((c for c in set(cette["erreurs"]) | set(avant["erreurs"]) if retenue(c)),
                      key=lambda c: (-cette["erreurs"].get(c, 0), -avant["erreurs"].get(c, 0), c))
        lignes.append(f"{titre} :" + ("" if cles else " aucune"))
        lignes.extend(f"  {c:<26} {_delta(cette['erreurs'].get(c, 0), avant['erreurs'].get(c, 0))}" for c in cles)
    return lignes


def rapport(stats: dict, semaine: str, aujourdhui: date) -> str:
    lundi = lundi_de(semaine)
    precedent = lundi - timedelta(days=7)
    cette, avant = cumuler(stats, lundi), cumuler(stats, precedent)
    fin = lundi + timedelta(days=6)
    lignes = [f"Serveur MCP ORQYRA AI — semaine {semaine} ({lundi:%d/%m} au {fin:%d/%m}), comparée à {nom_semaine(precedent)}",
              f"Date du compteur (UTC) : {stats.get('genere_le') or 'inconnue'}"]
    if cette["jours_lus"] < 7 or avant["jours_lus"] < 7:
        lignes.append(f"! Jours absents de la réponse : {7 - cette['jours_lus']} sur la semaine, {7 - avant['jours_lus']} sur la précédente")
    if fin >= aujourdhui:
        lignes.append("! Semaine non terminée : relevé partiel")
    appels = sum(cette["outils"].values())
    lignes.append(f"Appels d'outils : {_delta(appels, sum(avant['outils'].values()))} ; requêtes : {_delta(sum(cette['req'].values()), sum(avant['req'].values()))}")
    for g, titre in GROUPES:
        if g == "erreurs":
            lignes.extend(_erreurs(cette, avant))
            continue
        cles = sorted(set(cette[g]) | set(avant[g]) | (set(OUTILS) if g == "outils" else set()),
                      key=lambda c: (-cette[g].get(c, 0), -avant[g].get(c, 0), c))
        lignes.append(f"{titre} :" + ("" if cles else " aucun"))
        for c in cles:
            lignes.append(f"  {c:<26} {_delta(cette[g].get(c, 0), avant[g].get(c, 0))}")
    recherches = cette["outils"].get("chercher_reference", 0)
    zero = cette["zero"].get("chercher_reference", 0)
    if recherches:
        lignes.append(f"Signal prioritaire D66 : chercher_reference sans résultat {zero} fois sur {recherches} ({round(100 * zero / recherches)} %)")
        erreurs = cette["erreurs"].get("chercher_reference", 0)
        expliquees = sum(n for c, n in cette["causes_erreurs"].items() if c.startswith("chercher_reference/"))
        lignes.append(f"chercher_reference : {erreurs} erreurs ; cause instrumentée pour {expliquees}/{erreurs} ; "
                      f"cause historique inconnue pour {max(0, erreurs - expliquees)}")
    lignes.append("Le taux de zéro résultat ne mesure pas la pertinence : rejouez mcp/mesurer.js sur le corpus étiqueté.")
    return "\n".join(lignes)


def main(argv: list[str] | None = None, aujourdhui: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Relevé hebdomadaire de l'usage du serveur MCP ORQYRA AI (lecture de /stats).")
    p.add_argument("--semaine", help="semaine ISO AAAA-Www (défaut : la semaine écoulée)")
    p.add_argument("--url", help="URL de base du serveur MCP (défaut : lue dans CONTEXTE.md)")
    p.add_argument("--fichier", type=Path, help="rejouer un instantané JSON de /stats, sans réseau")
    a = p.parse_args(argv)
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    try:
        semaine = a.semaine or semaine_ecoulee(aujourdhui)
        lundi = lundi_de(semaine)
        if a.fichier:
            try:
                stats = json.loads(a.fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise Indisponible("instantané /stats illisible") from None
            if not isinstance(stats, dict) or stats.get("statut") != "ok" or not isinstance(stats.get("jours"), list):
                raise Indisponible("instantané /stats : structure inattendue")
        else:
            stats = lire_stats(url_de_base(a.url), jours_a_lire(lundi, aujourdhui))
    except ValueError as e:
        p.error(str(e))
    except Indisponible as e:
        print(f"Relevé impossible : {e}", file=sys.stderr)
        return 1
    print(rapport(stats, semaine, aujourdhui))
    return 0


if __name__ == "__main__":
    sys.exit(main())
