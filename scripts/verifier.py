#!/usr/bin/env python3
"""Contrôle avant commit (D87) : pytest puis valider.py sur les trois périmètres, jamais deux fois sur le même arbre.
Preuve de fusion (D94, CI-PREUVE) : `--cible` lance les seuls tests touchés par le diff contre origin/main (carte.py),
`--ci` lit le run GitHub Actions vert du hash exact de la branche (locale, sinon `origin/<branche>`), `--local` lance ce que la CI ne fait pas (tests marqués
`local`) ; la suite complète locale n'est que le repli sans CI verte exploitable.

Un succès est enregistré sous une clé qui décrit le contenu réellement testé (arbre git du répertoire de travail,
fichiers non suivis non ignorés compris) et l'environnement Python. Un commit ou un rebase sans changement de contenu
donne la même clé, donc le même résultat. Un échec n'est jamais enregistré.
Les suites passent par le verrou machine commun (VERROU-COMMUN, D94) : `verifier.py` se relance lui-même sous
`verrou-tests` (file FIFO, deux places, nice 10) ; la réutilisation d'un résultat n'attend aucun verrou.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import carte

RACINE = Path(__file__).resolve().parent.parent
PERIMETRES = ("claude", "openai", "actu")
# Sorties locales de travail : ce ne sont pas des entrées des tests.
IGNORES = (".tmp-", ".codex-commit-")
VERROU_TESTS = "verrou-tests"  # lanceur commun (~/.local/bin, dépôt discipline) : même file FIFO que les autres dépôts
NOM_VERROU = "delta-ia"
CODE_FILE_PLEINE = 75  # deux passages de ce dépôt attendent déjà : sortie rendue telle quelle


def git(*args: str, racine: Path = RACINE) -> bytes:
    return subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True).stdout


def cle_arbre(racine: Path = RACINE) -> str:
    """Empreinte git (`write-tree`) du contenu réel du répertoire de travail : fichiers suivis, modifiés ou non, et fichiers
    non suivis non ignorés, calculée dans un index temporaire (l'index réel n'est jamais touché). Un commit, un rebase ou un
    amend qui ne change pas le contenu donnent la même clé ; sur un arbre propre, c'est `HEAD^{tree}`."""
    index = Path(git("rev-parse", "--git-path", "index", racine=racine).decode().strip())
    index = index if index.is_absolute() else racine / index
    with tempfile.TemporaryDirectory(prefix="verifier-index-") as tmp:
        copie = Path(tmp) / "index"
        if index.is_file():
            shutil.copyfile(index, copie)
        env = {**os.environ, "GIT_INDEX_FILE": str(copie)}
        exclus = [f":(exclude){p}*" for p in IGNORES]
        for args in (["add", "-A", "--", ".", *exclus], ["write-tree"]):
            res = subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True, env=env)
        return res.stdout.decode().strip()


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


def fichiers_touches(racine: Path = RACINE, base: str = "origin/main") -> list[str]:
    """Fichiers qui diffèrent de `base` depuis l'ancêtre commun (commits de la branche, modifications non commitées et
    fichiers non suivis non ignorés). L'ancêtre commun évite de compter comme changements ceux que `base` a reçus depuis."""
    ancetre = git("merge-base", base, "HEAD", racine=racine).decode().strip()
    suivis = git("diff", "--name-only", ancetre, racine=racine).decode().splitlines()
    autres = git("ls-files", "--others", "--exclude-standard", racine=racine).decode().splitlines()
    return sorted({p for p in suivis + autres if not p.startswith(IGNORES)})


def commandes_cible(selection: dict, python: str = sys.executable) -> list[list[str]]:
    """pytest sur les seuls tests désignés (jamais la suite complète), puis valider.py si la sélection l'exige."""
    cmds = [[python, "-m", "pytest", "-q", *selection["tests"]]] if selection["tests"] else []
    if selection["valider"]:
        cmds += [[python, "scripts/valider.py", "--perimetre", p] for p in PERIMETRES]
    return cmds


def commandes_local(python: str = sys.executable) -> list[list[str]]:
    return [[python, "-m", "pytest", "-q", "-m", "local"]]


