#!/usr/bin/env python3
"""Delta — garde du passage /delta automatique (D68). Lecture seule : ce script n'écrit rien.

Contrôles, dans l'ordre :
1. `.git/index.lock` présent : un autre passage ou une autre session tient le dépôt (D21) -> arrêt, code 10.
2. `rapports/usage.json` (console-mur) : `claude.session_5h.pct` >= 80 ou `claude.semaine.pct` >= 85 -> arrêt,
   code 11. Fichier absent, illisible ou modifié il y a plus de 15 minutes : la console est sans doute arrêtée ;
   les pourcentages ne sont plus fiables, le passage continue et l'avertissement est signalé (code 0).
3. `docs/data/claude/<J>.json` a déjà un `genere_le` daté du jour J (heure locale) : passage déjà fait -> arrêt,
   code 12.

Code 0 : le passage peut tourner (éventuels avertissements affichés). Code 2 : argument invalide.
Sortie : une ligne par contrôle, puis `GARDE: OK` ou `GARDE: ARRÊT (<motif>)` ; `--json` pour un bilan structuré.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SEUIL_SESSION_5H = 80
SEUIL_SEMAINE = 85
FRAICHEUR_MAX_MIN = 15
CODE_VERROU, CODE_QUOTA, CODE_DEJA_FAIT = 10, 11, 12


def _pct(d: dict, *cles) -> float | None:
    for c in cles:
        d = d.get(c) if isinstance(d, dict) else None
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else None


def controler(racine: Path, jour: date, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    res = {"jour": jour.isoformat(), "code": 0, "motif": None, "controles": [], "avertissements": []}

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

    # 2. quotas Claude (console-mur)
    usage = racine / "rapports" / "usage.json"
    try:
        age_min = (maintenant.timestamp() - usage.stat().st_mtime) / 60
        u = json.loads(usage.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        res["avertissements"].append(f"usage.json absent ou illisible ({type(e).__name__}) : quotas inconnus, console arrêtée ?")
        res["controles"].append("quotas : inconnus (usage.json absent ou illisible) — le passage continue")
    else:
        s5, sem = _pct(u, "claude", "session_5h", "pct"), _pct(u, "claude", "semaine", "pct")
        if age_min > FRAICHEUR_MAX_MIN:
            res["avertissements"].append(f"usage.json modifié il y a {age_min:.0f} min (> {FRAICHEUR_MAX_MIN}) : console arrêtée ? "
                                         f"quotas non fiables (dernières valeurs : session 5 h {s5} %, semaine {sem} %)")
            res["controles"].append(f"quotas : relevé périmé ({age_min:.0f} min) — le passage continue")
        elif s5 is None or sem is None:
            res["avertissements"].append("usage.json sans claude.session_5h.pct ou claude.semaine.pct : quotas inconnus")
            res["controles"].append("quotas : champs absents — le passage continue")
        elif s5 >= SEUIL_SESSION_5H or sem >= SEUIL_SEMAINE:
            res["controles"].append(f"quotas : session 5 h {s5} % (seuil {SEUIL_SESSION_5H}), semaine {sem} % (seuil {SEUIL_SEMAINE}) — arrêt")
            arret(CODE_QUOTA, f"quota Claude : session 5 h {s5} %, semaine {sem} %")
        else:
            res["controles"].append(f"quotas : session 5 h {s5} %, semaine {sem} % (relevé il y a {age_min:.0f} min)")

    # 3. passage claude du jour déjà fait
    quotidien = racine / "docs" / "data" / "claude" / f"{jour.isoformat()}.json"
    genere = None
    if quotidien.exists():
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
    if fait:
        res["controles"].append(f"passage du jour : déjà fait (genere_le {genere}) — arrêt")
        arret(CODE_DEJA_FAIT, f"passage claude du {jour.isoformat()} déjà fait ({genere})")
    else:
        res["controles"].append("passage du jour : pas encore fait")
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="garde.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", help="date du passage J, AAAA-MM-JJ (défaut : aujourd'hui)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        jour = date.fromisoformat(a.date) if a.date else date.today()
    except ValueError:
        print(f"garde.py : date invalide {a.date!r} (AAAA-MM-JJ attendu)", file=sys.stderr)
        return 2
    res = controler(a.racine, jour)
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
