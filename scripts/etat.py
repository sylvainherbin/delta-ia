#!/usr/bin/env python3
"""Delta — état volatil des outils de Sylvain (D65) -> docs/data/etat.json.

Relevé sur la machine, au même endroit que versions.py dans /delta :
- Claude Code : modèle et effort par défaut (`~/.claude/settings.json`) ;
- Codex : modèle, effort et niveau de service par défaut (`~/.codex/config.toml`), profils (`~/.codex/<nom>.config.toml`) ;
- serveurs MCP et connecteurs visibles : `claude mcp list` (syntaxe vérifiée par `claude mcp list --help`) lancé dans
  ~/projets et ~/projets/delta-ia, et `mcp_servers` de config.toml ;
- présence et date des instructions globales `~/.claude/CLAUDE.md` et `~/.codex/AGENTS.md`.
Chaque relevé : {valeur, source, raison} ; `raison` est renseignée quand la valeur est null (illisible, absente).
Bloc `comptes` (D93, D71) : quotas recopiés de rapports/usage.json (claude.session_5h, claude.semaine, claude.semaine_fable,
chatgpt.semaine : pct, remise_a_zero, releve_le), seulement si `releves_machine` vaut true dans profil.yaml ; fichier absent ou
illisible : `comptes: {statut: "inconnu", raison}`. Rien de `machine` ni de `wifi`.
`comptes.credits` (D102, D71) : crédit de sessions cloud Claude lu en lecture seule dans le bloc `cloud` de `operer --json etat`
(solde, date du relevé, expiration), jours restants calculés ici ; valeur inconnue = null avec `raison`, jamais devinée.
Aucun secret (REGLES §5) : ni `env`, ni arguments de commande, ni paramètres d'URL.
En fin d'exécution, organisation.py écrit aussi raw/organisation.json (D77), hors --dry-run.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib import profil  # noqa: E402
from deltalib.dates import maintenant_iso  # noqa: E402
import organisation  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
MAISON = Path(os.path.expanduser("~"))
DOSSIERS_MCP = ["~/projets", "~/projets/delta-ia", "~/projets/trading-sim"]
_RE_LIGNE_MCP = re.compile(r"^(?P<nom>.+?): (?P<cible>\S+)(?: \((?P<transport>[A-Za-z]+)\))? - (?P<statut>.+)$")


def releve(valeur, source: str, raison: str | None = None) -> dict:
    return {"valeur": valeur, "source": source, "raison": None if valeur is not None else (raison or "valeur absente")}


def _tilde(p: Path) -> str:
    try:
        return "~/" + str(p.relative_to(MAISON))
    except ValueError:
        return str(p)


def _sans_parametres(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


def lire_json(p: Path) -> tuple[dict | None, str | None]:
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"{_tilde(p)} illisible : {type(e).__name__}"
    except ValueError as e:
        return None, f"{_tilde(p)} : JSON invalide ({e})"


def lire_toml(p: Path) -> tuple[dict | None, str | None]:
    try:
        return tomllib.loads(p.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"{_tilde(p)} illisible : {type(e).__name__}"
    except tomllib.TOMLDecodeError as e:
        return None, f"{_tilde(p)} : TOML invalide ({e})"


def claude_code(maison: Path) -> dict:
    f = maison / ".claude" / "settings.json"
    s, err = lire_json(f)
    src = _tilde(f)
    if s is None:
        return {"modele_par_defaut": releve(None, src, err), "effort_par_defaut": releve(None, src, err)}
    return {"modele_par_defaut": releve(s.get("model"), src, "clé `model` absente : modèle par défaut de Claude Code"),
            "effort_par_defaut": releve(s.get("effortLevel"), src, "clé `effortLevel` absente : effort par défaut du modèle")}


def codex(maison: Path) -> dict:
    f = maison / ".codex" / "config.toml"
    c, err = lire_toml(f)
    src = _tilde(f)
    res = {}
    for champ, cle in (("modele_par_defaut", "model"), ("effort_par_defaut", "model_reasoning_effort"), ("niveau_de_service", "service_tier")):
        res[champ] = releve(c.get(cle) if c else None, src, err or f"clé `{cle}` absente")
    profils = []
    for p in sorted(glob.glob(str(maison / ".codex" / "*.config.toml"))):
        chemin = Path(p)
        pc, perr = lire_toml(chemin)
        profils.append({"nom": chemin.name[: -len(".config.toml")], "fichier": _tilde(chemin),
                        "modele": releve(pc.get("model") if pc else None, _tilde(chemin), perr or "clé `model` absente"),
                        "effort": releve(pc.get("model_reasoning_effort") if pc else None, _tilde(chemin),
                                         perr or "clé `model_reasoning_effort` absente")})
    res["profils"] = {"elements": profils, "source": _tilde(maison / ".codex") + "/<nom>.config.toml",
                      "raison": None if profils else "aucun fichier <nom>.config.toml"}
    serveurs = []
    for nom, m in ((c or {}).get("mcp_servers") or {}).items():
        if not isinstance(m, dict):
            continue
        if m.get("url"):
            serveurs.append({"nom": nom, "transport": "http", "cible": _sans_parametres(str(m["url"]))})
        elif m.get("command"):
            serveurs.append({"nom": nom, "transport": "stdio", "cible": os.path.basename(str(m["command"]))})
    res["serveurs_mcp"] = {"elements": serveurs, "source": src + " [mcp_servers]", "raison": err}
    return res


def _claude_exe() -> str | None:
    return shutil.which("claude") or next((p for p in [str(MAISON / ".local" / "bin" / "claude")] if os.access(p, os.X_OK)), None)


def claude_mcp_list(dossier: Path, exe: str | None, delai: int = 120) -> dict:
    src = f"claude mcp list (dans {_tilde(dossier)})"
    if not exe:
        return {"elements": [], "source": src, "raison": "exécutable `claude` introuvable"}
    aide = subprocess.run([exe, "mcp", "list", "--help"], capture_output=True, text=True, timeout=30)
    if aide.returncode != 0 or "Usage: claude mcp list" not in aide.stdout:
        return {"elements": [], "source": src, "raison": "syntaxe `claude mcp list` non confirmée par --help"}
    if not dossier.is_dir():
        return {"elements": [], "source": src, "raison": "dossier absent"}
    try:
        r = subprocess.run([exe, "mcp", "list"], cwd=dossier, capture_output=True, text=True, timeout=delai)
    except subprocess.TimeoutExpired:
        return {"elements": [], "source": src, "raison": f"délai de {delai} s dépassé"}
    elements = []
    for l in r.stdout.splitlines():
        m = _RE_LIGNE_MCP.match(l.strip())
        if not m or l.startswith("Checking"):
            continue
        nom = m.group("nom")
        elements.append({"nom": nom, "origine": "connecteur claude.ai" if nom.startswith("claude.ai ") else "serveur local",
                         "cible": _sans_parametres(m.group("cible")), "transport": (m.group("transport") or "").lower() or None,
                         "statut": m.group("statut").lstrip("✔✓✗! ").strip()})
    raison = None if elements else (f"code {r.returncode}, aucune ligne reconnue" if r.returncode else "aucun serveur listé")
    return {"elements": elements, "source": src, "raison": raison}


QUOTAS_COMPTES = (("claude", "session_5h"), ("claude", "semaine"), ("claude", "semaine_fable"), ("chatgpt", "semaine"))


def _pct_entier(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= 100:
        return None
    return int(round(v))


def _horodatage(v) -> str | None:
    if not isinstance(v, str) or "T" not in v:
        return None
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return v


def comptes(racine: Path) -> dict:
    """D93 : quotas de rapports/usage.json, recopiés sans rien deviner (champ absent ou invalide = null et raison)."""
    f = racine / "rapports" / "usage.json"
    u, err = lire_json(f)
    if u is None or not isinstance(u, dict):
        return {"statut": "inconnu", "raison": err or "rapports/usage.json : objet JSON attendu"}
    releve_global = _horodatage(u.get("releve_le"))
    quotas = {}
    for produit, nom in QUOTAS_COMPTES:
        brut = (u.get(produit) or {}).get(nom) if isinstance(u.get(produit), dict) else None
        brut = brut if isinstance(brut, dict) else {}
        pct = _pct_entier(brut.get("pct"))
        q = {"pct": pct, "remise_a_zero": _horodatage(brut.get("remise_a_zero")),
             "releve_le": _horodatage(brut.get("releve_le")) or releve_global}
        if pct is None:
            q["raison"] = f"{produit}.{nom}.pct absent ou hors de 0 à 100 dans rapports/usage.json"
        quotas[f"{produit}_{nom}"] = q
    if all(q["pct"] is None for q in quotas.values()):
        return {"statut": "inconnu", "raison": "aucun quota lisible dans rapports/usage.json"}
    return {"statut": "ok", "source": "rapports/usage.json", "releve_le": releve_global, "quotas": quotas}


NOM_CREDIT_CLOUD = "Crédit sessions cloud Claude"


def _solde_usd(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or v < 0:
        return None
    return round(float(v), 2)


def credits_cloud(lire_vue=organisation.lire_vue, maintenant: datetime | None = None) -> list[dict]:
    """D102 : crédit cloud Claude daté, lu dans `operer --json etat` (bloc `cloud`), sans écrire dans OPÉRER ni publier d'identifiant."""
    credit = {"nom": NOM_CREDIT_CLOUD, "solde_usd": None, "releve_le": None, "expire_le": None, "jours_restants": None}
    try:
        cloud = lire_vue("etat").get("cloud")
    except organisation.LectureImpossible as err:
        return [{**credit, "raison": f"OPÉRER illisible : {err}"}]
    if not isinstance(cloud, dict):
        return [{**credit, "raison": "OPÉRER : bloc cloud absent"}]
    solde = _solde_usd(cloud.get("solde"))
    expire = _horodatage(cloud.get("expire"))
    credit.update(solde_usd=solde, expire_le=expire, releve_le=_horodatage(cloud.get("releve_le")) if solde is not None else None)
    if expire is not None:
        try:
            limite = datetime.fromisoformat(expire.replace("Z", "+00:00"))
            if limite.utcoffset() is None:
                credit["expire_le"] = None
            else:
                reste = (limite - (maintenant or datetime.now(timezone.utc))).total_seconds() / 86400
                credit["jours_restants"] = max(int(reste // 1), 0)
        except ValueError:
            credit["expire_le"] = None
    if solde is None:
        credit["raison"] = "aucun solde cloud relevé dans OPÉRER"
    elif credit["expire_le"] is None:
        credit["raison"] = "expiration du crédit inconnue dans OPÉRER"
    return [credit]


def instructions_globales(maison: Path) -> list[dict]:
    res = []
    for nom, chemin in (("CLAUDE.md global", maison / ".claude" / "CLAUDE.md"), ("AGENTS.md global", maison / ".codex" / "AGENTS.md")):
        if chemin.exists():
            date = datetime.fromtimestamp(chemin.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
            res.append({"nom": nom, "fichier": _tilde(chemin), "present": True, "modifie_le": releve(date, "date du fichier")})
        else:
            res.append({"nom": nom, "fichier": _tilde(chemin), "present": False,
                        "modifie_le": releve(None, "date du fichier", "fichier absent")})
    return res


def relever(maison: Path = MAISON, lister_mcp=claude_mcp_list) -> dict:
    exe = _claude_exe()
    return {
        "releve_le": maintenant_iso(),
        "outils": {"Claude Code": claude_code(maison), "Codex": codex(maison)},
        "mcp_claude_code": {d: lister_mcp(Path(os.path.expanduser(d)), exe) for d in DOSSIERS_MCP},
        "instructions_globales": instructions_globales(maison),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="etat.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    etat = {"pertinent_pour_profil": profil.charger(a.racine)["releves_machine"], **relever()}  # D79 : false sans profil.yaml
    if etat["pertinent_pour_profil"]:
        etat["comptes"] = comptes(a.racine)  # D93 : même condition que les relevés de la machine
        etat["comptes"]["credits"] = credits_cloud()  # D102
    texte = json.dumps(etat, ensure_ascii=False, indent=2) + "\n"
    if a.dry_run:
        print(texte)
        return 0
    chemin = a.racine / "docs" / "data" / "etat.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    o = etat["outils"]
    print(f"Claude Code : {o['Claude Code']['modele_par_defaut']['valeur']} | Codex : {o['Codex']['modele_par_defaut']['valeur']} "
          f"({len(o['Codex']['profils']['elements'])} profils) | MCP : "
          + ", ".join(f"{d} {len(v['elements'])}" for d, v in etat["mcp_claude_code"].items()) + f" -> {chemin}")
    try:
        organisation.ecrire_releve(a.racine)
    except Exception as err:
        print(f"! AVERTISSEMENT : organisation OPÉRER non écrite ({err})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
