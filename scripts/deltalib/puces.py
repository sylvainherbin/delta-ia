"""D95 : notes de version découpées en puces (`puces: [{genre, texte, noms}]`) dans le brut.

Le `contenu` d'une note de version arrive en un seul bloc ; R2 (D85) demande de la lire ajout par ajout. Ce module
découpe le Markdown en puces `- …` / `* …`, donne à chacune un genre d'après son premier mot (à défaut, d'après le
titre de section qui la porte) et relève les segments entre accents graves (`noms`). Le `contenu` reste intact.
Une note sans aucune puce n'a pas de champ `puces` : `decouper_puces` rend `None`, jamais une liste vide.
"""

from __future__ import annotations

import re

GENRES = ("ajout", "modification", "correctif", "retrait", "autre")

_MOTS_GENRE = {
    "ajout": {"added", "add", "adds", "new", "introduced", "introduces", "introducing", "launched", "launches",
              "released", "ajouté", "ajoutée", "ajoutés", "ajoutées", "ajout", "nouveau", "nouvelle", "nouveaux",
              "nouvelles", "nouveauté", "introduit", "introduite", "lancé", "lancée"},
    "modification": {"changed", "change", "changes", "improved", "improves", "improvements", "updated", "updates", "update", "improve",
                     "renamed", "redesigned", "reduced", "increased", "lowered", "raised", "moved", "replaced",
                     "reverted", "optimized", "enhanced", "switched", "modifié", "modifiée", "modifiés", "modifiées",
                     "amélioré", "améliorée", "améliorés", "améliorées", "amélioration", "mis", "renommé",
                     "renommée", "remplacé", "remplacée", "changé", "changée"},
    "correctif": {"fixed", "fix", "fixes", "resolved", "corrected", "corrigé", "corrigée", "corrigés", "corrigées",
                  "correction", "corrections", "correctif"},
    "retrait": {"removed", "remove", "removes", "deprecated", "deprecates", "dropped", "retired", "sunset",
                "supprimé", "supprimée", "supprimés", "supprimées", "retiré", "retirée", "retirés", "retirées",
                "déprécié", "dépréciée", "obsolète", "abandonné", "abandonnée"},
}
_GENRE_DU_MOT = {mot: genre for genre, mots in _MOTS_GENRE.items() for mot in mots}

# Titres de section (`## New Features`, `### Bug Fixes`) : repli quand le premier mot d'une puce ne tranche pas.
_TITRES = (
    (re.compile(r"\b(new features?|features?|added|what'?s new|nouveaut|ajout)", re.I), "ajout"),
    (re.compile(r"\b(improvement|changed|changes|updated|modif|am[ée]lior)", re.I), "modification"),
    (re.compile(r"\b(bug ?fix|fixes|fixed|correct)", re.I), "correctif"),
    (re.compile(r"\b(removed|removals?|deprecat|retrait|suppress)", re.I), "retrait"),
)

_PUCE = re.compile(r"^(\s*)[-*+]\s+(\S.*)$")
_TITRE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_PREFIXE_NOUS = re.compile(r"^(?:we(?:'ve|’ve| have)?|nous(?: avons)?)\s+", re.I)
_ETIQUETTE = re.compile(r"^(?:#\d+\s+|\[[^\]\n]{1,40}\]\s*|[A-Z][\w ./-]{0,40}:\s+)+")
_SEGMENT = re.compile(r"`([^`\n]+)`")
_MOT = re.compile(r"[\w’'-]+", re.UNICODE)


def _genre_du_premier_mot(texte: str) -> str | None:
    t = _PREFIXE_NOUS.sub("", texte.lstrip("*_ ").lstrip())
    m = _MOT.match(t)
    return _GENRE_DU_MOT.get(m.group().lower().rstrip("'’-")) if m else None


def genre_de(texte: str, titre_section: str | None = None) -> str:
    """Genre d'une puce : premier mot (après un éventuel « We've »), sinon premier mot après une étiquette de tête
    (`#49246`, `[Claude Tag]`, `Windows:`), sinon titre de la section, sinon `autre`."""
    genre = _genre_du_premier_mot(texte)
    if genre is None:
        genre = _genre_du_premier_mot(_ETIQUETTE.sub("", texte, count=1))
    if genre is None and titre_section:
        genre = next((g for motif, g in _TITRES if motif.search(titre_section)), None)
    return genre or "autre"


def noms_de(texte: str) -> list[str]:
    """Segments entre accents graves, dans l'ordre, sans doublon."""
    vus: dict[str, None] = {}
    for m in _SEGMENT.finditer(texte):
        nom = m.group(1).strip()
        if nom:
            vus.setdefault(nom, None)
    return list(vus)


def decouper_puces(contenu: str) -> list[dict] | None:
    """Puces d'un contenu Markdown, ou `None` s'il n'en a aucune. Les lignes de suite (indentées) et les sous-puces
    se rattachent à la puce qui les précède ; un titre ou un paragraphe non indenté la termine."""
    puces: list[dict] = []
    courante: list[str] | None = None
    section: str | None = None
    section_courante: str | None = None
    base: int | None = None

    def clore() -> None:
        nonlocal courante
        if courante is not None:
            texte = " ".join(" ".join(courante).split())
            puces.append({"genre": genre_de(texte, section_courante), "texte": texte, "noms": noms_de(texte)})
            courante = None

    for ligne in (contenu or "").splitlines():
        if not ligne.strip():
            continue
        titre = _TITRE.match(ligne)
        if titre:
            clore()
            section = titre.group(1)
            continue
        puce = _PUCE.match(ligne)
        if puce:
            indent = len(puce.group(1).expandtabs(4))
            if courante is not None and base is not None and indent > base:
                courante.append(puce.group(2))
                continue
            clore()
            base = indent
            courante, section_courante = [puce.group(2)], section
        elif courante is not None and ligne[:1].isspace():
            courante.append(ligne.strip())
        else:
            clore()
    clore()
    return puces or None


def ajouter_puces(nouveautes, sources) -> None:
    """Branche le découpage sur les sources qui déclarent `options.puces: true` (notes de version)."""
    avec = {s.id for s in sources if s.options.get("puces")}
    for e in nouveautes:
        if e.source_id in avec and not e.id.startswith("etat-initial-"):
            e.puces = decouper_puces(e.contenu)