def preuve_ci(branche: str, sha: str, runs: list[dict]) -> tuple[bool, str]:
    """Une CI verte exploitable est un run terminé `success` dont le `headSha` est exactement `sha` (pas le dernier run
    de la branche). Sinon le message dit pourquoi, et le repli est la suite complète locale."""
    pour_sha = [r for r in runs if r.get("headSha") == sha]
    if any(r.get("conclusion") == "success" for r in pour_sha):
        return True, f"CI verte sur {sha[:12]} ({branche})"
    if not pour_sha:
        return False, f"aucun run CI pour {sha[:12]} ({branche}) : branche non poussée ou run pas encore créé ; repli : suite complète locale"
    if any(r.get("status") != "completed" for r in pour_sha):
        return False, f"run CI de {sha[:12]} en cours ; attendre sa fin, ou repli : suite complète locale"
    conclusions = ", ".join(sorted({str(r.get("conclusion")) for r in pour_sha}))
    return False, f"CI non verte sur {sha[:12]} ({conclusions}) ; corriger, ou repli : suite complète locale"


def hash_branche(branche: str, racine: Path = RACINE) -> str:
    """Hash de la branche locale, sinon de `origin/<branche>` (branche poussée depuis un autre worktree ou une autre session,
    absente en local). `ValueError` si ni l'une ni l'autre n'existe."""
    for ref in (branche, f"origin/{branche}"):
        res = subprocess.run(["git", "-C", str(racine), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                             capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    raise ValueError(f"branche {branche} introuvable (ni locale, ni origin/{branche})")


def lire_runs_ci(branche: str, racine: Path = RACINE) -> list[dict]:
    sortie = subprocess.run(["gh", "run", "list", "--branch", branche, "--limit", "30", "--json", "conclusion,headSha,status,url"],
                            cwd=racine, check=True, capture_output=True, text=True, timeout=60).stdout
    runs = json.loads(sortie)
    return runs if isinstance(runs, list) else []


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


def verrou_commun(argv: list[str], racine: Path = RACINE) -> None:
    """Une seule prise du verrou machine par exécution (VERROU-COMMUN) : l'exécution se relance sous
    `verrou-tests --depot <racine> --nom delta-ia -- verifier.py <argv>` et sort avec son code, rendu tel quel (75 : deux
    passages de ce dépôt attendent déjà, sans contournement). Le lanceur est le seul exemplaire de la file (tickets FIFO,
    deux places, nice 10 posé par le lanceur, source : discipline/outils/tests/verrou.py). Sous `VERIFY_VERROU_TENU` hérité (la relance, ou
    un test lancé sous un verrou), aucune seconde prise : retour immédiat."""
    if os.environ.get("VERIFY_VERROU_TENU"):
        return
    lanceur = shutil.which(VERROU_TESTS)
    if not lanceur:
        print(f"VERIFY : {VERROU_TESTS} introuvable (~/.local/bin, dépôt discipline) ; aucun verrou local de rechange, "
              "installer le lanceur commun", flush=True)
        raise SystemExit(127)
    cmd = [lanceur, "--depot", str(racine), "--nom", NOM_VERROU, "--", sys.executable, str(Path(__file__).resolve()), *argv]
    code = subprocess.run(cmd).returncode
    if code == CODE_FILE_PLEINE:
        print(f"VERIFY : file du verrou commun pleine (code {CODE_FILE_PLEINE}) ; relancer plus tard", flush=True)
    raise SystemExit(code)


def lancer(cmds: list[list[str]], racine: Path = RACINE, codes_ok: tuple[int, ...] = (0,)) -> dict:
    """Exécute les commandes dans l'ordre, s'arrête à la première en échec (code hors `codes_ok`)."""
    rapport = {"ok": True, "commandes": []}
    for cmd in cmds:
        t0 = time.perf_counter()
        code = subprocess.run(cmd, cwd=racine).returncode
        rapport["commandes"].append({"cmd": " ".join(cmd[1:] if cmd[0] == sys.executable else cmd),
                                     "code": code, "secondes": round(time.perf_counter() - t0, 2)})
        if code not in codes_ok:
            rapport["ok"] = False
            break
    return rapport


def verifier(racine: Path, registre: Path, cmds: list[list[str]], sans_cache: bool = False, verrou=lambda: None) -> dict:
    """Résultat réutilisé si l'arbre est déjà vérifié, sinon exécution ; le succès n'est enregistré que si rien n'a
    bougé pendant la suite."""
    cle, contexte = cle_arbre(racine), signature(racine)
    debut = time.perf_counter()
    preuve = None if sans_cache else reutilisable(lire_registre(registre), cle, contexte)
    if preuve:
        rapport = {**preuve["rapport"], "reutilise": True}
    else:
        verrou()  # relance sous le verrou commun (ne revient que s'il est déjà tenu)
        rapport = {**lancer(cmds, racine), "reutilise": False}
        if rapport["ok"] and cle_arbre(racine) == cle:
            sauver(registre, cle, contexte, rapport)
        elif rapport["ok"]:
            print("VERIFY : le contenu a changé pendant les tests ; résultat non enregistré", flush=True)
    rapport.update(cle=cle, total_secondes=round(time.perf_counter() - debut, 3))
    return rapport


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cibles", nargs="*", help="fichiers de tests ciblés (pytest seul, sans valider.py ni cache)")
    p.add_argument("--sans-cache", action="store_true", help="relancer même si l'arbre est déjà vérifié")
    p.add_argument("--registre", type=Path, help="registre des résultats (défaut : ~/.local/state/delta/verify-resultats.json)")
    p.add_argument("--cible", action="store_true", help="tests touchés par le diff contre --base (carte.py), jamais la suite complète")
    p.add_argument("--base", default="origin/main", help="référence du diff de --cible (défaut origin/main)")
    p.add_argument("--liste", action="store_true", help="avec --cible : afficher la sélection sans rien lancer")
    p.add_argument("--ci", nargs="?", const="", metavar="BRANCHE", help="lire la CI GitHub : code 0 si un run vert a le hash exact de la branche (défaut : branche courante), 1 sinon (repli : suite complète)")
    p.add_argument("--local", action="store_true", help="seulement les tests marqués `local` (ce que la CI ne fait pas) ; aucun test marqué n'est un succès")
    p.add_argument("--json", action="store_true", help="écrire le rapport en JSON sur la sortie standard")
    args = p.parse_args(argv)
    if args.ci is not None:
        branche = args.ci or git("branch", "--show-current", racine=RACINE).decode().strip()
        try:
            ok, message = preuve_ci(branche, hash_branche(branche, RACINE), lire_runs_ci(branche, RACINE))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            ok, message = False, f"CI illisible ({exc}) ; repli : suite complète locale"
        print(f"VERIFY CI {'OK' if ok else 'NON EXPLOITABLE'} : {message}", flush=True)
        return 0 if ok else 1
    if args.local:
        verrou_commun(argv)
        rapport = lancer(commandes_local(), codes_ok=(0, 5))  # 5 : aucun test marqué `local`
        print(f"VERIFY local {'OK' if rapport['ok'] else 'ÉCHEC'} en {rapport['commandes'][-1]['secondes']} s", flush=True)
        return 0 if rapport["ok"] else 1
    if args.cible:
        touches = fichiers_touches(RACINE, args.base)
        selection = carte.selectionner(carte.generer(RACINE), touches)
        cmds = commandes_cible(selection)
        if cmds and not args.liste:
            verrou_commun(argv)  # avant d'écrire la sélection : la relance la recalcule et l'écrit une seule fois
        print(f"VERIFY ciblé : {len(touches)} fichier(s) touché(s) contre {args.base}, {len(selection['tests'])} test(s)"
              f"{', valider.py' if selection['valider'] else ''}", flush=True)
        for raison in selection["raisons"]:
            print(f"  - {raison}", flush=True)
        if args.liste or not cmds:
            if not cmds:
                print("VERIFY ciblé OK : rien à lancer", flush=True)
            return 0
        rapport = {**lancer(cmds), "reutilise": False, "cible": True}
        print(f"VERIFY ciblé {'OK' if rapport['ok'] else 'ÉCHEC'} en {sum(c['secondes'] for c in rapport['commandes']):.1f} s "
              f"(la CI sur le hash exact fait foi pour la fusion)", flush=True)
        return 0 if rapport["ok"] else 1
    if args.cibles:  # test ciblé : jamais enregistré, il ne vaut pas verify complet
        verrou_commun(argv)
        rapport = lancer(commandes(cibles=args.cibles)[:1])
        rapport.update(reutilise=False, cible=True)
        print(f"VERIFY ciblé {'OK' if rapport['ok'] else 'ÉCHEC'} en {rapport['commandes'][-1]['secondes']} s", flush=True)
        return 0 if rapport["ok"] else 1
    rapport = verifier(RACINE, args.registre or registre_par_defaut(), commandes(), args.sans_cache, lambda: verrou_commun(argv))
    if args.json:
        print(json.dumps(rapport, indent=2))
    print(f"VERIFY {'OK' if rapport['ok'] else 'ÉCHEC'}{' (résultat réutilisé)' if rapport['reutilise'] else ''}"
          f" en {rapport['total_secondes']:.3f} s : {rapport['cle'][:19]}", flush=True)
    return 0 if rapport["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
