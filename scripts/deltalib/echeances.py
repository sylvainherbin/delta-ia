"""Étape 2d : échéances de retrait des modèles et fonctionnalités, lues dans les pages de dépréciations.

Deux temps :
- `extraire_retraits` lit chaque tableau des annonces (`options.parents`, comme `annonces_datees`) : une ligne = un retrait
  {modèle ou fonctionnalité, date de retrait, date d'annonce, remplacement, URL de la section}. Une date de retrait
  illisible, ou qui n'est qu'une borne (« at earliest », « not sooner than »), est signalée, jamais devinée.
- `produire_echeances` transforme les retraits à venir en éléments bruts d'identifiant stable
  `echeance-<source>-<modèle normalisé>-<AAAA-MM-JJ>-j14` (retrait dans 2 à 14 jours) ou `…-j1` (dans 1 jour). Le suivi des
  identifiants déjà vus (`state/<p>.json`, `etat.detecter`) empêche toute répétition ; un identifiant ne dépend jamais du
  jour du passage, donc un passage manqué rattrape l'échéance tant que le retrait n'est pas passé.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from .dates import analyser_date
from .kb.markdown import cellules, nettoyer, sections as decouper
from .modeles import Element

PREFIXE = "echeance-"
PALIERS = ((1, "j1"), (14, "j14"))  # jours restants au plus -> suffixe ; le plus urgent d'abord
MAX_SIGNALES = 8  # lignes détaillées dans un message de signalement
TAILLE_MAX_PROSE = 700

_RE_TRAITS = re.compile("[‐-―−]")  # tirets typographiques (U+2011 dans « 2026‑08‑26 »)
_RE_BORNE = re.compile(r"\b(at earliest|earliest|not sooner than|no sooner than|no earlier than|approximately|tentative)\b|~", re.I)
_RE_SEPARATEUR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_RE_TITRE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\s*:\s*(.*)$")
_RE_BALISE = re.compile(r"^\s*</?(Note|Tip|Warning|Info)\b[^>]*>\s*$")
_ABSENT = {"", "-", "--", "---", "n/a", "none", "—", "–"}


@dataclass
class Retrait:
    modele: str  # modèle ou fonctionnalité, tel que la page l'écrit (backticks et liens retirés)
    cle: str  # modèle normalisé : premier nom de la cellule, en minuscules, `[a-z0-9]` séparés par `-`
    date_retrait: str | None  # AAAA-MM-JJ, None si illisible ou si ce n'est qu'une borne
    ferme: bool  # False : la date est une borne (« not sooner than… »)
    date_annonce: str | None  # lue dans le titre `### AAAA-MM-JJ: …` de l'annonce, None sans date
    annonce: str  # titre de l'annonce, sans la date
    remplacement: str | None
    detail: str | None  # colonne « Update » des tableaux de fonctionnalités
    url: str  # URL de la section de l'annonce
    prose: str  # texte de l'annonce d'origine, sans les tableaux
    brut: str  # contenu de la cellule de date, tel quel


@dataclass
class Signalement:
    genre: str  # `date_illisible`, `date_non_ferme`, `annonce_sans_retrait`
    texte: str
    date_retrait: str | None = None
    date_annonce: str | None = None


def normaliser_modele(texte: str) -> str:
    """`gpt-5.4-cyber` -> `gpt-5-4-cyber`. Premier nom d'une cellule à alias (`a | b, c` -> `a`), sans accents."""
    premier = re.split(r"[|,;]", texte, maxsplit=1)[0]
    t = unicodedata.normalize("NFKD", premier)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def ancre(titre: str, source) -> str:
    """Ancre d'un titre, selon le moteur du site : option `ancre_points: tiret` (platform.claude.com : `4.5` -> `4-5`) ou,
    par défaut, ponctuation retirée (developers.openai.com : `5.4` -> `54`). Vérifié sur les pages HTML réelles le 01/10/2026."""
    t = titre.lower()
    if source.options.get("ancre_points") == "tiret":
        t = t.replace(".", "-")
    t = re.sub(r"[^\w\s-]", "", t)
    return re.sub(r"[\s]+", "-", t.strip()).strip("-")


