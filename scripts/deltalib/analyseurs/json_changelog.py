"""Flux JSON du « ChatGPT & Codex changelog » (learn.chatgpt.com/docs/changelog/*.json).

Endpoint non documenté : toute dérive de structure doit être une erreur explicite, jamais un résultat vide.
Identifiant (D1) : `oa-<id natif>`, commun aux flux general, codex-app et ios, pour dédoublonner.
Produit (D2, option `produit_par_entree`) : « codex » dans le titre ou les sujets -> codex, sinon chatgpt.
"""

from __future__ import annotations

import json

from ..dates import analyser_date
from ..modeles import Element, FormatInattendu, ResultatSource

CHAMPS_OBLIGATOIRES = ("id", "title", "date")
SCHEMA_ATTENDU = 1


def produit_de(it: dict, source) -> str:
    if not source.options.get("produit_par_entree"):
        return source.produit
    texte = " ".join([str(it.get("title") or "")] + [str(t) for t in (it.get("topics") or [])]).lower()
    return "codex" if "codex" in texte else "chatgpt"


def parser_json(donnees, source) -> list[Element]:
    if not isinstance(donnees, dict):
        raise FormatInattendu("la racine n'est pas un objet JSON")
    if donnees.get("schemaVersion") not in (None, SCHEMA_ATTENDU):
        raise FormatInattendu(f"schemaVersion inattendu : {donnees.get('schemaVersion')!r} (attendu {SCHEMA_ATTENDU})")
    items = donnees.get("items")
    if not isinstance(items, list):
        raise FormatInattendu("clé `items` absente ou pas une liste")
    if not items:
        raise FormatInattendu("liste `items` vide")
    elements: list[Element] = []
    for it in items:
        if not isinstance(it, dict):
            raise FormatInattendu("entrée qui n'est pas un objet")
        manquants = [c for c in CHAMPS_OBLIGATOIRES if not it.get(c)]
        if manquants:
            raise FormatInattendu(f"champs manquants dans l'entrée {it.get('id', '?')!r} : {manquants}")
        titre = str(it["title"]).strip()
        version = it.get("version")
        version = str(version).strip() if version not in (None, "") else None
        if version and version not in titre:
            titre = f"{titre} {version}"
        corps = it.get("bodyMarkdown") or it.get("summary") or ""
        elements.append(Element(
            id=f"oa-{it['id']}",
            produit=produit_de(it, source),
            titre=titre,
            version=version,
            date_publication=analyser_date(str(it["date"])),
            url=it.get("url") or f"{source.options.get('url_publique', 'https://developers.openai.com/codex/changelog')}#{it['id']}",
            contenu=str(corps).strip(),
            source_id=source.id,
            officielle=source.officielle,
        ))
    return elements


def analyser(source, client, borne: str | None = None) -> ResultatSource:
    reponse = client.get(source.url, accept="application/json")
    try:
        donnees = json.loads(reponse.texte)
    except ValueError as e:
        raise FormatInattendu(f"JSON invalide ({reponse.content_type or 'type inconnu'}) : {e}") from e
    return ResultatSource(parser_json(donnees, source))
