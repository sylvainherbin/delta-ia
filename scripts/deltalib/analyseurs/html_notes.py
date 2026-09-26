"""Pages de notes de version datées, en Markdown (`### <date>`) ou en HTML, et listes d'articles avec <time>.

Formats (option `format`) :
- `markdown_date` : titres `### September 22, 2026` ; une entrée par date, identifiée `<source>-<date>`,
  titrée par ses intertitres en gras `**Titre**` s'il y en a.
- `html_date`     : même logique sur une page HTML (<h3> datés, <p><b>Titre</b></p>).
- `html_time_liens` : chaque <time> dans un <a> : le lien est l'URL et l'identifiant, le titre est l'intertitre.
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


def _element_date(source, date_txt: str, corps: str, ancre: str | None, titres: list[str]) -> Element:
    """Une entrée par date (D1) : id `<source>-<date>`, titre = intertitres en gras s'il y en a."""
    date_iso = analyser_date(date_txt)
    if date_iso is None:
        raise FormatInattendu(f"titre de section sans date reconnaissable : {date_txt!r}")
    base = source.options.get("url_publique", source.url)
    titre = " ; ".join(titres) if titres else f"{_nom(source)} — {date_iso}"
    return Element(id=f"{source.id}-{date_iso}", produit=source.produit, titre=titre, version=None,
                   date_publication=date_iso, url=f"{base}#{ancre}" if ancre else base, contenu=corps,
                   source_id=source.id, officielle=source.officielle)


def parser_markdown_date(texte: str, source) -> list[Element]:
    titres = list(_RE_H3.finditer(texte))
    if not titres:
        raise FormatInattendu("aucun titre `### <date>` trouvé")
    elements: list[Element] = []
    vus: dict[str, Element] = {}
    for i, m in enumerate(titres):
        fin = titres[i + 1].start() if i + 1 < len(titres) else len(texte)
        corps = texte[m.end():fin]
        # couper avant un éventuel `## Mois AAAA` suivant
        corps = re.split(r"^##\s+[^#]", corps, maxsplit=1, flags=re.M)[0].strip()
        if not corps:
            continue
        gras = [g.group(1).strip() for l in corps.splitlines() if (g := _RE_GRAS_SEUL.match(l.strip()))]
        e = _element_date(source, m.group(1), corps, None, gras)
        if e.id in vus:  # même date répétée dans la page : on fusionne
            vus[e.id].contenu += "\n\n" + corps
        else:
            vus[e.id] = e
            elements.append(e)
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
    vus: dict[str, Element] = {}
    for h in h3s:
        blocs: list[str] = []
        gras: list[str] = []
        for el in h.find_all_next():
            if el.name in ("h2", "h3"):
                break
            if el.name not in ("p", "li"):
                continue
            t = el.get_text(" ", strip=True)
            if not t:
                continue
            b = el.find(["b", "strong"])
            if el.name == "p" and b and b.get_text(" ", strip=True) == t and not b.find("a"):
                gras.append(t)
            blocs.append(t)
        if not blocs:
            continue
        e = _element_date(source, h.get_text(" ", strip=True), "\n\n".join(blocs), h.get("id"), gras)
        if e.id in vus:
            vus[e.id].contenu += "\n\n" + e.contenu
        else:
            vus[e.id] = e
            elements.append(e)
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
        elements.append(Element(id=url, produit=source.produit, titre=titre, version=None, date_publication=date_iso,
                                url=url, contenu=resume.get_text(" ", strip=True) if resume else "",
                                source_id=source.id, officielle=source.officielle))
    if not elements:
        raise FormatInattendu("balises <time> présentes mais aucun lien avec intertitre : gabarit changé ?")
    return elements


TAILLE_MAX_ARTICLE = 20000  # caractères gardés du texte principal d'un article (le début porte l'essentiel)
TAILLE_MIN_ARTICLE = 200


