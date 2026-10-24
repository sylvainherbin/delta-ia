"""Boucle d'adoption (m-a04181983623) : où en est une fiche envoyée à Delta, projeté depuis OPÉRER, sans second workflow.

Delta-IA ne décide ni ne mesure rien ici : il relit trois vues d'OPÉRER, en lecture seule, et les range par fiche.
  1. `operer --json idees` : les idées jugées par JUGER ; une idée venue du bouton « Envoyer à Delta » porte
     « référence Delta-IA « <nom> » (<produit>, <catégorie>, id <fiche>) » (texte_idee du relais). Position du jugement,
     suite donnée (`sans_suite`) et missions liées.
  2. `operer --json mission <id>` pour chaque mission liée : état, issue, preuves vérifiées par OPÉRER
     (`preuves.verifie_ts`) ; `preuves.fichiers` liste ce qui a été installé, `preuves.sans_installation` (vrai, fichiers
     vides) dit une livraison fusionnée sans rien installer (preuves.py de discipline).
  3. `operer --json essai liste`, puis `essai voir <ess_…>` : les essais de Delta Lab, qui portent l'id de fiche
     (`protocole.fiche`) ; leur statut est le résultat observé (mesures d'OBSERVATORY), distinct de l'installation.
Plus le journal du relais (envois réussis) : une fiche partie mais pas encore jugée est « proposée ».

États (rang croissant ; une fiche prend le plus haut de ses idées et missions) :
  propose        envoyée, ou jugée sans conclusion (A_PRECISER, VERITE sans sens) ;
  ecarte         jugée non pertinente, ou idée close sans suite, et aucune mission ;
  retenu         jugée pertinente ou une mission liée (brief, conception livrée sans installation) ;
  en_realisation une mission liée ouverte (de EN_COURS à POUSSEE, attentes, échec en reprise) ;
  adopte         une mission liée close « livre », preuves vérifiées, sans fichier installé (`sans_installation` ou
                 `fichiers` vides : fusion seule, document, conception) ;
  installe       une mission liée close « livre » avec des fichiers installés et vérifiés, ou un essai Delta Lab adopté
                 (réglage de la politique en vigueur).
Hors rang : `inconnu`, quand la vue d'une mission liée manque (délai, code de sortie) et que le résumé de l'idée ne suffit
pas (mission close : seules ses preuves disent installée, adoptée ou non) ; la fiche n'est jamais rétrogradée en silence.
Delta Lab ne rejoint qu'une fiche déjà dans la boucle (envoyée ou jugée) ; son id peut porter le préfixe « kb- »
(sortie réelle de `essai liste`, 24/10/2026), retiré quand la forme nue est celle de la fiche.

Ces données décrivent l'organisation de Sylvain : couche personnelle, jamais publiées (SPEC §1, couches). Seul le relais
local les sert, à la page ouverte sur ce poste.
"""
from __future__ import annotations

import json
import re
import subprocess

ETATS = ("propose", "ecarte", "retenu", "en_realisation", "adopte", "installe")
INCONNU = "inconnu"
IDEE = re.compile(r"référence Delta-IA « .* » \([^()]*, id ([a-z0-9][a-z0-9._-]*)\)")
POSITIVES = ("PERTINENTE", "VERITE (PENCHE_POUR)")
ESSAI = re.compile(r"^(ess_[0-9a-f]{12}) · ")
TRI = re.compile(r"^(\S+) · (\S+)(?: \[[^\]]*\])? : (.+)$")
OUVERTES_SANS_TRAVAIL = ("BRIEF",)
DELAI = 120   # `operer --json idees` et `essai liste` prennent environ 13 s chacun (mesure du 24/10/2026)
RESULTAT_MAX = 240


class LectureImpossible(ValueError):
    """Raison contrôlée : jamais de sortie brute d'OPÉRER."""


def lire_operer(*args, delai=DELAI):
    """Une vue `operer --json …` en dict, ou LectureImpossible."""
    try:
        r = subprocess.run(["operer", "--json", *args], capture_output=True, text=True, encoding="utf-8",
                           timeout=delai, shell=False)
    except FileNotFoundError:
        raise LectureImpossible("exécutable operer absent") from None
    except subprocess.TimeoutExpired:
        raise LectureImpossible(f"{' '.join(args)} : délai de {delai} s dépassé") from None
    except (OSError, UnicodeError):
        raise LectureImpossible(f"{' '.join(args)} : exécution impossible") from None
    if r.returncode:
        raise LectureImpossible(f"{' '.join(args)} : code de sortie {r.returncode}")
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise LectureImpossible(f"{' '.join(args)} : JSON illisible") from None
    if not isinstance(d, dict):
        raise LectureImpossible(f"{' '.join(args)} : objet JSON attendu")
    return d


