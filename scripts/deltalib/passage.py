"""Un passage de récupération pour un périmètre : sources, analyseurs, détection, fichier brut."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .analyseurs import ANALYSEURS
from .dates import analyser_date, aujourd_hui, maintenant_iso
from .etat import charger_etat, detecter, premier_passage, sources_connues
from .http import Client
from .modeles import Element, ErreurSource, empreinte_contenu
from .sources import Source

FENETRE_PREMIER_PASSAGE_JOURS = 30
FENETRE_AMORCAGE_SOURCE_JOURS = 7  # D30 : une source sans trace dans l'état est amorcée sur J-7
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
            "sources_amorcees": self.sources_amorcees,
            "empreintes": self.empreintes,
            "sources_en_echec": [e.en_dict() for e in self.echecs],
        }


def recuperer(sources: list[Source], client: Client, borne: str | None = None
              ) -> tuple[list[Element], list[Echec], list[str], list[str]]:
    """Interroge chaque source ; un échec n'arrête pas les autres. Retourne (éléments, échecs, traitées, ignorés)."""
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
    elements, echecs, traitees, ignores_hist = recuperer(sources, client, borne)
    # D30 : une source active sans aucune trace dans l'état reçoit la fenêtre d'amorçage (--depuis, sinon J-7),
    # même si l'état du périmètre existe déjà ; ses éléments plus anciens vont dans `ignores`.
    amorcees: list[str] = []
    fenetre_par_source: dict[str, date] = {}
    if not premier_passage(etat):
        connues = sources_connues(etat)
        for s in sources:
            if s.id in traitees and s.id not in connues:
                amorcees.append(s.id)
                fenetre_par_source[s.id] = depuis or (jour - timedelta(days=FENETRE_AMORCAGE_SOURCE_JOURS))
                journal.info("source %s sans trace dans l'état : amorçage à partir du %s", s.id, fenetre_par_source[s.id])
    nouveautes, ignores = detecter(elements, etat, fenetre, fenetre_par_source)
    lire_articles(nouveautes, sources, client, echecs)
    vus = etat.get("vus", {})
    ignores = sorted(set(ignores) | {i for i in ignores_hist if i not in vus})
    par_id = {e.id: e for e in elements}
    ignores_sources = {i: (par_id[i].source_id if i in par_id else _source_de_l_historique(i, sources)) for i in ignores}
    empreintes = {e.id: e.empreinte for e in elements if e.empreinte and (e.id in ignores or e in nouveautes)}
    return Bilan(perimetre, fenetre, borne, nouveautes, ignores, echecs, traitees, len(elements), empreintes,
                 ignores_sources, amorcees)


def lire_articles(nouveautes: list[Element], sources: list[Source], client: Client, echecs: list[Echec]) -> None:
    """A1 (26/09) : pour une source à option `lire_articles`, chaque nouvel article est lu (un GET) et son texte
    principal remplace le résumé de la liste dans `contenu`. Un article illisible garde le résumé et remonte en
    `sources_en_echec` (partiel), jamais en contenu vide."""
    from .analyseurs.html_notes import texte_article
    lues = {s.id for s in sources if s.options.get("lire_articles")}
    for e in nouveautes:
        if e.source_id not in lues or not e.url:
            continue
        try:
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
