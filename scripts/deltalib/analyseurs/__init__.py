"""Un analyseur par `type` de source. Tous produisent des `Element` au format brut commun.

Chaque module expose `analyser(source, client) -> ResultatSource` (récupération + analyse) et une fonction
pure `parser_*` testable sur un échantillon enregistré.
"""

from __future__ import annotations

from . import github_changelog, github_releases, html_notes, json_changelog, rss

ANALYSEURS = {
    "github_changelog": github_changelog.analyser,
    "github_releases": github_releases.analyser,
    "html": html_notes.analyser,
    "rss": rss.analyser,
    "json": json_changelog.analyser,
}
