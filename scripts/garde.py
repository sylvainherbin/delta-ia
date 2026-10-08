#!/usr/bin/env python3
"""Delta — garde du passage /delta automatique (D68). Lecture seule : ce script n'écrit rien.

Contrôles, dans l'ordre :
1. `.git/index.lock` présent : un autre passage ou une autre session tient le dépôt (D21) -> arrêt, code 10.
1 bis. D70 : `.git/delta-passage.lock` tenu (flock) par l'orchestrateur `scripts/passage-auto.sh` et cet appel n'en fait pas
   partie -> arrêt, code 14. La garde teste le verrou, elle ne le prend pas (ouverture en lecture seule, flock non bloquant,
   relâché aussitôt). Un appel de la chaîne s'identifie par `DELTA_CHAINE_PID`, égal au PID écrit dans le fichier de verrou.
2. `rapports/usage.json` (console-mur) : `claude.session_5h.pct` >= 80 ou `claude.semaine.pct` >= 98 -> arrêt,
   code 11. Fichier absent, illisible ou modifié il y a plus de 15 minutes : la console est sans doute arrêtée ;
   les pourcentages ne sont plus fiables, le passage continue et l'avertissement est signalé (code 0).
   D71 : un fichier absent, illisible ou sans `claude.session_5h.pct` / `claude.semaine.pct` (la console le réécrit) est relu
   une seule fois après 3 s ; s'il reste incomplet, comportement inchangé (« quotas inconnus », aucun arrêt nouveau).
   D71 : `claude.semaine.pct` ou `chatgpt.semaine.pct` >= 80 ajoute un avertissement, sans arrêt, même sur un relevé périmé
   (mention « relevé périmé, il y a N min ») ; ChatGPT n'arrête jamais le passage. Quotas Claude inconnus : l'avertissement
   ajoute « vérifie tes quotas et remises à zéro Claude dans Paramètres > Utilisation (D71) ».
3. `docs/data/claude/<J>.json` a déjà un `genere_le` daté du jour J (heure locale) : passage déjà fait -> arrêt,
   code 12.
4. Arbre de travail : fichier suivi modifié (indexé ou non), ou fichier non suivi dans les chemins du passage
   (`docs/data/claude/`, `docs/data/actu/`, `state/`) -> arrêt, code 13, avec la liste des fichiers. Un reste
   d'arrêt (versions.json, etat.json, fichier du jour non commité) ou un CONTEXTE.md non commité bloquerait le pull.

5. D70 : au moins un commit local absent de `origin/main` (`git rev-list --count origin/main..HEAD`) -> arrêt, code 15 :
   une étape ne doit jamais pousser le commit non validé d'une autre. Sans `origin/main` (dépôt sans distant, tests), non évalué.

`--etape {delta,codex-delta,delta-kb,codex-delta-kb}` (D70) adapte les contrôles 2 et 3 à l'étape de la chaîne : le quota
Claude (code 11) ne vaut que pour les étapes Claude ; le code 12 regarde le fichier du jour de l'étape (`delta` : claude,
`codex-delta` : openai) et n'existe pas pour les étapes kb. Sans `--etape`, comportement D68 (quota Claude, fichier claude).

Code 0 : le passage peut tourner (éventuels avertissements affichés). Code 2 : argument invalide.
Sortie : une ligne par contrôle, puis `GARDE: OK` ou `GARDE: ARRÊT (<motif>)` ; `--json` pour un bilan structuré.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SEUIL_SESSION_5H = 80
SEUIL_SEMAINE = 98
SEUIL_ALERTE_HEBDO = 80  # D71 : avertissement seulement, sur Claude et sur ChatGPT
FRAICHEUR_MAX_MIN = 15
DELAI_RELECTURE_S = 3  # console-mur réécrit usage.json : un champ absent une fois est relu une seule fois après ce délai
RAPPEL_CLAUDE = "vérifie tes quotas et remises à zéro Claude dans Paramètres > Utilisation (D71)"
CODE_VERROU, CODE_QUOTA, CODE_DEJA_FAIT, CODE_ARBRE, CODE_CHAINE, CODE_NON_POUSSE = 10, 11, 12, 13, 14, 15
CHEMINS_PASSAGE = ("docs/data/claude/", "docs/data/actu/", "docs/data/openai/", "docs/data/kb/", "docs/data/semaine/", "state/")
VERROU_CHAINE = Path(".git") / "delta-passage.lock"
# D70 : par étape de la chaîne, (quota Claude applicable, dossier de données du fichier du jour pour le code 12 ou None)
ETAPES = {"delta": (True, "claude"), "codex-delta": (False, "openai"), "delta-kb": (True, None), "codex-delta-kb": (False, None)}
# D83 : avec --etape, le code 13 ne regarde que les chemins qu'écrit l'étape (SPEC §3) ; sans --etape, tous les chemins de passage
_CLAUDE = ("docs/data/claude/", "docs/data/actu/", "docs/data/kb/claude/", "docs/data/kb/recent.json", "docs/data/kb/a-tester.json", "docs/data/kb/noms.json", "docs/data/versions.json", "docs/data/etat.json",
           "docs/data/semaine/", "state/claude.json", "state/actu.json")
_OPENAI = ("docs/data/openai/", "docs/data/kb/openai/", "docs/data/kb/recent.json", "docs/data/kb/a-tester.json", "docs/data/kb/noms.json", "state/openai.json")  # D99 : recent.json est dérivé des deux bases
CHEMINS_ETAPE = {"delta": _CLAUDE, "delta-kb": ("docs/data/kb/claude/", "docs/data/kb/recent.json", "docs/data/kb/a-tester.json", "docs/data/kb/noms.json"), "codex-delta": _OPENAI,
                 "codex-delta-kb": ("docs/data/kb/openai/", "docs/data/kb/recent.json", "docs/data/kb/a-tester.json", "docs/data/kb/noms.json")}


def _pct(d: dict, *cles) -> float | None:
    for c in cles:
        d = d.get(c) if isinstance(d, dict) else None
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else None


def _dormir(secondes: float) -> None:  # remplacé dans les tests : aucune attente réelle
    time.sleep(secondes)


def _lire_usage(usage: Path, maintenant: datetime):
    """(âge en minutes, contenu, erreur) ; complet = session 5 h et semaine de Claude présentes."""
    try:
        age_min = (maintenant.timestamp() - usage.stat().st_mtime) / 60
        u = json.loads(usage.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, None, e
    return age_min, u, None


def _complet(u) -> bool:
    return u is not None and _pct(u, "claude", "session_5h", "pct") is not None and _pct(u, "claude", "semaine", "pct") is not None


def verrou_chaine(racine: Path) -> tuple[bool, int | None]:
    """(tenu, pid écrit dans le fichier) ; lecture seule : le fichier n'est ni créé ni modifié."""
    chemin = racine / VERROU_CHAINE
    try:
        fd = os.open(chemin, os.O_RDONLY)
    except OSError:
        return False, None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                return True, int(os.read(fd, 32).decode().strip() or 0) or None
            except ValueError:
                return True, None
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False, None
    finally:
        os.close(fd)


