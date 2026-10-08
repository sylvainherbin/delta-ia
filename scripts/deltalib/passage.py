"""Un passage de récupération pour un périmètre : sources, analyseurs, détection, fichier brut."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .analyseurs import ANALYSEURS
from .dates import analyser_date, aujourd_hui, maintenant_iso
from .etat import charger_etat, detecter, premier_passage, sources_connues
from .http import Client
from .modeles import Element, ErreurSource, FormatInattendu, empreinte_contenu
from .puces import ajouter_puces
from .revisions import comparer_phrases, textes_precedents
from .sources import Source
from .textes import normaliser_contenu

FENETRE_PREMIER_PASSAGE_JOURS = 30
FENETRE_AMORCAGE_SOURCE_JOURS = 7  # D30 : une source sans trace dans l'état est amorcée sur J-7, sauf option de source `amorcage_jours`
journal = logging.getLogger("delta")


@dataclass
class Echec:
    id: str
    url: str
    erreur: str
    partiel: bool = False

    def en_dict(self) -> dict:
        return {"id": self.id, "url": self.url, "erreur": self.erreur, "partiel": self.partiel}


@dataclass
class Bilan:
    perimetre: str
    fenetre_depuis: date | None
    borne: str | None
    nouveautes: list[Element]
    ignores: list[str]
    echecs: list[Echec]
    sources_traitees: list[str] = field(default_factory=list)
    elements_total: int = 0
    empreintes: dict = field(default_factory=dict)
    ignores_sources: dict = field(default_factory=dict)
    sources_amorcees: list[str] = field(default_factory=list)
    ignores_raisons: dict[str, str] = field(default_factory=dict)
    contenus_suivis: dict[str, str] = field(default_factory=dict)
    echeances: dict | None = None  # D71 : résumé à 14 jours (`echeances.resume_echeances`), écrit par fetch.py dans raw/echeances.json

    def en_dict(self) -> dict:
        return {
            "perimetre": self.perimetre,
            "genere_le": maintenant_iso(),
            "fenetre_depuis": self.fenetre_depuis.isoformat() if self.fenetre_depuis else None,
            "borne": self.borne,
            "sources_traitees": self.sources_traitees,
            "elements_total": self.elements_total,
            "nouveautes": [e.en_dict() for e in self.nouveautes],
            "ignores": self.ignores,
            "ignores_sources": self.ignores_sources,
            "ignores_raisons": self.ignores_raisons,
            "sources_amorcees": self.sources_amorcees,
            "empreintes": self.empreintes,
            "contenus_suivis": self.contenus_suivis,
            "sources_en_echec": [e.en_dict() for e in self.echecs],
        }


def fenetre_amorcage(source: Source, jour: date, depuis: date | None) -> date:
    """D30 : début de la fenêtre d'amorçage d'une source sans trace : `--depuis`, sinon J moins l'option de source
    `amorcage_jours` (étape 2c : 120 pour les dépréciations, dont les annonces restent ouvertes des mois), sinon J-7."""
    return depuis or (jour - timedelta(days=int(source.options.get("amorcage_jours", FENETRE_AMORCAGE_SOURCE_JOURS))))


def recuperer(sources: list[Source], client: Client, borne: str | None = None, retraits: dict | None = None
              ) -> tuple[list[Element], list[Echec], list[str], list[str]]:
    """Interroge chaque source ; un échec n'arrête pas les autres. Retourne (éléments, échecs, traitées, ignorés).
    `retraits` (facultatif, étape 2d) reçoit, par identifiant de source, (source, retraits extraits, signalements)."""
    elements: list[Element] = []
    echecs: list[Echec] = []
    traitees: list[str] = []
    ignores: list[str] = []
    for s in sources:
        analyser = ANALYSEURS[s.type]
        try:
            resultat = analyser(s, client, borne)
        except ErreurSource as e:
            journal.warning("source %s en échec : %s", s.id, e)
            echecs.append(Echec(s.id, s.url, f"{type(e).__name__}: {e}"))
            continue
        except Exception as e:  # défaut d'un analyseur : signalé, jamais propagé aux autres sources
            journal.exception("source %s : erreur interne", s.id)
            echecs.append(Echec(s.id, s.url, f"erreur interne {type(e).__name__}: {e}"))
            continue
        if resultat.partiel:
            journal.warning("source %s partielle : %s", s.id, resultat.partiel)
            echecs.append(Echec(s.id, s.url, resultat.partiel, partiel=True))
        if retraits is not None and resultat.retraits is not None:
            retraits[s.id] = (s, resultat.retraits, resultat.retraits_signales)
        if s.options.get("suivre_revisions"):
            for e in resultat.elements:
                e.empreinte = empreinte_contenu(e.contenu)
        trou = detecter_trou(resultat, borne)
        if trou:
            journal.warning("source %s : %s", s.id, trou)
            echecs.append(Echec(s.id, s.url, trou, partiel=True))
        journal.info("source %s : %d éléments", s.id, len(resultat.elements))
        elements.extend(resultat.elements)
        ignores.extend(resultat.ignores)
        traitees.append(s.id)
    return elements, echecs, traitees, ignores


def detecter_trou(resultat, borne: str | None) -> str | None:
    """D4 : si la date la plus ancienne vue par la source est postérieure à la borne, il peut manquer des entrées."""
    if not borne:
        return None
    plus_ancienne = resultat.plus_ancienne
    if plus_ancienne is None:
        dates = [e.date_publication for e in resultat.elements if e.date_publication]
        plus_ancienne = min(dates) if dates else None
    if plus_ancienne and plus_ancienne > borne:
        return f"trou possible entre {borne} et {plus_ancienne}"
    return None


def executer(perimetre: str, sources: list[Source], chemin_etat: Path, client: Client,
             depuis: date | None = None, aujourd_hui_=None) -> Bilan:
    etat = charger_etat(chemin_etat)
    jour = aujourd_hui_ or aujourd_hui()
    fenetre = depuis
    if fenetre is None and premier_passage(etat):
        fenetre = jour - timedelta(days=FENETRE_PREMIER_PASSAGE_JOURS)
        journal.info("premier passage sans état : fenêtre limitée à partir du %s", fenetre)
    # D4 : la borne est la date du dernier `--valider`, sinon le début de la fenêtre
    borne = analyser_date(etat.get("maj_le")) or (fenetre.isoformat() if fenetre else None)
    retraits_sources: dict = {}
    elements, echecs, traitees, ignores_hist = recuperer(sources, client, borne, retraits_sources)
    # D30 : une source active sans aucune trace dans l'état reçoit la fenêtre d'amorçage (--depuis, sinon J-7),
    # même si l'état du périmètre existe déjà ; ses éléments plus anciens vont dans `ignores`.
    amorcees: list[str] = []
    fenetre_par_source: dict[str, date] = {}
    if not premier_passage(etat):
        connues = sources_connues(etat)
        for s in sources:
            if s.id in traitees and s.id not in connues:
                amorcees.append(s.id)
                fenetre_par_source[s.id] = fenetre_amorcage(s, jour, depuis)
                journal.info("source %s sans trace dans l'état : amorçage à partir du %s", s.id, fenetre_par_source[s.id])
    elif depuis is None:  # premier passage du périmètre : fenêtre de 30 jours, sauf pour une source qui déclare la sienne
        for s in sources:
            if s.id in traitees and "amorcage_jours" in s.options:
                fenetre_par_source[s.id] = fenetre_amorcage(s, jour, None)
    nouveautes, ignores = detecter(elements, etat, fenetre, fenetre_par_source)
    # D76 : les textes restent en lecture seule jusqu'à --valider, même lors d'un amorçage.
    precedents = textes_precedents(chemin_etat.parent.parent, perimetre,
                                   {e.id: etat["vus"][e.id]["empreinte"] for e in nouveautes if e.revision})
    ignores_raisons = {}
    for e in nouveautes:
        if e.revision and e.id in precedents:
            e.changements = comparer_phrases(precedents[e.id], e.contenu)
            if not any(e.changements[k] for k in ("ajoutees", "retirees", "modifiees")):
                ignores.append(e.id)
                ignores_raisons[e.id] = "revision_de_forme"
    nouveautes = [e for e in nouveautes if e.id not in ignores_raisons]
    # Étape 2a : une source à option `amorcage_silencieux` (index d'articles d'aide, éléments non datés) n'annonce rien à
    # sa première lecture : l'existant va dans `ignores`, `--valider` l'inscrit comme référence pour les passages suivants.
    premieres = {s.id for s in sources if s.id in traitees and (premier_passage(etat) or s.id in amorcees)}
    silencieuses = {s.id for s in sources if s.options.get("amorcage_silencieux") and s.id in premieres}
    reference_silencieuse = {sid: sum(1 for e in nouveautes if e.source_id == sid) for sid in silencieuses}
    if silencieuses:
        ignores = sorted(set(ignores) | {e.id for e in nouveautes if e.source_id in silencieuses})
        nouveautes = [e for e in nouveautes if e.source_id not in silencieuses]
    nouveautes, ignores = regrouper_etat_initial(perimetre, sources, premieres, nouveautes, ignores, reference_silencieuse)
    nouveautes = echeances_du_jour(retraits_sources, etat, jour, echecs) + nouveautes  # non datées : en tête, comme `detecter` (D3)
    lire_articles(nouveautes, sources, client, echecs)
    ajouter_puces(nouveautes, sources)  # D95 : après la lecture des articles, `contenu` est définitif
    vus = etat.get("vus", {})
    ignores = sorted(set(ignores) | {i for i in ignores_hist if i not in vus})
    par_id = {e.id: e for e in elements}
    ignores_sources = {i: (par_id[i].source_id if i in par_id else _source_de_l_historique(i, sources)) for i in ignores}
    empreintes = {e.id: e.empreinte for e in elements if e.empreinte}
    contenus_suivis = {e.id: normaliser_contenu(e.contenu).strip() for e in elements if e.empreinte}
    from .echeances import resume_echeances
    resume = resume_echeances(perimetre, sources, retraits_sources, echecs, jour, maintenant_iso())
    return Bilan(perimetre, fenetre, borne, nouveautes, ignores, echecs, traitees, len(elements), empreintes,
                 ignores_sources, amorcees, ignores_raisons, contenus_suivis, resume)


_RE_DATE_ECHEANCE = re.compile(r"(\d{4}-\d{2}-\d{2})-j\d+$")


def echeances_du_jour(retraits_sources: dict, etat: dict, jour: date, echecs: list[Echec]) -> list[Element]:
    """Étape 2d : éléments d'échéance des sources qui déclarent `echeances`. Hors de la fenêtre d'amorçage et du regroupement
    de l'état initial (leur identifiant `echeance-…` est propre à l'échéance, pas à l'annonce) : seul le suivi des identifiants
    déjà vus (`detecter`, `state/<p>.json`) écarte une échéance déjà signalée. Triées par date de retrait croissante."""
    from .echeances import produire_echeances
    produits: list[Element] = []
    for s, retraits, signales in retraits_sources.values():
        elements, message = produire_echeances(s, retraits, signales, jour)
        if message:
            journal.warning("source %s : %s", s.id, message)
            echecs.append(Echec(s.id, s.url, message, partiel=True))
        produits.extend(elements)
    nouvelles, _ = detecter(produits, etat, None)
    return sorted(nouvelles, key=lambda e: (_RE_DATE_ECHEANCE.search(e.id).group(1), e.id))


def _ligne_page(e: Element) -> str:
    """Une ligne pour l'état initial : titre, adresse et première phrase de la page (160 caractères au plus)."""
    resume = next((l.strip() for l in e.contenu.splitlines() if l.strip() and not l.lstrip().startswith(("#", ">", "|", "-", "*", "<"))), "")
    resume = resume if len(resume) <= 160 else resume[:157].rsplit(" ", 1)[0] + "…"
    return f"- {e.titre} ({e.url})" + (f" : {resume}" if resume else "")


