"""CHANGELOG.md d'un dépôt GitHub : sections `## x.y.z`, datées par l'API releases du même dépôt."""

from __future__ import annotations

import json
import re

from ..modeles import Element, ErreurSource, FormatInattendu, ResultatSource
from .github_releases import dates_par_version

_RE_VERSION = re.compile(r"^##\s+v?(\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.-]+)?)\s*$", re.M)


def parser_changelog(texte: str, source, dates: dict[str, str] | None = None) -> list[Element]:
    """Découpe le Markdown en versions. `dates` : version -> AAAA-MM-JJ (peut être vide)."""
    dates = dates or {}
    positions = list(_RE_VERSION.finditer(texte))
    if not positions:
        raise FormatInattendu("aucune section `## x.y.z` trouvée dans le changelog")
    elements: list[Element] = []
    for i, m in enumerate(positions):
        version = m.group(1)
        debut = m.end()
        fin = positions[i + 1].start() if i + 1 < len(positions) else len(texte)
        corps = texte[debut:fin].strip()
        if not corps:
            continue
        url = source.options.get("url_version", "").format(version=version) if source.options.get("url_version") \
            else f"{source.options.get('url_publique', source.url)}#{version.replace('.', '')}"
        elements.append(Element(
            produit=source.produit,
            titre=f"{_nom(source)} {version}",
            version=version,
            date_publication=dates.get(version),
            url=url,
            contenu=corps,
            source_id=source.id,
            officielle=source.officielle,
        ))
    if not elements:
        raise FormatInattendu("sections de version trouvées mais toutes vides")
    return elements


def _nom(source) -> str:
    return source.options.get("nom", {"claude-code": "Claude Code"}.get(source.produit, source.produit))


def analyser(source, client) -> ResultatSource:
    reponse = client.get(source.url)
    if reponse.est_json or "<html" in reponse.texte[:500].lower():
        raise FormatInattendu(f"réponse non Markdown ({reponse.content_type or 'type inconnu'})")
    dates: dict[str, str] = {}
    partiel = None
    releases_url = source.options.get("releases_url")
    if releases_url:
        try:
            rep = client.get(releases_url, accept="application/vnd.github+json")
            dates = dates_par_version(json.loads(rep.texte), source.options.get("prefixe_tag", "v"))
        except (ErreurSource, ValueError) as e:
            partiel = f"dates indisponibles, API releases en échec : {e}"
    elements = parser_changelog(reponse.texte, source, dates)
    if releases_url and not partiel and not any(e.date_publication for e in elements):
        partiel = "API releases lue mais aucune version datée (préfixe de tag ou nommage inattendu)"
    return ResultatSource(elements, partiel)
