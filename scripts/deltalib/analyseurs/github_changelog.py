"""CHANGELOG.md d'un dépôt GitHub : sections `## x.y.z`, datées par l'API releases du même dépôt.

Identifiant (D1) : `<produit>-<version>`. Historique (D3) : les versions strictement inférieures à la plus
ancienne version datée par l'API sont ignorées ; une version non datée plus récente est une nouveauté.
"""

from __future__ import annotations

import json
import re

from ..modeles import Element, ErreurSource, FormatInattendu, ResultatSource, cle_version
from .github_releases import dates_par_version

_RE_VERSION = re.compile(r"^##\s+v?(\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.-]+)?)\s*$", re.M)


def _nom(source) -> str:
    return source.options.get("nom", {"claude-code": "Claude Code"}.get(source.produit, source.produit))


def parser_changelog(texte: str, source, dates: dict[str, str] | None = None) -> list[Element]:
    """Découpe le Markdown en versions. `dates` : version -> AAAA-MM-JJ (peut être vide)."""
    dates = dates or {}
    positions = list(_RE_VERSION.finditer(texte))
    if not positions:
        raise FormatInattendu("aucune section `## x.y.z` trouvée dans le changelog")
    base = source.options.get("url_publique", source.url)
    elements: list[Element] = []
    for i, m in enumerate(positions):
        version = m.group(1)
        fin = positions[i + 1].start() if i + 1 < len(positions) else len(texte)
        corps = texte[m.end():fin].strip()
        if not corps:
            continue
        elements.append(Element(
            id=f"{source.produit}-{version}",
            produit=source.produit,
            titre=f"{_nom(source)} {version}",
            version=version,
            date_publication=dates.get(version),
            url=f"{base}#{version.replace('.', '')}",
            contenu=corps,
            source_id=source.id,
            officielle=source.officielle,
        ))
    if not elements:
        raise FormatInattendu("sections de version trouvées mais toutes vides")
    return elements


def separer_historique(elements: list[Element]) -> tuple[list[Element], list[str]]:
    """D3 : versions non datées strictement inférieures à la plus ancienne version datée -> historique."""
    datees = [e for e in elements if e.date_publication]
    if not datees:
        return elements, []
    plancher = min(cle_version(e.version) for e in datees)
    courants, historique = [], []
    for e in elements:
        if e.date_publication is None and cle_version(e.version) < plancher:
            historique.append(e.id)
        else:
            courants.append(e)
    return courants, historique


def analyser(source, client, borne: str | None = None) -> ResultatSource:
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
    elements, historique = separer_historique(elements)
    plus_ancienne = min((e.date_publication for e in elements if e.date_publication), default=None)
    return ResultatSource(elements, partiel, ignores=historique, plus_ancienne=plus_ancienne)