def texte_article(html: str) -> str:
    """A1 (26/09) : texte principal d'un article de la newsroom, pour `contenu`. Le plus long <article> de la page,
    sinon <main> ; titres, paragraphes et puces, un bloc par ligne. Gabarit changé ou texte trop court :
    FormatInattendu, jamais un contenu vide."""
    soup = BeautifulSoup(html, "html.parser")
    candidats = soup.find_all("article") or soup.find_all("main")
    if not candidats:
        raise FormatInattendu("article sans <article> ni <main> : gabarit changé ?")
    zone = max(candidats, key=lambda e: len(e.get_text(" ", strip=True)))
    for bruit in zone.find_all(["script", "style", "nav", "aside", "noscript", "svg", "button", "form"]):
        bruit.decompose()
    blocs, vus = [], set()
    for b in zone.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        if b.find_parent(["li", "p"]) and b.name in ("p", "li"):
            continue  # paragraphe dans une puce : le texte est déjà pris avec la puce
        t = re.sub(r"\s+", " ", b.get_text(" ", strip=True)).replace(" .", ".").replace(" ,", ",")
        if t and t not in vus:
            vus.add(t)
            blocs.append(t)
    texte = "\n".join(blocs)
    if len(texte) < TAILLE_MIN_ARTICLE:
        raise FormatInattendu(f"texte de l'article trop court ({len(texte)} caractères) : gabarit changé ?")
    if len(texte) > TAILLE_MAX_ARTICLE:
        texte = texte[:TAILLE_MAX_ARTICLE].rsplit("\n", 1)[0] + "\n[… texte tronqué]"
    return texte


def parser_sections_suivies(texte: str, source) -> list[Element]:
    """O2 (26/09) : page Markdown suivie par empreinte de section (option `suivre_revisions`). Chaque section de
    `options.sections` ({id, titre: regex, portee: complete|chapeau}) donne un élément non daté `<source>-<id>` :
    une modification de la section le fait revenir en révision. `chapeau` = texte avant le premier sous-titre.
    Section introuvable ou vide : FormatInattendu."""
    from ..kb.markdown import sections as decouper
    lignes, secs = decouper(texte)
    base = source.url[:-3] if source.url.endswith(".md") else source.url
    res: list[Element] = []
    for conf in source.options.get("sections") or []:
        rx = re.compile(conf["titre"], re.I)
        sec = next((s for s in secs if rx.search(s.titre)), None)
        if sec is None:
            raise FormatInattendu(f"section « {conf['titre']} » introuvable : gabarit changé ?")
        fin = sec.fin
        if conf.get("portee") == "chapeau":
            fin = next((s.debut for s in secs if s.debut > sec.debut and s.niveau > sec.niveau), sec.fin)
        corps = "\n".join(lignes[sec.debut + 1:fin]).strip()
        if not corps:
            raise FormatInattendu(f"section « {sec.titre} » vide")
        ancre = re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", sec.titre.lower()))
        res.append(Element(id=f"{source.id}-{conf['id']}", produit=source.produit,
                           titre=f"{_nom(source)} — {sec.titre}", version=None, date_publication=None,
                           url=f"{base}#{ancre}" if conf.get("portee") != "chapeau" else base, contenu=corps,
                           source_id=source.id, officielle=source.officielle))
    if not res:
        raise FormatInattendu("aucune section suivie déclarée (options.sections)")
    return res


PARSEURS = {
    "markdown_date": parser_markdown_date,
    "html_date": parser_html_date,
    "html_time_liens": parser_html_time_liens,
    "sections_suivies": parser_sections_suivies,
}


def analyser(source, client, borne: str | None = None) -> ResultatSource:
    reponse = client.get(source.url, accept="text/markdown, text/html")
    fmt = source.options.get("format")
    if not fmt:
        fmt = "markdown_date" if reponse.est_markdown else "html_date"
    if fmt not in PARSEURS:
        raise FormatInattendu(f"format d'analyse inconnu : {fmt!r}")
    if fmt == "markdown_date" and "<html" in reponse.texte[:500].lower():
        raise FormatInattendu("page HTML reçue alors que du Markdown était attendu")
    return ResultatSource(PARSEURS[fmt](reponse.texte, source))
