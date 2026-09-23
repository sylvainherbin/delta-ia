"""Releases GitHub via l'API REST : une release stable = un élément, identifiée par son tag (D1).

Pagination adaptative (D4) : page suivante tant que la plus ancienne release vue est postérieure à la borne,
quatre pages au plus. `releases/latest` (option `url_latest`) garantit la dernière version stable.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from ..dates import analyser_date
from ..modeles import Element, ErreurSource, FormatInattendu, ResultatSource

CHAMPS_OBLIGATOIRES = ("tag_name", "html_url", "published_at")
PAGES_MAX = 4


def _version(tag: str, prefixe: str) -> str:
    return tag[len(prefixe):] if prefixe and tag.startswith(prefixe) else tag


def dates_par_version(releases, prefixe: str) -> dict[str, str]:
    if not isinstance(releases, list):
        raise FormatInattendu("l'API releases n'a pas renvoyé une liste")
    dates: dict[str, str] = {}
    for r in releases:
        if not isinstance(r, dict) or not r.get("tag_name"):
            continue
        d = analyser_date(r.get("published_at") or r.get("created_at"))
        if d:
            dates[_version(r["tag_name"], prefixe)] = d
    return dates


def parser_releases(releases, source) -> list[Element]:
    if not isinstance(releases, list):
        raise FormatInattendu("l'API releases n'a pas renvoyé une liste")
    if not releases:
        raise FormatInattendu("liste de releases vide")
    prefixe = source.options.get("prefixe_tag", "")
    inclure_pre = bool(source.options.get("inclure_prereleases", False))
    elements: list[Element] = []
    for r in releases:
        if not isinstance(r, dict):
            raise FormatInattendu("entrée de release qui n'est pas un objet")
        manquants = [c for c in CHAMPS_OBLIGATOIRES if c not in r]
        if manquants:
            raise FormatInattendu(f"champs manquants dans une release : {manquants}")
        if r.get("draft"):
            continue
        if r.get("prerelease") and not inclure_pre:
            continue
        version = _version(r["tag_name"], prefixe)
        nom = (r.get("name") or "").strip()
        titre = nom if nom and nom != version else f"{source.options.get('nom', source.produit)} {version}"
        if nom and nom != version and version not in nom:
            titre = f"{nom} ({version})"
        elements.append(Element(
            id=r["tag_name"],
            produit=source.produit,
            titre=titre,
            version=version,
            date_publication=analyser_date(r.get("published_at")),
            url=r["html_url"],
            contenu=(r.get("body") or "").strip(),
            source_id=source.id,
            officielle=source.officielle,
        ))
    # Une liste sans aucune release stable n'est pas une erreur de format : l'exclusion des pré-versions est voulue.
    return elements


def _charger(client, url):
    reponse = client.get(url, accept="application/vnd.github+json")
    try:
        donnees = json.loads(reponse.texte)
    except ValueError as e:
        raise FormatInattendu(f"JSON invalide : {e}") from e
    if isinstance(donnees, dict) and "message" in donnees:
        raise FormatInattendu(f"réponse d'erreur GitHub : {donnees['message'][:200]}")
    return donnees


def url_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    q = {k: v[-1] for k, v in parse_qs(parts.query).items()}
    q["page"] = str(page)
    return urlunsplit(parts._replace(query=urlencode(q)))


def _plus_ancienne(releases) -> str | None:
    dates = [analyser_date(r.get("published_at")) for r in releases if isinstance(r, dict)]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def analyser(source, client, borne: str | None = None) -> ResultatSource:
    releases = _charger(client, source.url)
    if not isinstance(releases, list):
        raise FormatInattendu("l'API releases n'a pas renvoyé une liste")
    if not releases:
        raise FormatInattendu("liste de releases vide")
    page = 1
    while borne and page < PAGES_MAX:
        ancienne = _plus_ancienne(releases)
        if ancienne is None or ancienne <= borne:
            break
        page += 1
        suite = _charger(client, url_page(source.url, page))
        if not isinstance(suite, list):
            raise FormatInattendu(f"page {page} : l'API releases n'a pas renvoyé une liste")
        if not suite:
            break  # fin de l'historique
        releases = releases + suite
    plus_ancienne = _plus_ancienne(releases)  # pré-versions comprises : c'est l'horizon réellement vu
    partiel = None
    url_latest = source.options.get("url_latest")
    if url_latest:
        try:
            derniere = _charger(client, url_latest)
        except (ErreurSource, FormatInattendu) as e:
            partiel = f"releases/latest indisponible : {e}"
        else:
            if not isinstance(derniere, dict) or not derniere.get("tag_name"):
                raise FormatInattendu("releases/latest n'a pas renvoyé une release")
            if derniere["tag_name"] not in {r.get("tag_name") for r in releases if isinstance(r, dict)}:
                releases = releases + [derniere]
    return ResultatSource(parser_releases(releases, source), partiel, plus_ancienne=plus_ancienne)
