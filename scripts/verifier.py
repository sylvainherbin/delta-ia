#!/usr/bin/env python3
"""Contrôle avant commit (D87) : pytest puis valider.py sur les trois périmètres, jamais deux fois sur le même arbre.

Un succès est enregistré sous une clé qui décrit l'arbre réellement testé : `HEAD^{tree}`, les modifications non
commitées des fichiers suivis, les fichiers non suivis non ignorés, et l'environnement Python. Un rebase sans changement
de contenu donne le même arbre, donc le même résultat. Un échec n'est jamais enregistré.
Les suites passent par le verrou machine (deux places, nice 10) ; la réutilisation d'un résultat n'attend aucun verrou.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PERIMETRES = ("claude", "openai", "actu")
# Sorties locales de travail : ce ne sont pas des entrées des tests.
IGNORES = (".tmp-", ".codex-commit-")
VERROUS = ("verify-machine.lock", "verify-machine-2.lock")  # deux places : deux suites tiennent sur 4 cœurs


def git(*args: str, racine: Path = RACINE) -> bytes:
    return subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True).stdout


def cle_arbre(racine: Path = RACINE) -> str:
    """`<HEAD^{tree}>:<empreinte du contenu non commité>` ; l'empreinte d'un arbre propre est constante."""
    arbre = git("rev-parse", "HEAD^{tree}", racine=racine).decode().strip()
    h = hashlib.sha256()
    h.update(git("diff", "HEAD", "--binary", racine=racine))  # fichiers suivis, indexés ou non
    h.update(b"\0untracked\0")
    autres = git("ls-files", "--others", "--exclude-standard", "-z", racine=racine).decode().split("\0")
    for p in sorted(p for p in autres if p and not p.startswith(IGNORES)):
        chemin = racine / p
        if chemin.is_file():
            h.update(p.encode() + b"\0" + chemin.read_bytes() + b"\0")
    return f"{arbre}:{h.hexdigest()}"


def signature(racine: Path = RACINE) -> dict:
    """Environnement qui a produit le résultat : interpréteur, paquets installés et requirements.txt."""
    paquets = sorted(f"{d.metadata['Name'].lower()}=={d.version}" for d in importlib.metadata.distributions())
    req = racine / "requirements.txt"
    return {"python": sys.version, "platform": platform.platform(), "executable": sys.executable,
            "paquets": hashlib.sha256("\n".join(paquets).encode()).hexdigest(),
            "requirements": hashlib.sha256(req.read_bytes()).hexdigest() if req.is_file() else None}


def commandes(python: str = sys.executable, cibles: list[str] | None = None) -> list[list[str]]:
    return [[python, "-m", "pytest", "-q", *(cibles or [])],
            *([python, "scripts/valider.py", "--perimetre", p] for p in PERIMETRES)]


def registre_par_defaut() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or "~/.local/state").expanduser()
    return base / "delta" / "verify-resultats.json"


def lire_registre(path: Path) -> dict:
    try:
        registre = json.loads(path.read_text(encoding="utf-8"))
        return registre if isinstance(registre, dict) else {}
    except (OSError, ValueError):
        return {}  # un registre illisible ne constitue jamais une preuve


def reutilisable(registre: dict, cle: str, contexte: dict) -> dict | None:
    preuve = registre.get(cle)
    return preuve if isinstance(preuve, dict) and preuve.get("ok") is True and preuve.get("contexte") == contexte else None


def sauver(path: Path, cle: str, contexte: dict, rapport: dict) -> None:
    """Enregistre un succès, atomiquement ; deux worktrees qui finissent ensemble gardent chacun leur preuve."""
    if not rapport.get("ok"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        registre = lire_registre(path)
        registre[cle] = {"ok": True, "contexte": contexte, "rapport": rapport, "date": time.time()}
        provisoire = path.with_suffix(".tmp")
        provisoire.write_text(json.dumps(registre, indent=2), encoding="utf-8")
        provisoire.replace(path)


def _prendre(fichiers):
    """La première place libre, sans bloquer ; None si toutes sont prises."""
    for fichier in fichiers:
        try:
            fcntl.flock(fichier, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fichier
        except BlockingIOError:
            pass
    return None


def verrou_machine(dossier: Path | None = None):
    """Deux passages de tests à la fois au plus sur la machine, en priorité basse (incident du 07/10 : six suites
    simultanées, charge 50 sur 4 cœurs). Les autres attendent la première place libre, sans échouer. Un verifier lancé
    par un test (variable héritée) ne reprend pas le verrou. Même verrou que discipline, delta-desktop et console-mur."""
    try:
        os.nice(10)
    except OSError:
        pass
    if os.environ.get("VERIFY_VERROU_TENU"):
        return None
    dossier = dossier or Path(os.environ.get("XDG_STATE_HOME") or "~/.local/state").expanduser()
    dossier.mkdir(parents=True, exist_ok=True)
    fichiers = [(dossier / nom).open("a") for nom in VERROUS]
    tenu = _prendre(fichiers)
    if tenu is None:
        print("VERIFY : deux passages de tests tournent sur la machine ; attente de son tour", flush=True)
        debut = time.perf_counter()
        while tenu is None:  # flock ne sait pas attendre « l'un ou l'autre »
            time.sleep(0.5)
            tenu = _prendre(fichiers)
        print(f"VERIFY : tour obtenu après {time.perf_counter() - debut:.0f} s", flush=True)
    for fichier in fichiers:
        if fichier is not tenu:
            fichier.close()
    os.environ["VERIFY_VERROU_TENU"] = "1"
    return tenu


def lancer(cmds: list[list[str]], racine: Path = RACINE) -> dict:
    """Exécute les commandes dans l'ordre, s'arrête à la première en échec."""
    rapport = {"ok": True, "commandes": []}
    for cmd in cmds:
        t0 = time.perf_counter()
        code = subprocess.run(cmd, cwd=racine).returncode
        rapport["commandes"].append({"cmd": " ".join(cmd[1:] if cmd[0] == sys.executable else cmd),
                                     "code": code, "secondes": round(time.perf_counter() - t0, 2)})
        if code != 0:
            rapport["ok"] = False
            break
    return rapport


def verifier(racine: Path, registre: Path, cmds: list[list[str]], sans_cache: bool = False, verrou=verrou_machine) -> dict:
    """Résultat réutilisé si l'arbre est déjà vérifié, sinon exécution ; le succès n'est enregistré que si rien n'a
    bougé pendant la suite."""
    cle, contexte = cle_arbre(racine), signature(racine)
    debut = time.perf_counter()
    preuve = None if sans_cache else reutilisable(lire_registre(registre), cle, contexte)
    if preuve:
        rapport = {**preuve["rapport"], "reutilise": True}
    else:
        tenu = verrou()  # gardé ouvert jusqu'à la fin des suites
        rapport = {**lancer(cmds, racine), "reutilise": False}
        if rapport["ok"] and cle_arbre(racine) == cle:
            sauver(registre, cle, contexte, rapport)
        elif rapport["ok"]:
            print("VERIFY : le contenu a changé pendant les tests ; résultat non enregistré", flush=True)
        del tenu
    rapport.update(cle=cle, total_secondes=round(time.perf_counter() - debut, 3))
    return rapport


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cibles", nargs="*", help="fichiers de tests ciblés (pytest seul, sans valider.py ni cache)")
    p.add_argument("--sans-cache", action="store_true", help="relancer même si l'arbre est déjà vérifié")
    p.add_argument("--registre", type=Path, help="registre des résultats (défaut : ~/.local/state/delta/verify-resultats.json)")
    p.add_argument("--json", action="store_true", help="écrire le rapport en JSON sur la sortie standard")
    args = p.parse_args(argv)
    if args.cibles:  # test ciblé : jamais enregistré, il ne vaut pas verify complet
        rapport = lancer(commandes(cibles=args.cibles)[:1])
        rapport.update(reutilise=False, cible=True)
        print(f"VERIFY ciblé {'OK' if rapport['ok'] else 'ÉCHEC'} en {rapport['commandes'][-1]['secondes']} s", flush=True)
        return 0 if rapport["ok"] else 1
    rapport = verifier(RACINE, args.registre or registre_par_defaut(), commandes(), args.sans_cache)
    if args.json:
        print(json.dumps(rapport, indent=2))
    print(f"VERIFY {'OK' if rapport['ok'] else 'ÉCHEC'}{' (résultat réutilisé)' if rapport['reutilise'] else ''}"
          f" en {rapport['total_secondes']:.3f} s : {rapport['cle'][:19]}", flush=True)
    return 0 if rapport["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
