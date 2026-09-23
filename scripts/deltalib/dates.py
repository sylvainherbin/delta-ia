"""Analyse de dates hétérogènes vers AAAA-MM-JJ. Une date non reconnue vaut None, jamais devinée."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

MOIS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# « September 22, 2026 », « Sep 22, 2026 », « 22 September 2026 »
_RE_ANGLAIS = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")
_RE_ANGLAIS_INV = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})(?!\d)")
_RE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def _valide(a: int, m: int, j: int) -> str | None:
    try:
        return date(a, m, j).isoformat()
    except ValueError:
        return None


def analyser_date(texte: str | None) -> str | None:
    """Retourne AAAA-MM-JJ, ou None si aucune date fiable n'est reconnue."""
    if not texte:
        return None
    t = texte.strip()
    m = _RE_ISO.search(t)
    if m:
        return _valide(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _RE_ANGLAIS.search(t)
    if m and m.group(1).lower() in MOIS:
        return _valide(int(m.group(3)), MOIS[m.group(1).lower()], int(m.group(2)))
    m = _RE_ANGLAIS_INV.search(t)
    if m and m.group(2).lower() in MOIS:
        return _valide(int(m.group(3)), MOIS[m.group(2).lower()], int(m.group(1)))
    try:  # RFC 2822 (flux RSS)
        return parsedate_to_datetime(t).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    return None


def contient_date(texte: str) -> bool:
    return analyser_date(texte) is not None


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def aujourd_hui() -> date:
    return datetime.now(timezone.utc).date()
