"""Racines d'instance des deux couches (conception §2.1), résolues une seule fois.

Trois sources, sans découverte implicite d'une autre instance :
- profil d'instance K1 (`delta.instance` v1 de Discipline, `--instance <profil.json>`) : ses racines déclarées, sinon
  `<home>/<défaut>/<identite>` comme `ContexteInstance` ;
- environnement d'une instance lancée par K1 (`DELTA_INSTANCE` posée) : `ContexteInstance.environnement()` y fait pointer
  `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` et `XDG_RUNTIME_DIR` sur les racines de l'instance ;
- installation historique, sur demande explicite (`historique=True`) : racines XDG existantes suffixées de `delta`
  (`~/.local/state/delta`, `~/.cache/delta`…), là où vivent déjà OPÉRER et ses états.
Les emplacements du composant `delta-ia` sont relatifs à ces racines ; aucun chemin personnel n'est codé en dur.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

COMPOSANT = "delta-ia"
# Mêmes défauts que discipline:src/delta/portabilite/instance.py (RACINES), limités aux quatre racines utilisées ici.
DEFAUTS_K1 = {"configuration": ".config/delta", "etat": ".local/state/delta", "cache": ".cache/delta",
              "runtime": ".local/run/delta"}
CHAMPS_K1 = {"schema", "version", "identite", "mode", "home", "racines", "executables", "path", "venv",
             "prefixe_node", "superviseur", "composants", "projets"}
RACINES_K1 = {"code", "configuration", "etat", "cache", "runtime", "lanceurs"}
XDG = {"configuration": ("XDG_CONFIG_HOME", ".config"), "etat": ("XDG_STATE_HOME", ".local/state"),
       "cache": ("XDG_CACHE_HOME", ".cache"), "runtime": ("XDG_RUNTIME_DIR", ".local/run")}


class RacinesInvalides(ValueError):
    """Aucune source de racines explicite, ou profil d'instance illisible."""


@dataclass(frozen=True)
class Racines:
    configuration: Path
    etat: Path
    cache: Path
    runtime: Path
    origine: str  # « instance », « environnement » ou « historique »

    @property
    def config(self) -> Path:
        return self.configuration / COMPOSANT / "config.json"

    @property
    def personnel(self) -> Path:
        return self.etat / COMPOSANT / "personnel"

    @property
    def production(self) -> Path:
        return self.etat / COMPOSANT / "production"

    @property
    def commun(self) -> Path:
        return self.cache / COMPOSANT / "commun"

    @property
    def commun_actif(self) -> Path:
        return self.etat / COMPOSANT / "commun-actif.json"

    @property
    def index(self) -> Path:
        return self.cache / COMPOSANT / "index"

    @property
    def verrous(self) -> Path:
        return self.runtime / COMPOSANT


def _absolu(valeur, quoi: str) -> Path:
    if not isinstance(valeur, str) or not valeur or not Path(valeur).is_absolute() or ".." in Path(valeur).parts:
        raise RacinesInvalides(f"{quoi} : chemin absolu sans '..' attendu")
    return Path(valeur)


def depuis_profil(chemin: Path) -> Racines:
    """Racines d'un profil `delta.instance` v1 ; mêmes refus que `ContexteInstance` pour la forme et les chemins."""
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as e:
        raise RacinesInvalides(f"profil d'instance illisible : {e}") from e
    if not isinstance(donnees, dict) or donnees.keys() - CHAMPS_K1:
        raise RacinesInvalides("profil d'instance : objet attendu, ou clés inconnues")
    if donnees.get("schema") != "delta.instance" or donnees.get("version") != 1:
        raise RacinesInvalides("profil d'instance : schema delta.instance, version 1 attendus")
    identite = donnees.get("identite", "")
    if not isinstance(identite, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", identite):
        raise RacinesInvalides("profil d'instance : identité attendue (lettres minuscules, chiffres, tirets)")
    home = _absolu(donnees.get("home"), "profil d'instance, home")
    declarees = donnees.get("racines", {})
    if not isinstance(declarees, dict) or declarees.keys() - RACINES_K1:
        raise RacinesInvalides("profil d'instance : racines inconnues")
    racines = {}
    for nom, defaut in DEFAUTS_K1.items():
        p = _absolu(declarees[nom], f"racine {nom}") if nom in declarees else home / defaut / identite
        if home not in p.parents:
            raise RacinesInvalides(f"profil d'instance : la racine {nom} doit rester dans son HOME")
        racines[nom] = p
    return Racines(**racines, origine="instance")


def depuis_environnement(env: dict) -> Racines:
    """Instance lancée par K1 : les variables XDG désignent déjà ses racines ; toutes doivent être posées."""
    manquantes = [var for var, _ in XDG.values() if not env.get(var)]
    if manquantes:
        raise RacinesInvalides(f"DELTA_INSTANCE posée sans {', '.join(manquantes)} : racines de l'instance incomplètes")
    return Racines(**{nom: _absolu(env[var], var) for nom, (var, _) in XDG.items()}, origine="environnement")


def historiques(env: dict, home: Path) -> Racines:
    """Adaptateur explicite de l'installation historique : `<XDG ou défaut>/delta`."""
    return Racines(**{nom: (Path(env[var]) if env.get(var) else home / defaut) / "delta"
                      for nom, (var, defaut) in XDG.items()}, origine="historique")


def resoudre(profil: Path | None = None, historique: bool = False, env: dict | None = None,
             home: Path | None = None) -> Racines:
    """Une seule source : profil explicite, sinon instance de l'environnement, sinon historique demandé ; refus sinon."""
    env = dict(os.environ) if env is None else env
    if profil is not None:
        return depuis_profil(profil)
    if env.get("DELTA_INSTANCE"):
        return depuis_environnement(env)
    if historique:
        return historiques(env, home or Path.home())
    raise RacinesInvalides("racines non désignées : passer --instance <profil.json>, lancer dans une instance "
                           "(DELTA_INSTANCE) ou demander l'installation historique (--historique)")