def regrouper_etat_initial(perimetre: str, sources: list[Source], premieres: set[str], nouveautes: list[Element],
                           ignores: list[str], reference_silencieuse: dict[str, int]) -> tuple[list[Element], list[str]]:
    """Étape 2a : les sources à option `etat_initial` (valeur = titre de l'élément) n'annoncent pas chacune leur état à la
    première lecture : un seul élément, une ligne par page, remplace leurs nouveautés. Les pages elles-mêmes vont dans
    `ignores` (avec leur empreinte) : `--valider` les inscrit, et une modification ultérieure revient en révision page
    par page. Les index d'articles lus en silence y figurent en une ligne (nombre d'articles enregistrés comme référence)."""
    groupes: dict[str, list[Source]] = {}
    for s in sources:
        titre = s.options.get("etat_initial")
        if titre and s.id in premieres:
            groupes.setdefault(titre, []).append(s)
    for titre, membres in groupes.items():
        ids = {m.id for m in membres}
        pages = [e for e in nouveautes if e.source_id in ids and not e.revision]
        lignes = [_ligne_page(e) for e in pages]
        lignes += [f"- Index {m.url} : {reference_silencieuse[m.id]} article(s) de ce sujet enregistré(s) comme référence ; "
                   "les prochains nouveaux articles seront signalés un par un"
                   for m in membres if reference_silencieuse.get(m.id)]
        if not lignes:
            continue
        premier = pages[0] if pages else None
        ident = f"etat-initial-{perimetre}-{hashlib.sha1(','.join(sorted(ids)).encode()).hexdigest()[:8]}"
        element = Element(id=ident, produit=(premier.produit if premier else membres[0].produit), titre=titre, version=None,
                          date_publication=None, url=(premier.url if premier else membres[0].url),
                          contenu=f"Première lecture des sources suivies : état actuel de {len(pages)} élément(s) (pages d'aide, annonces).\n" + "\n".join(lignes),
                          source_id=(premier.source_id if premier else membres[0].id), officielle=all(m.officielle for m in membres))
        retirees = {e.id for e in pages}
        nouveautes = [element] + [e for e in nouveautes if e.id not in retirees]
        ignores = sorted(set(ignores) | retirees)
    return nouveautes, ignores


