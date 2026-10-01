"""Pages de notes de version datées, en Markdown (`### <date>`) ou en HTML, et listes d'articles avec <time>.

Formats (option `format`) :
- `markdown_date` : titres `### September 22, 2026` ; une entrée par date, identifiée `<source>-<date>`,
  titrée par ses intertitres en gras `**Titre**` s'il y en a.
- `html_date`     : même logique sur une page HTML (<h3> datés, <p><b>Titre</b></p>).
- `html_time_liens` : chaque <time> dans un <a> : le lien est l'URL et l'identifiant, le titre est l'intertitre.
- `html_blog_liste` : liste Webflow/Finsweet du blog claude.com (étape 2b) : un élément par article de la première page.
- `annonces_datees` : pages de dépréciations des modèles (étape 2c) : une annonce par titre `### AAAA-MM-JJ: titre` sous les
  sections parentes déclarées, plus, si déclarées, des sections suivies en entier (tableau d'état des modèles, préavis).
Le format est détecté d'après la réponse si l'option est absente.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

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


def parser_blog_liste(html: str, source) -> tuple[list[Element], str | None]:
    """Étape 2b (01/10/2026) : liste des articles de claude.com/blog (Webflow + attributs Finsweet `fs-list-field`).
    Chaque `.blog_cms_list .blog_cms_item` porte un titre (`heading`), une date en toutes lettres (`date`), une
    catégorie (`category`) et un lien `fs-list-element="item-link"` : l'URL absolue est l'identifiant (D1), le texte
    de l'article s'y lit avec l'option `lire_articles`. Seule la première page (15 articles) est lue : la plus
    ancienne date vue est rendue pour la détection de trou (D4). Liste absente, carte sans titre, sans lien ou sans
    date reconnaissable : FormatInattendu, jamais une liste vide silencieuse."""
    soup = BeautifulSoup(html, "html.parser")
    liste = soup.select_one(".blog_cms_list")
    if liste is None:
        raise FormatInattendu("liste `.blog_cms_list` introuvable : gabarit du blog changé ?")
    cartes = liste.select(".blog_cms_item")
    if not cartes:
        raise FormatInattendu("liste du blog sans aucune carte `.blog_cms_item` : gabarit changé ?")
    elements: list[Element] = []
    vus: set[str] = set()
    dates: list[str] = []
    for c in cartes:
        titre_el = c.select_one('[fs-list-field="heading"]')
        lien = c.select_one('a[fs-list-element="item-link"][href]') or c.select_one('a[href^="/blog/"]')
        date_el = c.select_one('[fs-list-field="date"]')
        if titre_el is None or not titre_el.get_text(strip=True) or lien is None or date_el is None:
            raise FormatInattendu("carte du blog sans titre, lien ou date : gabarit changé ?")
        url = urljoin(source.url, lien["href"])
        date_iso = analyser_date(date_el.get_text(" ", strip=True))
        if date_iso is None:
            raise FormatInattendu(f"date illisible dans la carte {url} : {date_el.get_text(' ', strip=True)!r}")
        if url in vus:
            continue
        vus.add(url)
        dates.append(date_iso)
        categories = [x.get_text(" ", strip=True) for x in c.select('[fs-list-field="category"]')]
        elements.append(Element(id=url, produit=source.produit, titre=titre_el.get_text(" ", strip=True), version=None,
                                date_publication=date_iso, url=url,
                                contenu=("Catégorie : " + ", ".join(categories)) if categories else "",
                                source_id=source.id, officielle=source.officielle))
    return elements, min(dates)


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
    base = re.sub(r"\.md(?=\?|$)", "", source.url)
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


def _slug(texte: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")[:60].strip("-")


_RE_TITRE_ANNONCE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*:\s*(.*)$")


def parser_annonces_datees(texte: str, source) -> list[Element]:
    """Étape 2c (01/10) : page de dépréciations, en Markdown. `options.parents` liste les sections parentes
    ({titre: regex, sans_date: bool}) ; chaque titre de niveau suivant est une annonce, élément `<source>-<date>-<slug>`
    (date lue dans le titre `AAAA-MM-JJ: titre`, jamais devinée). Une annonce sans date n'est retenue que sous un parent
    `sans_date: true` (annonces en attente), son identifiant est alors `<source>-<slug>` et sa date `null`. Le corps
    comprend les sous-titres : une note « retired » ajoutée ou un tableau modifié fait revenir l'annonce en révision
    (`suivre_revisions`). `options.sections` (facultatif, même format que `sections_suivies`) ajoute des sections suivies
    en entier. Parent introuvable, titre de date invalide ou aucune annonce ni section : FormatInattendu."""
    from ..kb.markdown import sections as decouper
    lignes, secs = decouper(texte)
    base = re.sub(r"\.md(?=\?|$)", "", source.options.get("url_publique", source.url))
    res: list[Element] = parser_sections_suivies(texte, source) if source.options.get("sections") else []
    vus = {e.id for e in res}
    parents = source.options.get("parents") or []
    if not parents and not res:
        raise FormatInattendu("aucune section parente ni section suivie déclarée (options.parents, options.sections)")
    for conf in parents:
        rx = re.compile(conf["titre"], re.I)
        parent = next((s for s in secs if rx.search(s.titre)), None)
        if parent is None:
            raise FormatInattendu(f"section « {conf['titre']} » introuvable : gabarit changé ?")
        for sec in secs:
            if sec.niveau != parent.niveau + 1 or not (parent.debut < sec.debut < parent.fin):
                continue
            m = _RE_TITRE_ANNONCE.match(sec.titre)
            if m:
                date_iso = analyser_date(m.group(1))
                if date_iso is None:
                    raise FormatInattendu(f"titre d'annonce avec une date invalide : {sec.titre!r}")
                ident = f"{source.id}-{date_iso}-{_slug(m.group(2)) or 'annonce'}"
            elif conf.get("sans_date"):
                date_iso, ident = None, f"{source.id}-{_slug(sec.titre) or 'annonce'}"
            else:
                continue
            corps = "\n".join(lignes[sec.debut + 1:sec.fin]).strip()
            if not corps:
                raise FormatInattendu(f"annonce « {sec.titre} » sans contenu")
            n, unique = 2, ident
            while unique in vus:  # deux annonces du même jour au titre identique : suffixe stable selon l'ordre de la page
                unique, n = f"{ident}-{n}", n + 1
            vus.add(unique)
            res.append(Element(id=unique, produit=source.produit, titre=f"{_nom(source)} — {sec.titre}", version=None,
                               date_publication=date_iso, url=base, contenu=corps, source_id=source.id,
                               officielle=source.officielle))
    if not res:
        raise FormatInattendu("aucune annonce ni section suivie trouvée : gabarit changé ?")
    return res


_RE_LIEN_INDEX = re.compile(r"^\s*[-*]\s*\[(?P<titre>.+?)\]\((?P<url>https?://[^)\s]+)\)\s*(?::\s*(?P<desc>.*))?$")
_RE_ARTICLE_AIDE = re.compile(r"/articles/(\d+)")


def _id_article(url: str) -> str:
    """Identifiant natif stable d'une page d'un index llms.txt : numéro d'article d'aide (un changement de titre ou de
    slug ne crée pas un nouvel article), sinon le chemin de la page sans extension ni requête."""
    m = _RE_ARTICLE_AIDE.search(url)
    if m:
        return m.group(1)
    chemin = urlparse(url).path.strip("/")
    return re.sub(r"[^A-Za-z0-9]+", "-", chemin.removesuffix(".md")).strip("-") or url


def parser_index_articles(texte: str, source) -> list[Element]:
    """Étape 2a (30/09) : index llms.txt d'un centre d'aide (une ligne `- [Titre](url): description` par page).
    `options.section` limite la lecture à une section `## <nom>` (le centre d'aide Claude répète chaque article dans
    dix langues). Seules les pages dont le titre ou la description touche au compte et aux quotas (D71,
    `deltalib.sujet_d71`) deviennent des éléments non datés `<source>-<id>` : une page absente de l'état est un nouvel
    article d'aide. Section introuvable, ou aucune ligne reconnue : FormatInattendu, jamais un vide silencieux."""
    from ..sujet_d71 import mots_trouves_index
    lignes = texte.splitlines()
    section = source.options.get("section")
    if section:
        debut = next((i for i, l in enumerate(lignes) if re.fullmatch(rf"##\s+{re.escape(section)}\s*", l)), None)
        if debut is None:
            raise FormatInattendu(f"section « {section} » introuvable dans l'index : gabarit changé ?")
        fin = next((i for i in range(debut + 1, len(lignes)) if re.match(r"##(?!#)", lignes[i])), len(lignes))
        lignes = lignes[debut + 1:fin]
    articles = [m for m in (_RE_LIEN_INDEX.match(l) for l in lignes) if m]
    if not articles:
        raise FormatInattendu("index sans aucune ligne « - [titre](url) » : gabarit changé ?")
    nom = source.options.get("nom") or "Nouvel article d'aide"
    base_url = source.options.get("url_publique")
    res: list[Element] = []
    vus: set[str] = set()
    for m in articles:
        titre = re.sub(r"\\([()\[\]])", r"\1", m.group("titre")).strip()
        desc = (m.group("desc") or "").strip()
        mots = mots_trouves_index(titre, desc)
        ident = _id_article(m.group("url"))
        if not mots or ident in vus:
            continue
        vus.add(ident)
        url = m.group("url").removesuffix(".md")
        contenu = desc or f"{titre} (page de l'index {source.url})."
        res.append(Element(id=f"{source.id}-{ident}", produit=source.produit, titre=f"{nom} — {titre}", version=None,
                           date_publication=None, url=url, contenu=f"{contenu}\nMots-clés D71 : {', '.join(mots)}.",
                           source_id=source.id, officielle=source.officielle))
    return res


PARSEURS = {
    "markdown_date": parser_markdown_date,
    "html_date": parser_html_date,
    "html_time_liens": parser_html_time_liens,
    "sections_suivies": parser_sections_suivies,
    "index_articles": parser_index_articles,
    "annonces_datees": parser_annonces_datees,
    "html_blog_liste": lambda html, source: parser_blog_liste(html, source)[0],
}


def analyser(source, client, borne: str | None = None) -> ResultatSource:
    reponse = client.get(source.url, accept="text/markdown, text/html")
    fmt = source.options.get("format")
    if not fmt:
        fmt = "markdown_date" if reponse.est_markdown else "html_date"
    if fmt not in PARSEURS:
        raise FormatInattendu(f"format d'analyse inconnu : {fmt!r}")
    if fmt in ("markdown_date", "annonces_datees") and "<html" in reponse.texte[:500].lower():
        raise FormatInattendu("page HTML reçue alors que du Markdown était attendu")
    if fmt == "html_blog_liste":
        elements, plus_ancienne = parser_blog_liste(reponse.texte, source)
        return ResultatSource(elements, plus_ancienne=plus_ancienne)
    return ResultatSource(PARSEURS[fmt](reponse.texte, source))