def commits_non_pousses(racine: Path) -> int | None:
    """Nombre de commits locaux absents de origin/main ; None si origin/main n'existe pas ou git est illisible."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(racine), "rev-list", "--count", "origin/main..HEAD"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def controler(racine: Path, jour: date, maintenant: datetime | None = None, delai_relecture: float = DELAI_RELECTURE_S,
              etape: str | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    res = {"jour": jour.isoformat(), "etape": etape, "code": 0, "motif": None, "controles": [], "avertissements": [],
           "fichiers_modifies": []}
    quota_claude, dossier_jour = ETAPES[etape] if etape else (True, "claude")

    def arret(code, motif):
        if not res["code"]:
            res["code"], res["motif"] = code, motif

    # 1. verrou git
    verrou = racine / ".git" / "index.lock"
    if verrou.exists():
        res["controles"].append(f"verrou : .git/index.lock présent — arrêt (D21)")
        arret(CODE_VERROU, "verrou .git/index.lock")
    else:
        res["controles"].append("verrou : absent")

    # 1 bis. verrou de la chaîne (D70)
    tenu, pid = verrou_chaine(racine)
    if not tenu:
        res["controles"].append("chaîne : verrou absent")
    elif pid is not None and os.environ.get("DELTA_CHAINE_PID") == str(pid):
        res["controles"].append(f"chaîne : verrou tenu par l'orchestrateur (pid {pid}), cet appel en fait partie")
    else:
        res["controles"].append(f"chaîne : .git/delta-passage.lock tenu (pid {pid or 'inconnu'}) par une autre chaîne — arrêt (D70)")
        arret(CODE_CHAINE, "chaîne de passages en cours (.git/delta-passage.lock)")

    # 2. quotas Claude (console-mur)
    usage = racine / "rapports" / "usage.json"
    age_min, u, erreur = _lire_usage(usage, maintenant)
    if not _complet(u):  # D71 : le fichier est réécrit par la console ; une seule relecture, après un délai court et borné
        _dormir(delai_relecture)
        age_min, u, erreur = _lire_usage(usage, maintenant)
    if erreur is not None:
        res["avertissements"].append(f"usage.json absent ou illisible ({type(erreur).__name__}) : quotas inconnus, console arrêtée ? {RAPPEL_CLAUDE}")
        res["controles"].append("quotas : inconnus (usage.json absent ou illisible) — le passage continue")
    else:
        s5, sem = _pct(u, "claude", "session_5h", "pct"), _pct(u, "claude", "semaine", "pct")
        if age_min > FRAICHEUR_MAX_MIN:
            res["avertissements"].append(f"usage.json modifié il y a {age_min:.0f} min (> {FRAICHEUR_MAX_MIN}) : console arrêtée ? "
                                         f"quotas non fiables (dernières valeurs : session 5 h {s5} %, semaine {sem} %)")
            res["controles"].append(f"quotas : relevé périmé ({age_min:.0f} min) — le passage continue")
        elif s5 is None or sem is None:
            res["avertissements"].append(f"usage.json sans claude.session_5h.pct ou claude.semaine.pct : quotas inconnus. {RAPPEL_CLAUDE}")
            res["controles"].append("quotas : champs absents — le passage continue")
        elif quota_claude and (s5 >= SEUIL_SESSION_5H or sem >= SEUIL_SEMAINE):
            res["controles"].append(f"quotas : session 5 h {s5} % (seuil {SEUIL_SESSION_5H}), semaine {sem} % (seuil {SEUIL_SEMAINE}) — arrêt")
            arret(CODE_QUOTA, f"quota Claude : session 5 h {s5} %, semaine {sem} %")
        else:
            res["controles"].append(f"quotas : session 5 h {s5} %, semaine {sem} % (relevé il y a {age_min:.0f} min)")
        # D71 : l'alerte vaut aussi sur un relevé périmé (avertissement seulement, jamais d'arrêt sur un relevé périmé)
        perime = f" (relevé périmé, il y a {age_min:.0f} min)" if age_min > FRAICHEUR_MAX_MIN else ""
        for produit, pct in (("Claude", sem), ("ChatGPT", _pct(u, "chatgpt", "semaine", "pct"))):
            if pct is not None and pct >= SEUIL_ALERTE_HEBDO:
                res["avertissements"].append(f"quota hebdomadaire {produit} à {pct:g} %{perime} — vérifie tes remises à zéro disponibles "
                                             "(Paramètres > Utilisation) avant d'économiser (D71)")

    # 3. passage du jour déjà fait (fichier du jour de l'étape : claude par défaut, openai pour codex-delta, aucun pour les étapes kb)
    quotidien = racine / "docs" / "data" / dossier_jour / f"{jour.isoformat()}.json" if dossier_jour else None
    genere = None
    if quotidien is not None and quotidien.exists():
        try:
            genere = json.loads(quotidien.read_text(encoding="utf-8")).get("genere_le")
        except (OSError, ValueError):
            genere = None
    fait = False
    if isinstance(genere, str):
        try:
            g = datetime.fromisoformat(genere.replace("Z", "+00:00"))
            fait = (g.astimezone() if g.tzinfo else g).date() == jour
        except ValueError:
            fait = False
    if dossier_jour is None:
        res["controles"].append("passage du jour : sans objet pour cette étape")
    elif fait:
        res["controles"].append(f"passage du jour : déjà fait (genere_le {genere}) — arrêt")
        arret(CODE_DEJA_FAIT, f"passage {dossier_jour} du {jour.isoformat()} déjà fait ({genere})")
    else:
        res["controles"].append("passage du jour : pas encore fait")

    # 4. arbre de travail (git en lecture seule)
    try:
        sortie = subprocess.run(["git", "--no-optional-locks", "-C", str(racine), "status", "--porcelain=v1", "--untracked-files=all"],
                                capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        res["controles"].append(f"arbre de travail : état git illisible ({type(e).__name__}) — arrêt")
        arret(CODE_ARBRE, "état git illisible")
        return res  # sans état git, les commits non poussés ne se lisent pas non plus
    sales = []
    chemins_etape = CHEMINS_ETAPE.get(etape)
    for ligne in sortie.splitlines():
        etat, chemin = ligne[:2], ligne[3:].split(" -> ")[-1]
        if chemins_etape is not None and not chemin.startswith(chemins_etape):
            continue
        if etat == "??":
            if chemin.startswith(CHEMINS_PASSAGE):
                sales.append(f"{chemin} (non suivi)")
        elif etat.strip():
            sales.append(f"{chemin} ({etat.strip()})")
    res["fichiers_modifies"] = sales
    if sales:
        res["controles"].append(f"arbre de travail : {len(sales)} fichier(s) modifié(s) — arrêt : " + ", ".join(sales))
        arret(CODE_ARBRE, f"arbre de travail non propre ({len(sales)} fichier(s))")
    else:
        res["controles"].append("arbre de travail : propre")

    # 5. commits locaux non poussés (D70)
    n = commits_non_pousses(racine)
    if n is None:
        res["controles"].append("commits non poussés : non évalué (pas de origin/main)")
    elif n > 0:
        res["controles"].append(f"commits non poussés : {n} commit(s) local(aux) absent(s) de origin/main — arrêt (D70)")
        arret(CODE_NON_POUSSE, f"{n} commit(s) local(aux) non poussé(s)")
    else:
        res["controles"].append("commits non poussés : aucun")
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="garde.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", help="date du passage J, AAAA-MM-JJ (défaut : aujourd'hui)")
    p.add_argument("--etape", choices=sorted(ETAPES), help="étape de la chaîne D70 (adapte le quota Claude et le fichier du jour)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        jour = date.fromisoformat(a.date) if a.date else date.today()
    except ValueError:
        print(f"garde.py : date invalide {a.date!r} (AAAA-MM-JJ attendu)", file=sys.stderr)
        return 2
    res = controler(a.racine, jour, etape=a.etape)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for c in res["controles"]:
            print(f"- {c}")
        for w in res["avertissements"]:
            print(f"! AVERTISSEMENT : {w}")
        print("GARDE: OK" if res["code"] == 0 else f"GARDE: ARRÊT ({res['motif']}) — code {res['code']}")
    return res["code"]


if __name__ == "__main__":
    sys.exit(main())
