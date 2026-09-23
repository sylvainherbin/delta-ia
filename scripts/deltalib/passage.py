"""Un passage de récupération pour un périmètre : sources, analyseurs, détection, fichier brut."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .analyseurs import ANALYSEURS
from .dates import aujourd_hui, maintenant_iso
from .etat import charger_etat, detecter, premier_passage
from .http import Client
from .modeles import Element, ErreurSource
from .sources import Source

FENETRE_PREMIER_PASSAGE_JOURS = 30
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
    nouveautes: list[Element]
    ignores: list[str]
    echecs: list[Echec]
    sources_traitees: list[str] = field(default_factory=list)
    elements_total: int = 0

    def en_dict(self) -> dict:
        return {
            "perimetre": self.perimetre,
            "genere_le": maintenant_iso(),
            "fenetre_depuis": self.fenetre_depuis.isoformat() if self.fenetre_depuis else None,
            "sources_traitees": self.sources_traitees,
            "elements_total": self.elements_total,
            "nouveautes": [e.en_dict() for e in self.nouveautes],
            "ignores": self.ignores,
            "sources_en_echec": [e.en_dict() for e in self.echecs],
        }


def recuperer(sources: list[Source], client: Client) -> tuple[list[Element], list[Echec], list[str]]:
    """Interroge chaque source ; un échec n'arrête pas les autres."""
    elements: list[Element] = []
    echecs: list[Echec] = []
    traitees: list[str] = []
    for s in sources:
        analyser = ANALYSEURS[s.type]
        try:
            resultat = analyser(s, client)
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
        journal.info("source %s : %d éléments", s.id, len(resultat.elements))
        elements.extend(resultat.elements)
        traitees.append(s.id)
    return elements, echecs, traitees


def executer(perimetre: str, sources: list[Source], chemin_etat: Path, client: Client,
             depuis: date | None = None, aujourd_hui_=None) -> Bilan:
    etat = charger_etat(chemin_etat)
    jour = aujourd_hui_ or aujourd_hui()
    fenetre = depuis
    if fenetre is None and premier_passage(etat):
        fenetre = jour - timedelta(days=FENETRE_PREMIER_PASSAGE_JOURS)
        journal.info("premier passage sans état : fenêtre limitée à partir du %s", fenetre)
    elements, echecs, traitees = recuperer(sources, client)
    nouveautes, ignores = detecter(elements, etat, fenetre)
    return Bilan(perimetre, fenetre, nouveautes, ignores, echecs, traitees, len(elements))
