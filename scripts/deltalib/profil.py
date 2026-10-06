"""Profil servi par la veille (D79) : lecture stricte de `profil.yaml`, valeurs par défaut sûres si absent."""

from __future__ import annotations

from pathlib import Path

import yaml

SYSTEMES_CONNUS = ("windows", "macos", "linux")  # acceptés par le chargeur ; la valeur par défaut reste [windows, macos]

DEFAUTS = {
    "priorites": [],
    "progression": None,
    "releves_machine": False,
    "base": {"exclure_systemes": ["windows", "macos"]},
}


class ProfilInvalide(ValueError):
    """`profil.yaml` illisible ou de type incorrect."""


def _copie_defauts() -> dict:
    return {"priorites": [], "progression": None, "releves_machine": False,
            "base": {"exclure_systemes": list(DEFAUTS["base"]["exclure_systemes"])}}


def _liste_de_textes(valeur, nom: str) -> list[str]:
    if not isinstance(valeur, list) or not all(isinstance(x, str) and x.strip() for x in valeur):
        raise ProfilInvalide(f"profil.yaml : `{nom}` doit être une liste de textes non vides")
    return [x.strip() for x in valeur]


def charger(racine: Path | str) -> dict:
    """Profil complet {priorites, progression, releves_machine, base: {exclure_systemes}} de `<racine>/profil.yaml`."""
    chemin = Path(racine) / "profil.yaml"
    profil = _copie_defauts()
    if not chemin.exists():
        return profil
    try:
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        raise ProfilInvalide(f"profil.yaml illisible : {e}") from e
    if brut is None:
        return profil
    if not isinstance(brut, dict):
        raise ProfilInvalide("profil.yaml : un dictionnaire est attendu à la racine")
    inconnues = set(brut) - set(DEFAUTS)
    if inconnues:
        raise ProfilInvalide(f"profil.yaml : clés inconnues {sorted(map(str, inconnues))}")
    if "priorites" in brut:
        profil["priorites"] = _liste_de_textes(brut["priorites"], "priorites")
    if "progression" in brut:
        p = brut["progression"]
        if p is not None and not (isinstance(p, str) and p.strip()):
            raise ProfilInvalide("profil.yaml : `progression` doit être un chemin (texte) ou null")
        profil["progression"] = p.strip() if p else None
    if "releves_machine" in brut:
        if not isinstance(brut["releves_machine"], bool):
            raise ProfilInvalide("profil.yaml : `releves_machine` doit être un booléen (true ou false)")
        profil["releves_machine"] = brut["releves_machine"]
    if "base" in brut:
        base = brut["base"]
        if not isinstance(base, dict):
            raise ProfilInvalide("profil.yaml : `base` doit être un dictionnaire")
        inconnues = set(base) - {"exclure_systemes"}
        if inconnues:
            raise ProfilInvalide(f"profil.yaml : clés inconnues dans `base` {sorted(map(str, inconnues))}")
        if "exclure_systemes" in base:
            systemes = [s.lower() for s in _liste_de_textes(base["exclure_systemes"], "base.exclure_systemes")]
            inconnus = [s for s in systemes if s not in SYSTEMES_CONNUS]
            if inconnus:
                raise ProfilInvalide(f"profil.yaml : `base.exclure_systemes` accepte {list(SYSTEMES_CONNUS)}, pas {inconnus}")
            profil["base"]["exclure_systemes"] = systemes
    return profil
