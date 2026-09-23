"""Extracteurs déterministes, un par forme de page (D40, étape 1). Aucun appel à un modèle.

Chaque extracteur reçoit la documentation (`DocSource`) et les fichiers récupérés {nom: texte} ; il rend des
`EntreeExtraite`. Une page dont la structure attendue est absente lève `FormatInattendu`, jamais une liste vide.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..modeles import FormatInattendu
from .markdown import (Section, cellules, nettoyer, premier_paragraphe, premiere_liste, sections, tableaux,
                       usage_de)
from .modeles import EntreeExtraite

_RE_PLATEFORME_EXCLUE = re.compile(r"macOS|\bmac\b|Windows|WSL|\bCmd\b|Cmd\+|Option\+|iTerm", re.I)


def _rx(motif: str | None):
    return re.compile(motif, re.I) if motif else None


def _texte(fichiers: dict, nom: str = "page") -> str:
    if nom not in fichiers:
        raise FormatInattendu(f"fichier `{nom}` absent de la récupération")
    return fichiers[nom]


def _premier_code(cellule: str) -> str | None:
    m = re.search(r"`([^`]+)`", cellule)
    return m.group(1).strip() if m else None


def _sections_retenues(secs: list[Section], motif: str | None) -> list[Section]:
    if not motif:
        return []
    rx = re.compile(rf"^(?:{motif})$", re.I)
    return [s for s in secs if rx.match(s.titre)]


def _variante_exclue(v: str) -> bool:
    return not re.search(r"Linux", v) and bool(_RE_PLATEFORME_EXCLUE.search(v))


def _garder_linux(usage: str) -> bool:
    """D42 : une ligne de raccourci est gardée si au moins une variante n'est ni macOS ni Windows."""
    variantes = re.split(r",?\s+or\s+|,\s+", usage)
    return any(v.strip() and not _variante_exclue(v) for v in variantes)


# ----------------------------------------------------------------------------------------------- tableau

def tableau(doc, fichiers: dict) -> list[EntreeExtraite]:
    o = doc.options
    texte = _texte(fichiers)
    lignes, secs = sections(texte)
    exclure = _rx(o.get("exclure"))
    if o.get("section"):
        spans = _sections_retenues(secs, o["section"])
        if not spans:
            raise FormatInattendu(f"section « {o['section']} » introuvable")
    else:
        spans = [Section(0, "", "", 0, len(lignes), ())]
    res: list[EntreeExtraite] = []
    for sec in spans:
        cat_sec = (o.get("categorie_par_section") or {}).get(sec.titre, o.get("categorie"))
        cols = (o.get("colonnes_par_section") or {}).get(sec.titre, {})
        tabs = tableaux(lignes, sec.debut, sec.fin)
        if not tabs:
            raise FormatInattendu(f"aucun tableau dans la section « {sec.titre or 'page'} »")
        for tab in tabs:
            groupe = next((s.titre for s in reversed(secs) if s.debut < tab.debut), sec.titre) or None
            i_usage, i_desc = cols.get("usage", 0), cols.get("description", 1)
            i_nom = cols.get("nom", i_usage)
            for rang in tab.lignes:
                if len(rang) <= max(i_usage, i_desc, i_nom):
                    continue
                brut_usage, brut_desc = rang[i_usage], rang[i_desc]
                usage = nettoyer(brut_usage)
                if not usage:
                    continue
                nom = nettoyer(rang[i_nom]) if "nom" in cols else (_premier_code(brut_usage) or usage)
                categorie = cat_sec
                for marque, cat in (o.get("categorie_si_marque") or {}).items():
                    if re.search(rf"\*\*\[?{re.escape(marque)}\b", brut_desc):
                        categorie = cat
                if categorie in ("commandes", "skills") and nom.startswith("/"):
                    nom = nom.split()[0]
                if o.get("nom_majuscule") and not re.fullmatch(r"[A-Z][A-Z0-9_]+", nom):
                    continue
                if exclure and exclure.search(nom):
                    continue
                if o.get("filtre_plateforme") and not _garder_linux(usage):
                    continue
                autres = [nettoyer(c) for k, c in enumerate(rang) if k not in (i_usage, i_desc, i_nom) and c.strip()]
                description = nettoyer(brut_desc) + (" — " + " — ".join(autres) if autres else "")
                res.append(EntreeExtraite(
                    produit=doc.produit, categorie=categorie, nom=(o.get("prefixe_nom") or "") + nom, usage=usage,
                    description_source=description, url=doc.url_publique, libelle=doc.libelle, origine=doc.id,
                    groupe=groupe))
    if not res:
        raise FormatInattendu("tableaux trouvés mais aucune ligne retenue : gabarit changé ?")
    return res


