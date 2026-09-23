"""Pages de notes de version datées, en Markdown (`### <date>`) ou en HTML, et listes d'articles avec <time>.

Formats (option `format`) :
- `markdown_date` : titres `### September 22, 2026` ; sous-entrées par paragraphe en gras `**Titre**`,
  sinon une entrée par date.
- `html_date`     : même logique sur une page HTML (<h3> datés, <p><b>Titre</b></p>).
- `html_time_liens` : chaque <time> dans un <a> : le lien est l'URL, le titre est l'intertitre du lien.
Le format est détecté d'après la réponse si l'option est absente.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import analyser_date
from ..modeles import Element, FormatInattendu, ResultatSource

_RE_H3 = re.compile(r"^###\s+(.+?)\s*$", re.M)
_RE_GRAS_SEUL = re.compile(r"^\*\*(.+?)\*\*\s*$")


def _nom(source) -> str:
    return source.options.get("nom") or source.id


def _entrees_par_date(source, date_txt: str, corps: str, ancre: str | None, sous_entrees: list[tuple[str, str]]) -> list[Element]:
    date_iso = analyser_date(date_txt)
    if date_iso is None:
        raise FormatInattendu(f"titre de section sans date reconnaissable : {date_txt!r}")
    base = source.options.get("url_publique", source.url)
    url = f"{base}#{ancre}" if ancre else base
    if not sous_entrees:
        return [Element(source.produit, f"{_nom(source)} — {date_iso}", None, date_iso, url, corps, source.id, source.officielle)]
    return [Element(source.produit, titre, None, date_iso, url, texte, source.id, source.officielle)
            for titre, texte in sous_entrees]


def parser_markdown_date(texte: str, source) -> list[Element]:
    titres = list(_RE_H3.finditer(texte))
    if not titres:
        raise FormatInattendu("aucun titre `### <date>` trouvé")
    elements: list[Element] = []
    for i, m in enumerate(titres):
        fin = titres[i + 1].start() if i + 1 < len(titres) else len(texte)
        corps = texte[m.end():fin]
        # couper avant un éventuel `## Mois AAAA` suivant
        corps = re.split(r"^##\s+[^#]", corps, maxsplit=1, flags=re.M)[0].strip()
        if not corps:
            continue
        sous: list[tuple[str, str]] = []
        courant: tuple[str, list[str]] | None = None
        for ligne in corps.splitlines():
            g = _RE_GRAS_SEUL.match(ligne.strip())
            if g:
                if courant:
                    sous.append((courant[0], "\n".join(courant[1]).strip()))
                courant = (g.group(1).strip(), [])
            elif courant is not None:
                courant[1].append(ligne)
        if courant:
            sous.append((courant[0], "\n".join(courant[1]).strip()))
        elements.extend(_entrees_par_date(source, m.group(1), corps, None, sous))
    if not elements:
        raise FormatInattendu("titres datés trouvés mais aucune section avec du contenu")
    return elements


def parser_html_date(html: str, source) -> list[Element]:
    soup = BeautifulSoup(html, "html.parser")
    zone = soup.find("article") or soup.find("main") or soup.body or soup
    h3s = [h for h in zone.find_all("h3") if analyser_date(h.get_text(" ", strip=True))]
    if not h3s:
        raise FormatInattendu("aucun <h3> daté trouvé")
    elements: list[Element] = []
    for h in h3s:
        blocs: list[str] = []
        sous: list[tuple[str, list[str]]] = []
        for el in h.find_all_next():
            if el.name in ("h2", "h3"):
                break
            if el.name not in ("p", "li"):
                continue
            t = el.get_text(" ", strip=True)
            if not t:
                continue
            gras = el.find(["b", "strong"])
            if el.name == "p" and gras and gras.get_text(" ", strip=True) == t and not gras.find("a"):
                sous.append((t, []))
            elif sous:
                sous[-1][1].append(t)
            blocs.append(t)
        if not blocs:
            continue
        elements.extend(_entrees_par_date(source, h.get_text(" ", strip=True), "\n\n".join(blocs), h.get("id"),
                                          [(s[0], "\n\n".join(s[1])) for s in sous]))
    if not elements:
        raise FormatInattendu("<h3> datés trouvés mais sans contenu")
    return elements


def parser_html_time_liens(html: str, source) -> list[Element]:
    soup = BeautifulSoup(html, "html.parser")
    times = soup.find_all("time")
    if not times:
        raise FormatInattendu("aucune balise <time> trouvée")
    elements: list[Element] = []
    vus: set[str] = set()
    for t in times:
        a = t.find_parent("a")
        if a is None or not a.get("href"):
            continue
        url = urljoin(source.url, a["href"])
        if url in vus:
            continue
        titre_el = a.find(["h1", "h2", "h3", "h4", "h5"]) or a.find(class_=lambda c: c and "title" in c.lower())
        titre = titre_el.get_text(" ", strip=True) if titre_el else None
        if not titre:
            continue
        date_iso = analyser_date(t.get("datetime") or t.get_text(" ", strip=True))
        resume = a.find("p")
        vus.add(url)
        elements.append(Element(source.produit, titre, None, date_iso, url,
                                resume.get_text(" ", strip=True) if resume else "", source.id, source.officielle))
    if not elements:
        raise FormatInattendu("balises <time> présentes mais aucun lien avec intertitre : gabarit changé ?")
    return elements


PARSEURS = {
    "markdown_date": parser_markdown_date,
    "html_date": parser_html_date,
    "html_time_liens": parser_html_time_liens,
}


def analyser(source, client) -> ResultatSource:
    reponse = client.get(source.url, accept="text/markdown, text/html")
    fmt = source.options.get("format")
    if not fmt:
        fmt = "markdown_date" if reponse.est_markdown else "html_date"
    if fmt not in PARSEURS:
        raise FormatInattendu(f"format d'analyse inconnu : {fmt!r}")
    if fmt == "markdown_date" and "<html" in reponse.texte[:500].lower():
        raise FormatInattendu("page HTML reçue alors que du Markdown était attendu")
    return ResultatSource(PARSEURS[fmt](reponse.texte, source))