TAILLE_MAX_MARKDOWN = 6000


def texte_markdown(texte: str) -> str:
    """Étape 2a : début d'un article d'aide en Markdown, pour `contenu` ; page vide ou HTML reçue : FormatInattendu."""
    if not texte.strip() or "<html" in texte[:500].lower():
        raise FormatInattendu("article Markdown vide ou page HTML reçue")
    lignes = [l for l in texte.splitlines() if not l.startswith("> For the complete documentation index")]
    res = "\n".join(lignes).strip()
    return res if len(res) <= TAILLE_MAX_MARKDOWN else res[:TAILLE_MAX_MARKDOWN].rsplit("\n", 1)[0] + "\n[… texte tronqué]"


def lire_articles(nouveautes: list[Element], sources: list[Source], client: Client, echecs: list[Echec]) -> None:
    """A1 (26/09) : pour une source à option `lire_articles`, chaque nouvel article est lu (un GET) et son texte
    principal remplace le résumé de la liste dans `contenu`. Un article illisible garde le résumé et remonte en
    `sources_en_echec` (partiel), jamais en contenu vide."""
    from .analyseurs.html_notes import texte_article
    lues = {s.id: s.options["lire_articles"] for s in sources if s.options.get("lire_articles")}
    for e in nouveautes:
        if e.source_id not in lues or not e.url:
            continue
        try:
            if lues[e.source_id] == "markdown":  # étape 2a : article d'aide servi en Markdown (`<url>.md`)
                e.contenu = texte_markdown(client.get(e.url if e.url.endswith(".md") else e.url + ".md",
                                                      accept="text/markdown").texte)
            else:
                e.contenu = texte_article(client.get(e.url, accept="text/html").texte)
        except ErreurSource as err:
            echecs.append(Echec(e.source_id, e.url, f"article illisible : {type(err).__name__}: {err}", partiel=True))
            journal.warning("source %s : article %s illisible : %s", e.source_id, e.url, err)


def _source_de_l_historique(ident: str, sources: list[Source]) -> str | None:
    """Un identifiant d'historique (`<produit>-<version>`) vient de la source `github_changelog` de ce produit."""
    for s in sources:
        if s.type == "github_changelog" and ident.startswith(f"{s.produit}-"):
            return s.id
    return None