# ----------------------------------------------------------------------------------------------- sections

def sections_page(doc, fichiers: dict) -> list[EntreeExtraite]:
    o = doc.options
    texte = _texte(fichiers)
    lignes, secs = sections(texte)
    niveaux = {int(n) for n in str(o.get("niveau", 3)).split(",")}
    parent = _rx(o.get("parent"))
    exclure_sec = _rx(o.get("exclure_sections"))
    exclure = _rx(o.get("exclure"))
    res: list[EntreeExtraite] = []
    for s in secs:
        if s.niveau not in niveaux:
            continue
        ancetres = s.chemin[:-1]
        if parent and not (ancetres and parent.search(ancetres[-1])):
            continue  # le parent est le titre immédiatement au-dessus, pas le titre de la page
        if exclure_sec and any(exclure_sec.search(a) for a in s.chemin):
            continue
        if exclure and exclure.search(s.titre):
            continue
        prochain = next((t.debut for t in secs if t.debut > s.debut), len(lignes))
        usage = usage_de(lignes, s.debut + 1, s.fin) or (s.titre if "`" in s.brut else None)
        if not usage:
            continue
        desc = premier_paragraphe(lignes, s.debut + 1, prochain) or ""
        res.append(EntreeExtraite(
            produit=doc.produit, categorie=o["categorie"], nom=(o.get("prefixe_nom") or "") + s.titre, usage=usage,
            description_source=nettoyer(desc), url=f"{doc.url_publique}#{_ancre(s.titre)}", libelle=doc.libelle,
            origine=doc.id, groupe=ancetres[-1] if ancetres else None))
    if not res:
        raise FormatInattendu(f"aucune section de niveau {sorted(niveaux)} retenue : gabarit changé ?")
    return res


