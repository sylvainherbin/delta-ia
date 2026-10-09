"""Exclusion des entrées propres à un système exclu (D79, D108) : détection par le nom et par le texte de la documentation.

Complète les exclusions explicites de `sources.yaml` (option `exclure`, sections, tableaux) : une entrée dont le nom ou le
texte la dit propre à un système listé dans `profil.yaml` (`base.exclure_systemes`) est écartée même sans marqueur de section.
Une entrée qui nomme aussi un système non exclu (« Windows and Linux ») ou n'en désigne aucun reste.
"""

from __future__ import annotations

import re

# Par système : jetons du NOM (mots d'un nom découpé sur tout ce qui n'est pas alphanumérique) qui le désignent seul,
# et expression qui le nomme dans le TEXTE (pour repérer aussi les systèmes cités à côté).
SYSTEMES = {
    "windows": {"jetons": {"windows", "win32", "mxc", "powershell", "pwsh"}, "texte": r"Windows|PowerShell"},
    "macos": {"jetons": {"macos", "darwin", "osx", "keychain", "launchd"}, "texte": r"macOS|\bMac\b|Darwin|OS X"},
    "linux": {"jetons": {"linux", "bubblewrap", "bwrap", "systemd"}, "texte": r"Linux|Ubuntu|Debian"},
}


def _jetons(nom: str) -> set[str]:
    return {j for j in re.split(r"[^a-z0-9]+", nom.lower()) if j}


def _propre_au_texte(systeme: str, texte: str) -> bool:
    """Le texte borne l'entrée à ce système : « Windows only », « only on macOS », « available on macOS ». Une simple
    mention (« on Windows, … », « Requires Option as Meta on macOS ») ne suffit pas : l'entrée reste."""
    s = SYSTEMES[systeme]["texte"]
    return bool(re.search(
        rf"\b(?:{s})[- ]only\b|\bonly (?:\w+ ){{0,2}}(?:on|for|in|under) (?:{s})|\b(?:available|supported) on (?:{s})\b", texte, re.I))


def _mentionnes(nom: str, texte: str) -> set[str]:
    jetons = _jetons(nom)
    return {s for s, c in SYSTEMES.items() if jetons & c["jetons"] or re.search(c["texte"], f"{nom} {texte}")}


def systeme_exclu_de(nom: str, texte: str, exclus: list[str]) -> str | None:
    """Premier système exclu auquel l'entrée est propre, ou None si elle reste (aucun système, multi-systèmes, ambiguë)."""
    exclus = [s for s in exclus if s in SYSTEMES]
    if not exclus:
        return None
    mentionnes = _mentionnes(nom, texte)
    if mentionnes - set(exclus):
        return None  # un système non exclu est cité : entrée multi-systèmes, elle reste
    jetons = _jetons(nom)
    for s in exclus:
        if jetons & SYSTEMES[s]["jetons"] or _propre_au_texte(s, texte):
            return s
    return None


def ecarter(entrees: list, exclus: list[str]) -> tuple[list, list[tuple[str, object]]]:
    """(gardées, [(système, entrée)] écartées) pour des `EntreeExtraite`. Les attributs de la liste (échecs de pages,
    replis HTML) sont perdus : l'appelant les lit avant."""
    gardees, ecartees = [], []
    for e in entrees:
        s = systeme_exclu_de(e.nom, e.description_source, exclus)
        (ecartees.append((s, e)) if s else gardees.append(e))
    return gardees, ecartees