def fiche_de_idee(verbatim):
    """L'id de fiche d'une idée envoyée par le bouton, ou None (autre idée)."""
    m = IDEE.search(verbatim) if isinstance(verbatim, str) else None
    return m.group(1) if m else None


def _jour(ts):
    return ts[:10] if isinstance(ts, str) and re.match(r"\d{4}-\d{2}-\d{2}", ts) else None


def _ligne(v, n=RESULTAT_MAX):
    s = " ".join(str(v or "").split())
    return (s if len(s) <= n else s[: n - 1].rstrip() + "…") or None


def etat_mission(m):
    """(état projeté, jour de la livraison vérifiée ou None) d'une mission OPÉRER."""
    etat = m.get("etat")
    if etat == "CLOSE":
        preuves = m.get("preuves") if isinstance(m.get("preuves"), dict) else {}
        if m.get("issue") == "livre" and preuves.get("verifie_ts"):
            installe = preuves.get("sans_installation") is not True and bool(preuves.get("fichiers"))
            return ("installe" if installe else "adopte"), _jour(preuves["verifie_ts"])
        return "retenu", None   # close sans installation constatée (conception livrée, abandon) : la décision reste
    if etat in OUVERTES_SANS_TRAVAIL or not isinstance(etat, str):
        return "retenu", None
    return "en_realisation", None


def etat_sujet(s):
    """État d'une idée jugée d'après sa seule position (sans ses missions)."""
    position = s.get("position") if isinstance(s.get("position"), str) else ""
    if position in POSITIVES:
        return "retenu"
    if position == "PAS_PERTINENTE" or "CONTRE" in position or s.get("sans_suite") is True:
        return "ecarte"
    return "propose"


def _id_connu(ident, fiches):
    """L'id de fiche de Delta Lab rattaché à une fiche de la boucle (forme nue ou préfixée « kb- »), ou None."""
    if not isinstance(ident, str) or not ident:
        return None
    if ident in fiches:
        return ident
    return ident[3:] if ident.startswith("kb-") and ident[3:] in fiches else None


def _plus_haut(a, b):
    return a if ETATS.index(a) >= ETATS.index(b) else b