def _ancre(titre: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", titre.lower()))


# ----------------------------------------------------------------------------------------------- pages

def pages(doc, fichiers: dict) -> list[EntreeExtraite]:
    """Une page de fonctionnalité = une entrée ; l'identifiant suit le chemin de la page, pas son titre."""
    res: list[EntreeExtraite] = []
    for chemin, conf in doc.options["pages"].items():
        cle = f"page:{chemin}"
        if cle not in fichiers:
            continue  # page non récupérée : signalée par fetch, ses entrées restent inchangées
        conf = conf if isinstance(conf, dict) else {"categorie": conf}
        texte = fichiers[cle]
        lignes, secs = sections(texte)
        titre = next((s for s in secs if s.niveau == 1), None)
        if titre is None:
            raise FormatInattendu(f"page {chemin} : aucun titre `# …`")
        debut = titre.debut + 1
        desc = None
        for i in range(debut, min(len(lignes), debut + 6)):
            if lignes[i].startswith("> ") and "Documentation Index" not in lignes[i] and "llms.txt" not in lignes[i]:
                desc = lignes[i][2:]
                break
        desc = desc or premier_paragraphe(lignes, debut, len(lignes)) or ""
        usage = usage_de(lignes, debut, len(lignes))
        if not usage:
            raise FormatInattendu(f"page {chemin} : ni code, ni liste, ni paragraphe")
        res.append(EntreeExtraite(
            produit=conf.get("produit", doc.produit), categorie=conf["categorie"], nom=titre.titre, usage=usage,
            description_source=nettoyer(desc), url=doc.base + chemin, libelle=titre.titre, origine=doc.id,
            groupe=None, cle=f"page-{chemin}"))
    if not res:
        raise FormatInattendu("aucune page de fonctionnalité disponible")
    return res


# ----------------------------------------------------------------------------------------------- plugins Claude Code

def plugins_cc(doc, fichiers: dict) -> list[EntreeExtraite]:
    o = doc.options
    texte = _texte(fichiers)
    debut = texte.find(f"## {o['section']}")
    fin = texte.find(f"## {o['fin_section']}")
    if debut < 0 or fin < 0:
        raise FormatInattendu("section de la marketplace officielle introuvable")
    lignes, secs = sections(texte[debut:fin])
    res: list[EntreeExtraite] = []
    vus: set[str] = set()

    def ajouter(nom: str, usage: str, desc: str, groupe: str | None):
        if nom in vus:
            return
        vus.add(nom)
        res.append(EntreeExtraite(produit=doc.produit, categorie="plugins", nom=nom, usage=usage, description_source=desc,
                                  url=f"{doc.url_publique}#{_ancre(groupe or o['section'])}", libelle=doc.libelle,
                                  origine=doc.id, groupe=groupe))

    for tab in tableaux(lignes):
        i = next((k for k, h in enumerate(tab.entetes) if h.lower() == "plugin"), None)
        if i is None:
            continue
        groupe = next((s.titre for s in reversed(secs) if s.debut < tab.debut), None)
        for rang in tab.lignes:
            nom = _premier_code(rang[i])
            if nom:
                ajouter(nom, " | ".join(nettoyer(c) for c in rang), " — ".join(
                    f"{nettoyer(h)} : {nettoyer(c)}" for h, c in zip(tab.entetes, rang)), groupe)
    for k, l in enumerate(lignes):
        groupe = next((s.titre for s in reversed(secs) if s.debut < k), None)
        m = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*:\s*(.+)$", l)
        if m:
            codes = re.findall(r"`([a-z0-9-]+)`", m.group(2))
            if codes:  # « **Catégorie** : `a`, `b` »
                for c in codes:
                    ajouter(c, nettoyer(l.strip()[1:].strip()), f"{nettoyer(m.group(1))} : {nettoyer(m.group(2))}", groupe)
            elif re.fullmatch(r"[a-z0-9-]+", m.group(1)):  # « **nom-du-plugin** : description »
                ajouter(m.group(1), nettoyer(l.strip()[1:].strip()), nettoyer(m.group(2)), groupe)
        for nom in re.findall(r"The `([a-z0-9-]+)` plugin", l):
            ajouter(nom, nom, nettoyer(l), groupe)
    if not res:
        raise FormatInattendu("aucun plugin reconnu dans la marketplace officielle")
    return res


# ----------------------------------------------------------------------------------------------- Codex : config.toml

_RE_CHAINE = r'"((?:[^"\\]|\\.)*)"'


def _chaines_apres(bloc: str, champ: str) -> str | None:
    m = re.search(rf"\b{champ}:\s*((?:{_RE_CHAINE}\s*\+?\s*)+)", bloc)
    if not m:
        return None
    parts = re.findall(_RE_CHAINE, m.group(1))
    return "".join(p.encode().decode("unicode_escape") if "\\" in p else p for p in parts)


def configtable(doc, fichiers: dict) -> list[EntreeExtraite]:
    o = doc.options
    texte = _texte(fichiers)
    debut = texte.find(f"## `{o['section']}`")
    fin = texte.find(f"## `{o['fin_section']}`") if o.get("fin_section") else len(texte)
    if debut < 0:
        raise FormatInattendu(f"section `{o['section']}` introuvable")
    zone = texte[debut:fin if fin > debut else len(texte)]
    if "<ConfigTable" not in zone:
        raise FormatInattendu("aucun composant <ConfigTable> dans la section")
    exclure = _rx(o.get("exclure"))
    positions = [m.start() for m in re.finditer(r"\bkey:\s*\"", zone)]
    res: list[EntreeExtraite] = []
    for k, p in enumerate(positions):
        bloc = zone[p:positions[k + 1] if k + 1 < len(positions) else len(zone)]
        cle = _chaines_apres(bloc, "key")
        type_ = _chaines_apres(bloc, "type") or ""
        desc = _chaines_apres(bloc, "description") or ""
        if not cle:
            raise FormatInattendu(f"objet ConfigTable sans clé lisible près de : {bloc[:60]!r}")
        if exclure and exclure.search(cle):
            continue
        res.append(EntreeExtraite(
            produit=doc.produit, categorie="parametres", nom=cle, usage=cle,
            description_source=nettoyer(f"Type : {type_}. {desc}"), url=f"{doc.url_publique}#{_ancre(o['section'])}",
            libelle=doc.libelle, origine=doc.id, groupe="config.toml"))
    if len(res) < 20:
        raise FormatInattendu(f"seulement {len(res)} clés config.toml lues : format du ConfigTable changé ?")
    return res


# ----------------------------------------------------------------------------------------------- Codex : CLI (HTML)

def _classer_table_codex(nom: str) -> tuple[str, str] | None:
    """(catégorie, contexte) d'un tableau ConfigTable de la page CLI, ou None s'il est exclu (D42)."""
    if re.search(r"Mac|Windows", nom):
        return None
    if nom.startswith("mcp"):
        return ("mcp", "codex mcp")
    if nom == "commandOverview":
        return ("commandes", "")
    if nom.endswith("Commands"):
        return ("commandes", "")
    return ("parametres", "")


def codex_cli(doc, fichiers: dict) -> list[EntreeExtraite]:
    md = _texte(fichiers, "md")
    html = _texte(fichiers, "page")
    noms = re.findall(r"<ConfigTable[^>]*?options=\{(\w+)\}", md, re.S)
    if not noms:
        raise FormatInattendu("aucune référence <ConfigTable options={…}> dans le Markdown")
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    cfg = [t for t in tables if t.find("tr") and [c.get_text(" ", strip=True) for c in t.find("tr").find_all(["th", "td"])][:1] == ["Key"]]
    if len(cfg) != len(noms):
        raise FormatInattendu(f"{len(noms)} ConfigTable dans le Markdown mais {len(cfg)} tableaux « Key » dans le HTML")
    res: list[EntreeExtraite] = []
    vus: set[str] = set()

    def ajouter(categorie, nom, usage, desc, groupe, ancre):
        cle = f"{categorie}:{nom}"
        if cle in vus:
            return
        vus.add(cle)
        res.append(EntreeExtraite(produit=doc.produit, categorie=categorie, nom=nom, usage=usage, description_source=desc,
                                  url=f"{doc.url_publique}#{ancre}" if ancre else doc.url_publique, libelle=doc.libelle,
                                  origine=doc.id, groupe=groupe))

    for nom_table, t in zip(noms, cfg):
        classe = _classer_table_codex(nom_table)
        if classe is None:
            continue
        categorie, contexte = classe
        titre = t.find_previous(["h2", "h3"])
        groupe = titre.get_text(" ", strip=True) if titre else nom_table
        ancre = titre.get("id") if titre else None
        commande = groupe.split(" and ")[0] if groupe.startswith("codex ") else ""
        for tr in t.find_all("tr")[1:]:
            c = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(c) < 3 or not c[0]:
                continue
            cle, valeurs, details = c[0], c[1], c[2]
            if nom_table == "commandOverview":
                if re.search(r"macOS|Windows", details) and "Linux" not in details:
                    continue
                ajouter("commandes", cle, cle, f"{details} (maturité : {valeurs})", groupe, ancre)
            elif categorie == "commandes" or (categorie == "mcp" and nom_table.endswith("Commands")):
                nom = f"{commande} {cle}".strip() if not cle.startswith("codex") else cle
                ajouter(categorie, nom, nom, details, groupe, ancre)
            else:
                prefixe = commande or ("codex" if nom_table == "globalFlagOptions" else contexte)
                nom = f"{prefixe} {cle}".strip()
                ajouter(categorie, nom, nom, f"{details} (valeurs : {valeurs})" if valeurs else details, groupe, ancre)
    for t in tables:
        entetes = [c.get_text(" ", strip=True) for c in t.find("tr").find_all(["th", "td"])] if t.find("tr") else []
        if not entetes or entetes[0] not in ("Command", "Slash command"):
            continue
        titre = t.find_previous(["h2", "h3"])
        groupe = titre.get_text(" ", strip=True) if titre else ""
        ide = entetes[0] == "Slash command" or "Extension" in groupe
        for tr in t.find_all("tr")[1:]:
            c = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not c or not c[0]:
                continue
            nom = c[0].split()[0] if c[0].startswith("/") else c[0]
            if ide and f"commandes:{nom}" in vus:
                continue  # commande `/` déjà décrite pour la CLI
            ajouter("commandes", ("IDE " + nom) if ide and not nom.startswith("/") else nom, c[0],
                    " — ".join(x for x in c[1:] if x), groupe, titre.get("id") if titre else None)
    # raccourcis : liste « Interactive shortcuts » du Markdown
    lignes, secs = sections(md)
    sec = next((s for s in secs if s.titre == "Interactive shortcuts"), None)
    if sec is None:
        raise FormatInattendu("section « Interactive shortcuts » introuvable")
    for l in lignes[sec.debut + 1:sec.fin]:
        if re.match(r"^\s*[-*]\s+", l):
            puce = nettoyer(l.strip()[1:])
            touches = re.findall(r"<kbd>(.*?)</kbd>", l)
            nom = "+".join(touches[:2]) if touches else (_premier_code(l) or puce[:40])
            ajouter("raccourcis", nom, puce, puce, "Interactive shortcuts", "interactive-shortcuts")
    if len(res) < 30:
        raise FormatInattendu(f"seulement {len(res)} entrées lues sur la page CLI de Codex")
    return res


EXTRACTEURS = {
    "tableau": tableau,
    "sections": sections_page,
    "pages": pages,
    "plugins_cc": plugins_cc,
    "configtable": configtable,
    "codex_cli": codex_cli,
}