def lire_date_retrait(cellule: str) -> tuple[str | None, bool]:
    """(date ISO ou None, ferme). `ferme` est faux pour une borne : la date n'est alors pas celle d'un retrait annoncé."""
    texte = _RE_TRAITS.sub("-", nettoyer(cellule))
    iso = analyser_date(texte)
    return iso, not _RE_BORNE.search(texte)


def _colonnes(entetes: list[str]) -> dict | None:
    """Colonnes d'un tableau de retraits d'après ses en-têtes ; None si ce n'est pas un tableau de dates de retrait."""
    bas = [nettoyer(h).lower() for h in entetes]
    date_i = next((i for i, h in enumerate(bas) if "date" in h), None)
    if date_i is None:
        return None
    rempl = next((i for i, h in enumerate(bas) if re.search(r"replacement|substitute", h)), None)
    update = next((i for i, h in enumerate(bas) if h == "update"), None)
    exclus = {date_i, rempl, update} | {i for i, h in enumerate(bas) if "price" in h}
    libres = [i for i in range(len(bas)) if i not in exclus]
    modele = next((i for i in libres if re.search(r"model|system|snapshot|endpoint", bas[i])), libres[0] if libres else None)
    if modele is None and update is None:
        return None
    return {"date": date_i, "modele": modele, "remplacement": rempl, "update": update}


def _tableaux(lignes: list[str]):
    """Blocs de lignes `|…|` consécutives : (en-têtes, lignes de données)."""
    bloc: list[str] = []
    for l in lignes + [""]:
        if l.lstrip().startswith("|"):
            bloc.append(l)
            continue
        if len(bloc) >= 2 and _RE_SEPARATEUR.match(bloc[1]):
            yield cellules(bloc[0]), [cellules(x) for x in bloc[2:]]
        bloc = []


def _prose(lignes: list[str]) -> str:
    """Texte de l'annonce sans les tableaux, sous-titres ni balises : l'annonce d'origine, en quelques phrases."""
    mots = [l.strip() for l in lignes if l.strip() and not l.lstrip().startswith(("|", "#")) and not _RE_BALISE.match(l)]
    t = nettoyer(" ".join(mots))
    return t if len(t) <= TAILLE_MAX_PROSE else t[:TAILLE_MAX_PROSE - 1].rsplit(" ", 1)[0] + "…"


def extraire_retraits(texte: str, source) -> tuple[list[Retrait], list[Signalement]]:
    """Retraits de toutes les annonces de la page, et signalements (date illisible, date non ferme, annonce sans retrait
    lisible). Ne lève jamais d'erreur de format : la page a déjà été validée par `parser_annonces_datees`."""
    from .analyseurs.html_notes import _annonces
    lignes, secs = decouper(texte)
    base = re.sub(r"\.md(?=\?|$)", "", source.options.get("url_publique", source.url))
    retraits: dict[str, Retrait] = {}
    signales: list[Signalement] = []
    for sec, date_annonce, _ in _annonces(secs, source):
        corps = lignes[sec.debut + 1:sec.fin]
        m = _RE_TITRE_DATE.match(sec.titre)
        annonce = m.group(1).strip() if m else sec.titre
        url = f"{base}#{ancre(sec.titre, source)}"
        prose = _prose(corps)
        trouve = False
        for entetes, rangees in _tableaux(corps):
            col = _colonnes(entetes)
            if col is None:
                continue
            for r in rangees:
                r = r + [""] * (len(entetes) - len(r))
                cellule_date = r[col["date"]]
                modele = nettoyer(r[col["modele"]]) if col["modele"] is not None else annonce
                if not modele or not normaliser_modele(modele):
                    continue
                trouve = True
                iso, ferme = lire_date_retrait(cellule_date)
                if iso is None:
                    signales.append(Signalement("date_illisible", f"« {modele} » (annonce {date_annonce or 'sans date'}) : "
                                                f"date {nettoyer(cellule_date)!r} illisible", None, date_annonce))
                    continue
                if not ferme:
                    signales.append(Signalement("date_non_ferme", f"« {modele} » (annonce {date_annonce or 'sans date'}) : "
                                                f"{nettoyer(cellule_date)!r} n'est qu'une borne", iso, date_annonce))
                    continue
                rempl = nettoyer(r[col["remplacement"]]) if col["remplacement"] is not None else ""
                detail = nettoyer(r[col["update"]]) if col["update"] is not None else ""
                cle = f"{normaliser_modele(modele)}-{iso}"
                if cle in retraits:  # même modèle, même date : un seul retrait, informations fusionnées
                    exist = retraits[cle]
                    exist.remplacement = exist.remplacement or (rempl if rempl.lower() not in _ABSENT else None)
                    if detail and detail not in (exist.detail or ""):
                        exist.detail = f"{exist.detail} ; {detail}" if exist.detail else detail
                    continue
                retraits[cle] = Retrait(modele=modele, cle=normaliser_modele(modele), date_retrait=iso, ferme=True,
                                        date_annonce=date_annonce, annonce=annonce,
                                        remplacement=None if rempl.lower() in _ABSENT else rempl,
                                        detail=detail or None, url=url, prose=prose, brut=nettoyer(cellule_date))
        if not trouve:
            signales.append(Signalement("annonce_sans_retrait", f"annonce « {annonce} » ({date_annonce or 'sans date'}) : "
                                        "aucun retrait lisible", None, date_annonce))
    return list(retraits.values()), signales