def projeter(sujets, missions, essais=(), tries=(), envois=()):
    """Projection par fiche. `missions` : id → vue mission d'OPÉRER ; `essais` : essais Delta Lab (dict d'`essai voir`) ;
    `tries` : (jour, fiche, raison) des fiches écartées au tri ; `envois` : lignes réussies du journal du relais."""
    fiches = {}

    def fiche(ident):
        return fiches.setdefault(ident, {"id": ident, "etat": "propose", "propose_le": None, "position": None,
                                         "missions": [], "installations": [], "resultat_observe": [],
                                         "missions_illisibles": []})

    for e in envois:
        if isinstance(e, dict) and e.get("ok") is True and isinstance(e.get("id"), str):
            f = fiche(e["id"])
            j = _jour(e.get("date"))
            if j and (f["propose_le"] is None or j < f["propose_le"]):
                f["propose_le"] = j
    for s in sujets:
        ident = fiche_de_idee(s.get("verbatim")) if isinstance(s, dict) else None
        if not ident:
            continue
        f = fiche(ident)
        j = _jour(s.get("premier"))
        if j and (f["propose_le"] is None or j < f["propose_le"]):
            f["propose_le"] = j
        if isinstance(s.get("position"), str):
            f["position"] = s["position"]
        etat = etat_sujet(s)
        liees = [x for x in s.get("missions") or [] if isinstance(x, dict) and isinstance(x.get("id"), str)]
        if liees:
            etat = _plus_haut(etat, "retenu")
        for x in liees:
            m = missions.get(x["id"])
            if m is None:   # vue mission en échec : le résumé de l'idée ne vaut que pour une mission ouverte
                m = {"etat": x.get("etat")}
                lisible = isinstance(m["etat"], str) and m["etat"] != "CLOSE"
                em, installee_le = etat_mission(m) if lisible else (INCONNU, None)
            else:
                em, installee_le = etat_mission(m)
            if em == INCONNU:
                if x["id"] not in f["missions_illisibles"]:
                    f["missions_illisibles"].append(x["id"])
            else:
                etat = _plus_haut(etat, em)
            if any(y["id"] == x["id"] for y in f["missions"]):
                continue
            f["missions"].append({"id": x["id"], "etat": m.get("etat"), "projete": em})
            if em in ("installe", "adopte"):
                f["installations"].append({"lot": x["id"], "le": installee_le,
                                           "par": "mission" if em == "installe" else "mission_sans_installation",
                                           "resultat": _ligne(m.get("resultat") or x.get("resultat"))})
        f["etat"] = _plus_haut(f["etat"], etat)
    for x in essais:
        p = x.get("protocole") if isinstance(x, dict) and isinstance(x.get("protocole"), dict) else {}
        ident = _id_connu(p.get("fiche"), fiches)
        if not ident:   # essai sur une fiche jamais envoyée ni jugée : hors de la boucle, comme au tri
            continue
        f = fiches[ident]
        clos = x.get("clos") if isinstance(x.get("clos"), dict) else {}
        f["resultat_observe"].append({"essai": x.get("id"), "statut": x.get("statut"), "maturite": x.get("maturite"),
                                      "titre": _ligne(p.get("titre"), 120), "le": _jour(clos.get("ts") or x.get("fige_le")),
                                      "explication": _ligne(clos.get("explication"))})
        if x.get("statut") == "adopte":
            adoption = x.get("adoption") if isinstance(x.get("adoption"), dict) else {}
            f["installations"].append({"lot": x.get("id"), "le": _jour(adoption.get("ts")), "par": "essai",
                                       "resultat": _ligne(p.get("titre"), 120)})
            f["etat"] = "installe"
    for jour, ident, raison in tries:
        ident = _id_connu(ident, fiches)
        if ident:   # une fiche écartée au tri sans avoir été envoyée n'entre pas dans la boucle
            fiches[ident]["resultat_observe"].append({"essai": None, "statut": "ecarte_au_tri", "maturite": None,
                                                      "titre": None, "le": jour, "explication": _ligne(raison)})
    for f in fiches.values():
        f["installations"].sort(key=lambda i: i["le"] or "")
        if f["missions_illisibles"] and f["etat"] != "installe":   # installée reste certaine : rien n'est plus haut
            f["etat"] = INCONNU
    return fiches


def lire_essais(liste):
    """(ids d'essais, tris) depuis la sortie de `essai liste` (lignes de texte, seule forme publiée par OPÉRER)."""
    lignes = liste.get("essais") if isinstance(liste.get("essais"), list) else []
    ids, tries, apres_tri = [], [], False
    for ligne in lignes:
        if not isinstance(ligne, str):
            continue
        if ligne.startswith("Examinés, écartés au tri"):
            apres_tri = True
            continue
        if apres_tri:
            m = TRI.match(ligne)
            if m:
                tries.append((_jour(m.group(1)), m.group(2), m.group(3)))
        else:
            m = ESSAI.match(ligne)
            if m:
                ids.append(m.group(1))
    return ids, tries


def suivi(envois=(), lire=lire_operer):
    """Projection complète, avec les vues en échec nommées (jamais un résultat vide silencieux)."""
    echecs = []
    try:
        sujets = lire("idees").get("sujets") or []
    except LectureImpossible as exc:
        sujets = []
        echecs.append(f"idées : {exc}")
    missions = {}
    for s in sujets:
        if not (isinstance(s, dict) and fiche_de_idee(s.get("verbatim"))):
            continue
        for x in s.get("missions") or []:
            ident = x.get("id") if isinstance(x, dict) else None
            if isinstance(ident, str) and ident not in missions:
                try:
                    m = lire("mission", ident).get("mission")
                    if isinstance(m, dict):
                        missions[ident] = m
                except LectureImpossible as exc:
                    echecs.append(f"mission {ident} : {exc}")
    essais, tries = [], []
    try:
        ids, tries = lire_essais(lire("essai", "liste"))
        for ident in ids:
            try:
                x = lire("essai", "voir", ident).get("essai")
                if isinstance(x, dict):
                    essais.append(x)
            except LectureImpossible as exc:
                echecs.append(f"essai {ident} : {exc}")
    except LectureImpossible as exc:
        echecs.append(f"essais : {exc}")
    return {"fiches": projeter(sujets, missions, essais, tries, envois), "sources_en_echec": echecs}
