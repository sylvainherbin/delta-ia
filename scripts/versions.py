#!/usr/bin/env python3
"""Delta — versions installées des outils de Sylvain (D54 à D56) -> docs/data/versions.json.

Détection sur la machine, sans chemin supposé :
- Claude Code : `claude --version` (exécutable trouvé dans le PATH ou via ~/.local/bin, emplacement de l'installateur natif) ;
- Codex CLI : `codex --version` si `codex` est dans le PATH, sinon l'exécutable `codex` livré par le paquet `chatgpt`
  (liste des fichiers du paquet donnée par `dpkg -L`) ;
- ChatGPT Desktop, Claude Desktop : version du paquet Debian (`dpkg-query -W`).
Une version introuvable vaut null, avec la raison.

Dernière version publiée : seulement si une source de Delta la fournit (état, fichiers quotidiens, fichier brut) :
claude-code-changelog pour Claude Code, codex-cli-releases pour Codex CLI. Pour l'app de bureau ChatGPT, la version la
plus haute est lue directement dans le flux de la source openai-changelog-codex-app (champ `version`, même analyseur
que la source) ; ses versions « 26.908 » suivent la numérotation du paquet `chatgpt` 26.917.x (correspondance déduite).
Aucune source de Delta ne publie les versions de Claude Desktop : statut `inconnu`.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.dates import maintenant_iso  # noqa: E402
from deltalib.modeles import cle_version  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
_RE_SEMVER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")


def _executer(cmd: list[str], delai: int = 20) -> tuple[str | None, str | None]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=delai)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{' '.join(cmd)} : {type(e).__name__}"
    if r.returncode != 0:
        return None, f"{' '.join(cmd)} : code {r.returncode}"
    return r.stdout.strip(), None


def paquet_dpkg(nom: str) -> tuple[str | None, str, str | None]:
    if not shutil.which("dpkg-query"):
        return None, "dpkg-query -W", "dpkg-query absent (système non Debian)"
    sortie, err = _executer(["dpkg-query", "-W", "-f=${Version}", nom])
    if err or not sortie:
        return None, f"dpkg-query -W {nom}", err or "paquet non installé"
    return sortie, f"paquet Debian `{nom}` (dpkg-query -W)", None


def claude_code() -> tuple[str | None, str, str | None]:
    exe = shutil.which("claude") or next((p for p in [os.path.expanduser("~/.local/bin/claude")] if os.access(p, os.X_OK)), None)
    if not exe:
        return None, "claude --version", "exécutable `claude` introuvable (PATH, ~/.local/bin)"
    sortie, err = _executer([exe, "--version"])
    m = _RE_SEMVER.search(sortie or "")
    if not m:
        return None, f"{exe} --version", err or f"sortie non reconnue : {sortie!r}"
    return m.group(0), f"`{exe} --version`", None


def codex_cli() -> tuple[str | None, str, str | None]:
    exe = shutil.which("codex")
    origine = "PATH"
    if not exe and shutil.which("dpkg"):
        fichiers, _ = _executer(["dpkg", "-L", "chatgpt"])
        exe = next((f for f in (fichiers or "").splitlines() if f.endswith("/codex") and os.access(f, os.X_OK)), None)
        origine = "paquet chatgpt (dpkg -L)"
    if not exe:
        return None, "codex --version", "exécutable `codex` introuvable (PATH, paquet chatgpt)"
    sortie, err = _executer([exe, "--version"])
    m = _RE_SEMVER.search(sortie or "")
    if not m:
        return None, f"{exe} --version", err or f"sortie non reconnue : {sortie!r}"
    return m.group(0), f"`{exe} --version` ({origine})", None


# ----------------------------------------------------------------------------------------------- dernière version publiée

def _lire(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def versions_publiees(racine: Path, source_id: str, motif: str, perimetre: str) -> list[str]:
    """Versions vues par Delta pour une source : identifiants de l'état, fichier brut, fichiers quotidiens."""
    rx = re.compile(motif)
    res: set[str] = set()
    etat = _lire(racine / "state" / f"{perimetre}.json") or {}
    for ident, v in (etat.get("vus") or {}).items():
        m = rx.fullmatch(ident)
        if m and m.groups() and v.get("source_id") in (source_id, None):  # la version figure dans l'identifiant
            res.add(m.group(1))
    brut = _lire(racine / "raw" / f"{perimetre}-nouveautes.json") or {}
    for n in brut.get("nouveautes", []):
        if n.get("source_id") == source_id and n.get("version"):
            res.add(n["version"])
    for f in glob.glob(str(racine / "docs" / "data" / perimetre / "????-??-??.json")):
        for e in (_lire(Path(f)) or {}).get("elements", []):
            if e.get("version") and any(rx.fullmatch(i) for i in e.get("ids_bruts", [])):
                res.add(e["version"])
    return sorted(res, key=cle_version)