def palier(jours: int) -> str | None:
    """`j1` (un jour avant le retrait), `j14` (2 à 14 jours), sinon rien : trop tôt, jour du retrait ou retrait passé."""
    if jours <= 0:
        return None
    for limite, nom in PALIERS:
        if jours <= limite:
            return nom
    return None


def _libelle_jours(n: int) -> str:
    return "dans 1 jour" if n == 1 else f"dans {n} jours"


def element_echeance(source, r: Retrait, jour: date, suffixe: str) -> Element:
    n = (date.fromisoformat(r.date_retrait) - jour).days
    lignes = [f"{r.modele} sera retiré le {r.date_retrait} ({_libelle_jours(n)} au passage du {jour.isoformat()})."]
    if r.detail:
        lignes.append(f"Étape annoncée : {r.detail}")
    lignes.append("Remplacement recommandé : " + (r.remplacement or "non indiqué par la page."))
    lignes.append(f"Annonce d'origine (« {r.annonce} », {r.date_annonce or 'date non indiquée'}) : "
                  + (r.prose or "tableau seul, sans texte d'accompagnement."))
    return Element(id=f"{PREFIXE}{source.id}-{r.cle}-{r.date_retrait}-{suffixe}", produit=source.produit,
                   titre=f"Retrait de {r.modele} le {r.date_retrait} ({_libelle_jours(n)})", version=None,
                   date_publication=None, url=r.url, contenu="\n".join(lignes),
                   source_id=f"{source.id}-echeances", officielle=source.officielle)


def signalements_retenus(signales: list[Signalement], jour: date, recent_jours: int = 180) -> list[str]:
    """Textes des signalements à porter : une borne déjà échue est sans objet, une annonce ancienne sans tableau de dates
    est de l'historique, pas une échéance en attente."""
    messages: list[str] = []
    for s in signales:
        if s.genre == "date_non_ferme" and s.date_retrait and s.date_retrait <= jour.isoformat():
            continue
        if s.genre == "annonce_sans_retrait" and s.date_annonce and (jour - date.fromisoformat(s.date_annonce)).days > recent_jours:
            continue
        messages.append(s.texte)
    return messages


def produire_echeances(source, retraits: list[Retrait], signales: list[Signalement], jour: date,
                       recent_jours: int = 180) -> tuple[list[Element], str | None]:
    """Éléments d'échéance du jour et message de signalement partiel (None s'il n'y a rien à signaler).
    Signalés : toute date de retrait illisible ; une borne dont la date est à venir ; une annonce sans retrait lisible
    seulement si elle est récente (ou sans date) ; aucun retrait du tout (gabarit changé)."""
    elements: list[Element] = []
    for r in retraits:
        p = palier((date.fromisoformat(r.date_retrait) - jour).days)
        if p:
            elements.append(element_echeance(source, r, jour, p))
    messages = signalements_retenus(signales, jour, recent_jours)
    if not retraits and not messages:
        messages.append("aucun retrait extrait de la page : gabarit changé ?")
    if not messages:
        return elements, None
    vus = "; ".join(messages[:MAX_SIGNALES]) + (f" ; … et {len(messages) - MAX_SIGNALES} autre(s)" if len(messages) > MAX_SIGNALES else "")
    return elements, f"échéances : {len(messages)} signalement(s) — {vus}"


