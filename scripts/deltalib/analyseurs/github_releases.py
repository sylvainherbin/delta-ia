"""Releases GitHub via l'API REST : une release stable = un élément. Pré-versions exclues par défaut."""

from __future__ import annotations

import json

from ..dates import analyser_date
from ..modeles import Element, ErreurSource, FormatInattendu, ResultatSource

CHAMPS_OBLIGATOIRES = ("tag_name", "html_url", "published_at")


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


def analyser(source, client) -> ResultatSource:
    """Liste des dernières releases, complétée par `releases/latest` (option `url_latest`).

    La liste est volontairement courte (chaque release pèse ~300 Ko dans l'API) ; `latest` garantit que la
    dernière version stable est vue même si les pré-versions ont rempli la liste.
    """
    donnees = _charger(client, source.url)
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
            if isinstance(donnees, list) and derniere["tag_name"] not in {r.get("tag_name") for r in donnees if isinstance(r, dict)}:
                donnees = list(donnees) + [derniere]
    return ResultatSource(parser_releases(donnees, source), partiel)