def versions_app_chatgpt(racine: Path, client=None) -> tuple[list[str], str | None]:
    """Versions de l'app de bureau lues dans le flux de openai-changelog-codex-app, avec l'analyseur de la source."""
    from deltalib.analyseurs import json_changelog
    from deltalib.http import Client
    from deltalib.modeles import ErreurSource
    from deltalib.sources import ErreurConfiguration, charger_sources
    try:
        source = next(s for s in charger_sources(racine / "sources.yaml") if s.id == "openai-changelog-codex-app")
    except (StopIteration, ErreurConfiguration, OSError) as e:
        return [], f"source openai-changelog-codex-app introuvable dans sources.yaml : {e or 'absente'}"
    try:
        elements = json_changelog.analyser(source, client or Client()).elements
    except ErreurSource as e:
        return [], f"flux {source.url} en échec : {type(e).__name__}: {e}"
    vs = sorted({e.version for e in elements if e.version and re.fullmatch(r"\d{2}\.\d{3}", e.version)}, key=cle_version)
    if not vs:
        return [], f"aucune version au format AA.MJJ dans {source.url}"
    return vs, None


def _stables(vs: list[str]) -> list[str]:
    return [v for v in vs if "-" not in v]


def comparer(installee: str | None, publiee: str | None, composantes: int | None = None) -> str:
    if not installee or not publiee:
        return "inconnu"
    a, b = installee, publiee
    if composantes:
        a = ".".join(a.split(".")[:composantes])
        b = ".".join(b.split(".")[:composantes])
    return "a_jour" if cle_version(a if re.fullmatch(r"\d+(\.\d+)*(-.*)?", a) else "0") >= cle_version(b) else "en_retard"


def detecter(racine: Path, client=None) -> list[dict]:
    horodatage = maintenant_iso()
    res = []

    def ligne(outil, trouve, publiees, source, composantes=None, note=None, raison_source=None):
        version, methode, raison = trouve
        derniere = publiees[-1] if publiees else None
        raison = "; ".join(x for x in (raison, None if derniere else raison_source) if x) or None
        d = {"outil": outil, "version": version, "detectee_le": horodatage, "methode": methode,
             "derniere_publiee": derniere, "source_derniere": source if derniere else None,
             "statut": comparer(version, derniere, composantes)}
        if raison:
            d["raison"] = raison
        if note:
            d["note"] = note
        res.append(d)

    ligne("Claude Code", claude_code(),
          _stables(versions_publiees(racine, "claude-code-changelog", r"claude-code-(\d+\.\d+\.\d+)", "claude")),
          "claude-code-changelog")
    ligne("Codex CLI", codex_cli(),
          _stables(versions_publiees(racine, "codex-cli-releases", r"rust-v(\d+\.\d+\.\d+)", "openai")),
          "codex-cli-releases",
          note="Livré avec l'app de bureau ChatGPT : il se met à jour avec elle, pas séparément.")
    app, raison_app = versions_app_chatgpt(racine, client)
    ligne("ChatGPT Desktop", paquet_dpkg("chatgpt"), app, "openai-changelog-codex-app", composantes=2,
          note="Correspondance déduite, non documentée par OpenAI : les versions de l'app Codex du changelog (ex. 26.908, "
               "entrée décrivant « the ChatGPT desktop app ») suivent la numérotation du paquet chatgpt ; la comparaison "
               "porte sur les deux premières composantes (26.917.51856 -> 26.917).",
          raison_source=raison_app)
    ligne("Claude Desktop", paquet_dpkg("claude-desktop"), [], None,
          note="Aucune source de Delta ne publie les versions de Claude Desktop.")
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="versions.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    lignes = detecter(a.racine)
    for l in lignes:
        print(f"{l['outil']:<16} {str(l['version']):<22} dernière publiée {str(l['derniere_publiee']):<10} {l['statut']:<9} "
              f"| {l['methode']}" + (f" | {l['raison']}" if l.get("raison") else ""))
    if not a.dry_run:
        chemin = a.racine / "docs" / "data" / "versions.json"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(lignes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"-> {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