HORIZON_JOURS = 14
FICHIER_RESUME = "echeances.json"


def resume_echeances(perimetre: str, sources: list, retraits_sources: dict, echecs: list, jour: date, releve_le: str) -> dict | None:
    """Résumé léger des échéances à 14 jours d'un périmètre, pour la supervision (D71) : `None` si aucune de ses sources ne
    déclare `echeances`. Contrairement aux éléments bruts, il liste tous les retraits de l'horizon (0 à 14 jours), déjà
    signalés ou non. `id` est l'identifiant de l'élément brut quand il en existe un (`-j14`, `-j1`), sinon (jour même) l'identifiant
    sans suffixe. Une source déclarée dont la page n'a pas été lue (échec) rend le périmètre `echec`, avec la raison : une
    liste vide n'y veut jamais dire « aucune échéance »."""
    declarees = [s for s in sources if s.options.get("echeances")]
    if not declarees:
        return None
    lignes: list[dict] = []
    signalements: list[dict] = []
    raisons: list[str] = []
    for s in declarees:
        if s.id not in retraits_sources:
            erreurs = [e.erreur for e in echecs if e.id == s.id and not e.partiel]
            raisons.append(f"{s.id} : " + (" ; ".join(erreurs) or "page des retraits non lue"))
            continue
        _, retraits, signales = retraits_sources[s.id]
        for r in retraits:
            n = (date.fromisoformat(r.date_retrait) - jour).days
            if not 0 <= n <= HORIZON_JOURS:
                continue
            p = palier(n)
            base = f"{PREFIXE}{s.id}-{r.cle}-{r.date_retrait}"
            lignes.append({"id": f"{base}-{p}" if p else base, "modele_ou_fonction": r.modele, "date_retrait": r.date_retrait,
                           "jours_restants": n, "palier": p, "remplacement": r.remplacement, "source_url": r.url})
        signalements += [{"source_id": s.id, "texte": t} for t in signalements_retenus(signales, jour)]
    lignes.sort(key=lambda l: (l["date_retrait"], l["id"]))
    return {"perimetre": perimetre, "releve_le": releve_le, "jour": jour.isoformat(), "statut": "echec" if raisons else "ok",
            "raison": " | ".join(raisons) or None, "echeances": lignes, "signalements": signalements}


def ecrire_resume(chemin, resume: dict) -> dict:
    """Fusionne le résumé d'un périmètre dans `raw/echeances.json` (un seul fichier pour claude et openai, chacun écrit par son
    passage ; `jours_restants` se compte au `jour` de son périmètre, lu dans `sources`). Un fichier existant illisible est
    repris à zéro. Retourne le contenu écrit."""
    import json
    from .etat import ecrire_json
    try:
        with open(chemin, encoding="utf-8") as f:
            actuel = json.load(f)
        if not all(isinstance(actuel.get(k), t) for k, t in (("sources", dict), ("perimetre", dict), ("signalements", list))):
            raise ValueError("structure inattendue")
    except (OSError, ValueError):
        actuel = {"sources": {}, "perimetre": {}, "signalements": []}
    p = resume["perimetre"]
    sources = {**actuel["sources"], p: {"statut": resume["statut"], "releve_le": resume["releve_le"], "jour": resume["jour"],
                                        "raison": resume["raison"]}}
    contenu = {
        "releve_le": max(v["releve_le"] for v in sources.values()),
        "horizon_jours": HORIZON_JOURS,
        "statut": "echec" if any(v["statut"] != "ok" for v in sources.values()) else "ok",
        "raison": " | ".join(f"{k} : {v['raison']}" for k, v in sorted(sources.items()) if v.get("raison")) or None,
        "perimetre": dict(sorted({**actuel["perimetre"], p: resume["echeances"]}.items())),
        "signalements": [x for x in actuel["signalements"] if x.get("perimetre") != p]
                        + [{"perimetre": p, **x} for x in resume["signalements"]],
        "sources": dict(sorted(sources.items())),
    }
    ecrire_json(chemin, contenu)
    return contenu
