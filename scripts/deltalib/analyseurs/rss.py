"""Flux RSS 2.0 et Atom, via la bibliothèque standard. Filtre facultatif par catégorie."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from ..dates import analyser_date
from ..modeles import Element, FormatInattendu, ResultatSource

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _texte(el, *chemins) -> str | None:
    for c in chemins:
        e = el.find(c, NS)
        if e is not None:
            v = (e.text or "").strip()
            if v:
                return v
    return None


def _lien_atom(entry) -> str | None:
    liens = entry.findall("atom:link", NS)
    for l in liens:
        if l.get("rel", "alternate") == "alternate" and l.get("href"):
            return l.get("href").strip()
    return liens[0].get("href").strip() if liens and liens[0].get("href") else None


def html_en_texte(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    texte = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def parser_flux(xml_texte: str, source) -> list[Element]:
    try:
        racine = ET.fromstring(xml_texte.encode("utf-8") if isinstance(xml_texte, str) else xml_texte)
    except ET.ParseError as e:
        raise FormatInattendu(f"XML invalide : {e}") from e
    categories = {c.lower() for c in source.options.get("categories", [])}
    entrees: list[tuple] = []
    if racine.tag == "rss" or racine.find("channel") is not None:
        for it in racine.iter("item"):
            entrees.append((
                _texte(it, "title"),
                _texte(it, "link") or (it.find("guid").text.strip() if it.find("guid") is not None and (it.find("guid").get("isPermaLink") in (None, "true")) and it.find("guid").text else None),
                _texte(it, "pubDate", "dc:date", "atom:published", "atom:updated"),
                _texte(it, "content:encoded", "description"),
                [(c.text or "").strip() for c in it.findall("category")],
            ))
    elif racine.tag == f"{{{NS['atom']}}}feed":
        for en in racine.findall("atom:entry", NS):
            entrees.append((
                _texte(en, "atom:title"),
                _lien_atom(en),
                _texte(en, "atom:published", "atom:updated"),
                _texte(en, "atom:content", "atom:summary"),
                [(c.get("term") or "").strip() for c in en.findall("atom:category", NS)],
            ))
    else:
        raise FormatInattendu(f"racine XML inattendue : {racine.tag}")
    if not entrees:
        raise FormatInattendu("flux sans aucun <item> ni <entry>")
    elements: list[Element] = []
    for titre, lien, date_txt, corps, cats in entrees:
        if not titre or not lien:
            raise FormatInattendu(f"entrée sans titre ou sans lien (titre={titre!r})")
        if categories and not ({c.lower() for c in cats} & categories):
            continue
        elements.append(Element(
            produit=source.produit,
            titre=titre,
            version=None,
            date_publication=analyser_date(date_txt),
            url=lien,
            contenu=html_en_texte(corps),
            source_id=source.id,
            officielle=source.officielle,
        ))
    # Après filtrage par catégorie, une liste vide est légitime.
    return elements


def analyser(source, client) -> ResultatSource:
    reponse = client.get(source.url, accept="application/rss+xml, application/atom+xml, application/xml, text/xml")
    if "<html" in reponse.texte[:300].lower():
        raise FormatInattendu(f"page HTML reçue à la place d'un flux ({reponse.content_type or 'type inconnu'})")
    return ResultatSource(parser_flux(reponse.texte, source))
