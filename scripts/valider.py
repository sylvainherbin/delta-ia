#!/usr/bin/env python3
"""Delta — validation des JSON produits par un agent avant commit (SPEC §7, D15).

Usage :
  valider.py --perimetre {claude,openai,actu} [--date AAAA-MM-JJ] [--brut raw/<p>-nouveautes.json]
             [--contexte CONTEXTE.md] [--racine <dossier>]
  valider.py --perimetre {claude,openai} --kb         base de référence (SPEC §7.4)

Vérifie tous les fichiers quotidiens du dossier `docs/data/<p>/` (schéma, énumérations, dates, unicité des
identifiants, cohérences, secrets), la couverture des nouveautés brutes par le fichier du jour (`--brut`),
et la cohérence de `index.json`. Code de sortie 0 si tout est valide, 1 sinon ; les erreurs sont listées.
Lignes `! AVERTISSEMENT` (D85, D97) : ajout à un outil sans commande exacte (R1), élément D71 sans date absolue (R5), ajout des `puces` du brut (D95) dont un nom figure
dans CONTEXTE.md ou la base et que ni `resume` ni `pour_toi` ne cite (R2), `pour_toi` conditionnel sans commande qui le tranche dans `action`
et `pour_toi` recopié du même id dans un fichier des 7 jours précédents (R4) ; sans effet sur le code de sortie.
Ancrage (D101) : `pour_toi` d'un élément d'impact faible ou plus qui ne nomme aucun projet, outil ni habitude de CONTEXTE.md (fichiers postérieurs au 24/09) ; sans effet sur le code de sortie.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.etat import DOSSIERS  # noqa: E402
from deltalib.contexte import (SHA1_VIDE, ContexteInvalide, analyser as analyser_contexte, erreurs_pourquoi,  # noqa: E402
                               termes_ancrage, termes_nommes)
from deltalib.modeles import PERIMETRES, PRODUITS, id_web  # noqa: E402
from deltalib.sujet_d71 import mots_trouves_element  # noqa: E402
from deltalib import semaine as bilan_semaine  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent

AGENTS = {"claude": "claude-code", "actu": "claude-code", "openai": "codex"}
PRODUITS_PAR_PERIMETRE = {"claude": {"claude", "claude-code"}, "openai": {"chatgpt", "codex"}, "actu": {"actu"}}
TYPES = {"nouveaute", "amelioration", "correction", "changement_rupture", "depreciation", "actu"}
CERTITUDES = {"officiel", "rapporte", "non_confirme"}
IMPACTS = {"fort", "moyen", "faible", "nul"}
EFFORTS = {"5min", "30min", "plus"}
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_D58 = "2026-09-23"
DATE_ID_WEB = "2026-09-25"  # fichiers datés après ce jour : identifiant `web-` recalculé (D20, audit du 25/09)
DATE_D64 = "2026-09-24"  # éléments quotidiens datés après ce jour : `contexte_sections` obligatoire, format D64-bis
RE_SECRETS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "jeton GitHub (ghp_)"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "jeton GitHub (github_pat_)"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "clé API (sk-)"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "clé AWS (AKIA)"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|-----BEGIN"), "clé privée (-----BEGIN)"),
    (re.compile(r"https?://[^\s\"'<>]*[?&/;#](?:[A-Za-z_-]*(?:token|key|secret)[A-Za-z_-]*)=[^\s\"'<>&]+", re.I), "URL contenant token, key ou secret"),
]
# D85 : avertissements seulement (jamais d'arrêt d'un passage de nuit). R1 : un ajout à un outil porte une commande exacte
# entre accents graves dans `action` ; R5 : un élément D71 porte une date absolue dans `action`. Aucun champ ne marque D71
# dans un élément : il se repère aux mots-clés de `deltalib.sujet_d71` dans `titre` et `resume` (pas `pour_toi`, qui cite
# « Paramètres > Utilisation » à tout propos).
TYPES_AJOUT = {"nouveaute", "amelioration"}
RE_SEGMENT_CODE = re.compile(r"`[^`\n]+`")
RE_DATE_ACTION = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}/\d{2}\b")
# R4 : un `pour_toi` qui pose une condition doit voir sa commande dans `action` ; le même id ne répète pas le texte de la veille.
MARQUEURS_CONDITIONNEL = ("si tu", "si vous", "au cas où", "éventuellement")
RE_CONDITIONNEL = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(m).replace(r"\ ", r"\s+") for m in MARQUEURS_CONDITIONNEL) + r")(?!\w)", re.I)
RECOPIE_JOURS = 7
# D101 (ancrage) : un `pour_toi` d'un élément d'impact faible ou plus nomme un projet, un outil ou une habitude de CONTEXTE.md
# (termes de `deltalib.contexte.termes_ancrage`, sections citées par l'élément) ; `contexte_sections` vide ou absent : avertissement d'office.
MESSAGE_ANCRAGE = "ancrage : `pour_toi` sans projet, outil ni habitude nommés de CONTEXTE.md"
RE_ORGANISATION_PRIVEE = [re.compile(motif) for motif in (rb"m-[0-9a-f]{12}", rb"cc-socks")]


class Rapport:
    def __init__(self) -> None:
        self.erreurs: list[str] = []
        self.avertissements: list[str] = []

    def erreur(self, ou: str, message: str) -> None:
        self.erreurs.append(f"{ou}: {message}")

    def avertissement(self, ou: str, message: str) -> None:
        self.avertissements.append(f"{ou}: {message}")

    @property
    def ok(self) -> bool:
        return not self.erreurs


def projets_du_contexte(chemin: Path) -> set[str]:
    """Noms de projets (D81) : sections de niveau 3 de CONTEXTE.md dont le ctx-id est `projet.<nom>`.

    Une structure ctx-id invalide donne un ensemble vide : `charger_ctx_ids` la signale déjà.
    """
    if not chemin.exists():
        return set()
    try:
        sections = analyser_contexte(chemin.read_text(encoding="utf-8"))[0]
    except ContexteInvalide:
        return set()
    return {cle[len("projet."):] for cle, s in sections.items()
            if s["niveau"] == 3 and cle.startswith("projet.") and len(cle) > len("projet.")}


def termes_ancrage_du_contexte(chemin: Path) -> dict | None:
    """D101 : termes d'ancrage de CONTEXTE.md ; None s'il est absent ou à structure invalide (déjà signalé ailleurs)."""
    if not chemin.exists():
        return None
    try:
        return termes_ancrage(chemin.read_text(encoding="utf-8"))
    except ContexteInvalide:
        return None


def _date_valide(v) -> bool:
    if not isinstance(v, str) or not RE_DATE.match(v):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def verifier_element(e: dict, i: int, perimetre: str, projets: set[str], r: Rapport, ou: str,
                     ctx_disparu_permis: bool = False) -> None:
    ou = f"{ou} elements[{i}]"
    if not isinstance(e, dict):
        r.erreur(ou, "n'est pas un objet")
        return
    obligatoires = ["id", "ids_bruts", "produit", "titre", "version", "date_publication", "type", "resume", "sources",
                    "certitude", "impact", "pour_toi", "projets_concernes", "action", "kb_refs"]
    manquants = [c for c in obligatoires if c not in e]
    if manquants:
        r.erreur(ou, f"champs manquants : {manquants}")
    inconnus = set(e) - set(obligatoires) - {"revision", "contexte_sections"}
    if inconnus:
        r.erreur(ou, f"champs inconnus : {sorted(inconnus)}")
    if not isinstance(e.get("id"), str) or not e.get("id"):
        r.erreur(ou, "`id` doit être une chaîne non vide")
    bruts = e.get("ids_bruts")
    if not isinstance(bruts, list) or not bruts or not all(isinstance(b, str) and b for b in bruts):
        r.erreur(ou, "`ids_bruts` doit être un tableau non vide de chaînes")
    elif e.get("id") != bruts[0]:
        r.erreur(ou, f"`id` ({e.get('id')!r}) doit être le premier de `ids_bruts` ({bruts[0]!r})")
    if isinstance(e.get("id"), str) and e["id"].startswith("web-") and not re.fullmatch(r"web-[0-9a-f]{12}", e["id"]):
        r.erreur(ou, "un identifiant `web-` doit être suivi des 12 premiers hexadécimaux du sha1 de l'URL")
    if e.get("produit") not in PRODUITS:
        r.erreur(ou, f"`produit` inconnu : {e.get('produit')!r}")
    elif e["produit"] not in PRODUITS_PAR_PERIMETRE[perimetre]:
        r.erreur(ou, f"`produit` {e['produit']!r} hors du périmètre {perimetre!r}")
    if not isinstance(e.get("titre"), str) or not e.get("titre", "").strip():
        r.erreur(ou, "`titre` vide")
    if e.get("version") is not None and not isinstance(e.get("version"), str):
        r.erreur(ou, "`version` doit être une chaîne ou null")
    if e.get("date_publication") is not None and not _date_valide(e.get("date_publication")):
        r.erreur(ou, f"`date_publication` doit être AAAA-MM-JJ ou null : {e.get('date_publication')!r}")
    if e.get("type") not in TYPES:
        r.erreur(ou, f"`type` inconnu : {e.get('type')!r}")
    if not isinstance(e.get("resume"), str) or not e.get("resume", "").strip():
        r.erreur(ou, "`resume` vide")
    sources = e.get("sources")
    if not isinstance(sources, list) or not sources:
        r.erreur(ou, "`sources` doit contenir au moins une source")
        sources = []
    for j, s in enumerate(sources):
        if not isinstance(s, dict) or set(s) != {"url", "libelle", "officielle"}:
            r.erreur(ou, f"sources[{j}] doit avoir exactement les champs url, libelle, officielle")
            continue
        if not isinstance(s["url"], str) or not s["url"].startswith(("http://", "https://")):
            r.erreur(ou, f"sources[{j}].url invalide : {s['url']!r}")
        if not isinstance(s["libelle"], str) or not s["libelle"].strip():
            r.erreur(ou, f"sources[{j}].libelle vide")
        if not isinstance(s["officielle"], bool):
            r.erreur(ou, f"sources[{j}].officielle doit être un booléen")
    if e.get("certitude") not in CERTITUDES:
        r.erreur(ou, f"`certitude` inconnue : {e.get('certitude')!r}")
    elif e["certitude"] == "officiel" and not any(isinstance(s, dict) and s.get("officielle") is True for s in sources):
        r.erreur(ou, "`certitude: officiel` exige au moins une source `officielle: true`")
    impact = e.get("impact")
    if impact not in IMPACTS:
        r.erreur(ou, f"`impact` inconnu : {impact!r}")
    pour_toi = e.get("pour_toi")
    if impact == "nul" and pour_toi is not None:
        r.erreur(ou, "`pour_toi` doit être null quand `impact` vaut `nul`")
    if impact in IMPACTS - {"nul"} and (not isinstance(pour_toi, str) or not pour_toi.strip()):
        r.erreur(ou, "`pour_toi` doit être renseigné quand `impact` n'est pas `nul`")
    pc = e.get("projets_concernes")
    if not isinstance(pc, list) or not all(isinstance(x, str) for x in pc):
        r.erreur(ou, "`projets_concernes` doit être un tableau de chaînes")
    else:
        hors = [x for x in pc if x not in projets]
        # Ancien fichier du jour (même drapeau que les sections) : un projet retiré ou renommé depuis de CONTEXTE.md §2
        # ne le rend pas invalide ; le fichier du jour garde le refus strict (29/09/2026).
        if hors and not ctx_disparu_permis:
            r.erreur(ou, f"`projets_concernes` hors de CONTEXTE.md §2 : {hors} (connus : {sorted(projets)})")
    action = e.get("action")
    if action is not None:
        if not isinstance(action, dict) or set(action) != {"description", "etapes", "effort"}:
            r.erreur(ou, "`action` doit être null ou {description, etapes, effort}")
        else:
            if not isinstance(action["description"], str) or not action["description"].strip():
                r.erreur(ou, "`action.description` vide")
            if not isinstance(action["etapes"], list) or not action["etapes"] or not all(isinstance(x, str) and x.strip() for x in action["etapes"]):
                r.erreur(ou, "`action.etapes` doit être un tableau non vide de chaînes")
            if action["effort"] not in EFFORTS:
                r.erreur(ou, f"`action.effort` hors de {sorted(EFFORTS)} : {action['effort']!r}")
    if not isinstance(e.get("kb_refs"), list) or not all(isinstance(x, str) for x in e.get("kb_refs", [])):
        r.erreur(ou, "`kb_refs` doit être un tableau de chaînes")
    if "contexte_sections" in e:
        if e["contexte_sections"] is None:
            r.erreur(ou, "`contexte_sections` doit être {ctx-id: {sha1, pourquoi}}, éventuellement vide (D64-bis)")
        else:
            verifier_sections(e["contexte_sections"], ou, r, ctx_disparu_permis)
    if "revision" in e and not isinstance(e["revision"], bool):
        r.erreur(ou, "`revision` doit être un booléen")


def _texte_action(action) -> str:
    if not isinstance(action, dict):
        return ""
    etapes = action.get("etapes") if isinstance(action.get("etapes"), list) else []
    return "\n".join(str(x) for x in [action.get("description"), *etapes] if isinstance(x, str))


def avertir_element(e: dict, i: int, r: Rapport, ou: str, ancrage: dict | None = None) -> None:
    """D85 (R1, R5), D101 (ancrage) : avertissements sur un élément, sans effet sur le code de sortie.

    `ancrage` : `deltalib.contexte.termes_ancrage` du CONTEXTE.md ; None, aucun contrôle d'ancrage."""
    if not isinstance(e, dict) or e.get("impact") not in IMPACTS - {"nul"}:
        return
    ou = f"{ou} elements[{i}] ({e.get('id')})"
    texte = _texte_action(e.get("action"))
    if e.get("type") in TYPES_AJOUT and e.get("produit") in PRODUITS and e["produit"] != "actu" \
            and not RE_SEGMENT_CODE.search(texte):
        r.avertissement(ou, "R1 : ajout à un outil sans commande exacte entre accents graves dans `action`")
    if mots_trouves_element(e.get("titre"), e.get("resume")) and not RE_DATE_ACTION.search(texte):
        r.avertissement(ou, "R5 : élément compte et quotas (D71) sans date absolue (AAAA-MM-JJ ou JJ/MM) dans `action`")
    if conditionnel_sans_commande(e):
        r.avertissement(ou, "R4 : `pour_toi` conditionnel sans commande entre accents graves dans `action` qui le tranche")
    if ancrage is not None and isinstance(e.get("pour_toi"), str) and e["pour_toi"].strip():
        citees = citees_du_pour_toi(e)
        if not citees or not termes_nommes(e["pour_toi"], ancrage, citees):
            r.avertissement(ou, MESSAGE_ANCRAGE)


def citees_du_pour_toi(e: dict) -> list[str]:
    """ctx-id cités par l'élément (`contexte_sections`), vide si le champ est absent, null ou mal formé."""
    cs = e.get("contexte_sections")
    return [k for k in cs if isinstance(k, str)] if isinstance(cs, dict) else []


def conditionnel_sans_commande(e: dict) -> bool:
    """R4 : `pour_toi` contenant un marqueur de condition (MARQUEURS_CONDITIONNEL) alors que l'`action` n'a aucun segment de code."""
    pour_toi = e.get("pour_toi")
    return isinstance(pour_toi, str) and bool(RE_CONDITIONNEL.search(pour_toi)) \
        and not RE_SEGMENT_CODE.search(_texte_action(e.get("action")))


def normaliser_texte(texte: str) -> str:
    """Casse, espaces et ponctuation écartés : deux `pour_toi` qui ne diffèrent que par là sont le même texte."""
    return " ".join(re.sub(r"[\W_]+", " ", texte.casefold()).split())


def recopies_pour_toi(quotidiens: dict[str, dict], jour: str) -> list[tuple[int, dict, str]]:
    """R4 : éléments du fichier `jour` dont le `pour_toi` est identique (normalisé) à celui du même id dans un fichier
    des RECOPIE_JOURS jours précédents ; (indice, élément, date du plus récent de ces fichiers)."""
    try:
        d = date.fromisoformat(jour)
    except ValueError:
        return []
    vus: dict[str, dict[str, str]] = {}  # id -> {date: pour_toi normalisé} sur les 7 jours précédents
    for autre in sorted(quotidiens):
        try:
            ecart = (d - date.fromisoformat(autre)).days
        except ValueError:
            continue
        if not 1 <= ecart <= RECOPIE_JOURS:
            continue
        for e in quotidiens[autre].get("elements", []):
            if isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("pour_toi"), str):
                vus.setdefault(e["id"], {})[autre] = normaliser_texte(e["pour_toi"])
    trouves = []
    for i, e in enumerate(quotidiens[jour].get("elements", [])):
        if not (isinstance(e, dict) and isinstance(e.get("pour_toi"), str)):
            continue
        norme = normaliser_texte(e["pour_toi"])
        memes = [a for a, n in vus.get(e.get("id"), {}).items() if n == norme] if norme else []
        if memes:
            trouves.append((i, e, max(memes)))
    return trouves


def avertir_recopies(quotidiens: dict[str, dict], r: Rapport) -> None:
    for jour in sorted(quotidiens):
        for i, e, ancien in recopies_pour_toi(quotidiens, jour):
            if e.get("impact") in IMPACTS - {"nul"}:
                r.avertissement(f"{jour}.json elements[{i}] ({e.get('id')})",
                                f"R4 : `pour_toi` recopié du {ancien[8:10]}/{ancien[5:7]}")


def verifier_ids_web(e: dict, ou: str, r: Rapport) -> None:
    """D20 : chaque identifiant `web-` de `ids_bruts` doit valoir id_web(url, date_publication, titre) pour l'URL de
    l'une des sources de l'élément, avec sa `date_publication` et son `titre` publiés. Sans URL, rien n'est vérifié."""
    urls = [s.get("url") for s in e.get("sources") or [] if isinstance(s, dict) and isinstance(s.get("url"), str) and s["url"]]
    if not urls or not isinstance(e.get("titre"), str):
        return
    attendus = {id_web(u, e.get("date_publication"), e["titre"]) for u in urls}
    for ident in e.get("ids_bruts") or []:
        if isinstance(ident, str) and ident.startswith("web-") and ident not in attendus:
            r.erreur(ou, f"identifiant `{ident}` ≠ id_web(url, date_publication, titre) de l'élément "
                         f"(attendu : {', '.join(sorted(attendus))}) ; calcule-le avec le titre publié (D20)")


def verifier_ids_kb(e: dict, ou: str, r: Rapport, connus: set[str] | None) -> None:
    """D86 : un identifiant `kb-<id>` désigne une entrée de la base de référence, citée dans `kb_refs` de l'élément."""
    for ident in e.get("ids_bruts") or []:
        if not (isinstance(ident, str) and ident.startswith("kb-")):
            continue
        entree = ident[3:]
        if connus is not None and entree not in connus:
            r.erreur(ou, f"identifiant `{ident}` : entrée inconnue dans la base de référence ({entree})")
        if entree not in (e.get("kb_refs") or []):
            r.erreur(ou, f"identifiant `{ident}` : l'entrée {entree} doit figurer dans `kb_refs` de l'élément")


def verifier_quotidien(chemin: Path, perimetre: str, projets: set[str], r: Rapport,
                       ctx_disparu_permis: bool = False, ancrage: dict | None = None) -> dict | None:
    ou = chemin.name
    texte = chemin.read_text(encoding="utf-8")
    verifier_secrets(texte, ou, r)
    try:
        q = json.loads(texte)
    except ValueError as e:
        r.erreur(ou, f"JSON invalide : {e}")
        return None
    if not isinstance(q, dict):
        r.erreur(ou, "la racine doit être un objet")
        return None
    attendus = {"date", "perimetre", "agent", "genere_le", "synthese", "sources_en_echec", "elements", "ecartes"}
    if not attendus <= set(q) or set(q) - attendus - {"contexte_empreinte"}:
        r.erreur(ou, f"champs attendus {sorted(attendus)} (+ contexte_empreinte), trouvés {sorted(q)}")
    # D58 : obligatoire pour les fichiers postérieurs à son introduction ; ceux du 23/09 sont laissés tels quels
    ce = q.get("contexte_empreinte")
    if ce is None and isinstance(q.get("date"), str) and q["date"] > DATE_D58:
        r.erreur(ou, "`contexte_empreinte` absent : sha1 de CONTEXTE.md au moment de la synthèse (D58)")
    elif ce is not None and not (isinstance(ce, str) and re.fullmatch(r"[0-9a-f]{40}", ce)):
        r.erreur(ou, "`contexte_empreinte` doit être le sha1 de CONTEXTE.md (40 hexadécimaux)")
    if q.get("date") != chemin.stem or not _date_valide(q.get("date")):
        r.erreur(ou, f"`date` ({q.get('date')!r}) doit être AAAA-MM-JJ et égale au nom du fichier")
    if q.get("perimetre") != perimetre:
        r.erreur(ou, f"`perimetre` {q.get('perimetre')!r} au lieu de {perimetre!r}")
    if q.get("agent") != AGENTS[perimetre]:
        r.erreur(ou, f"`agent` {q.get('agent')!r} au lieu de {AGENTS[perimetre]!r}")
    if not isinstance(q.get("genere_le"), str) or "T" not in q.get("genere_le", ""):
        r.erreur(ou, "`genere_le` doit être un horodatage ISO 8601")
    if not isinstance(q.get("synthese"), str) or not q.get("synthese", "").strip():
        r.erreur(ou, "`synthese` vide")
    for k, s in enumerate(q.get("sources_en_echec") or []):
        if not isinstance(s, dict) or not {"id", "url", "erreur"} <= set(s):
            r.erreur(ou, f"sources_en_echec[{k}] doit avoir id, url, erreur (et partiel)")
    ecartes = q.get("ecartes")
    ids_ecartes: list[str] = []
    if not isinstance(ecartes, list):
        r.erreur(ou, "`ecartes` doit être un tableau")
    else:
        for k, x in enumerate(ecartes):
            if not isinstance(x, dict) or set(x) != {"id", "raison"} or not x.get("id") or not str(x.get("raison", "")).strip():
                r.erreur(ou, f"ecartes[{k}] doit être {{id, raison}} non vides")
            else:
                ids_ecartes.append(x["id"])
    elements = q.get("elements")
    if not isinstance(elements, list):
        r.erreur(ou, "`elements` doit être un tableau")
        return q
    ids: list[str] = []
    bruts: list[str] = []
    for i, e in enumerate(elements):
        verifier_element(e, i, perimetre, projets, r, ou, ctx_disparu_permis)
        avertir_element(e, i, r, ou, ancrage if isinstance(q.get("date"), str) and q["date"] > DATE_D64 else None)
        if isinstance(e, dict) and "contexte_sections" not in e and isinstance(q.get("date"), str) and q["date"] > DATE_D64:
            r.erreur(f"{ou} elements[{i}]", "`contexte_sections` absent : sections de CONTEXTE.md citées (D64)")
        if isinstance(e, dict) and isinstance(q.get("date"), str) and q["date"] > DATE_ID_WEB:
            verifier_ids_web(e, f"{ou} elements[{i}]", r)
        if isinstance(e, dict):
            if isinstance(e.get("id"), str):
                ids.append(e["id"])
            if isinstance(e.get("ids_bruts"), list):
                bruts.extend(b for b in e["ids_bruts"] if isinstance(b, str))
    for doublon in sorted({x for x in ids if ids.count(x) > 1}):
        r.erreur(ou, f"identifiant d'élément en double : {doublon}")
    for doublon in sorted({x for x in bruts if bruts.count(x) > 1}):
        r.erreur(ou, f"identifiant brut présent dans deux éléments : {doublon}")
    for doublon in sorted({x for x in ids_ecartes if ids_ecartes.count(x) > 1}):
        r.erreur(ou, f"identifiant écarté en double : {doublon}")
    for x in sorted(set(bruts) & set(ids_ecartes)):
        r.erreur(ou, f"identifiant à la fois écarté et repris dans un élément : {x}")
    return q


def verifier_secrets(texte: str, ou: str, r: Rapport) -> None:
    for motif, libelle in RE_SECRETS:
        m = motif.search(texte)
        if m:
            r.erreur(ou, f"secret possible ({libelle}) : {m.group(0)[:24]}…")


def verifier_organisation_privee(racine: Path, r: Rapport) -> None:
    """D77 : aucune trace opérationnelle OPÉRER dans les fichiers publics, tous périmètres compris."""
    for chemin in sorted((racine / "docs" / "data").rglob("*")):
        if not chemin.is_file():
            continue
        ou = str(chemin.relative_to(racine))
        try:
            contenu = chemin.read_bytes()
        except OSError:
            r.erreur(ou, "fichier illisible pour le contrôle OPÉRER (D77)")
            continue
        for motif in RE_ORGANISATION_PRIVEE:
            if motif.search(contenu):
                r.erreur(ou, f"donnée OPÉRER interdite (D77), motif : {motif.pattern.decode('ascii')}")


def verifier_couverture(q: dict, chemin_brut: Path, r: Rapport) -> None:
    ou = chemin_brut.name
    try:
        brut = json.loads(chemin_brut.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        r.erreur(ou, f"fichier brut illisible : {e}")
        return
    if brut.get("perimetre") != q.get("perimetre"):
        r.erreur(ou, f"le brut concerne {brut.get('perimetre')!r}, le fichier quotidien {q.get('perimetre')!r}")
    couverts = {b for e in q.get("elements", []) if isinstance(e, dict) for b in (e.get("ids_bruts") or [])}
    couverts |= {x["id"] for x in q.get("ecartes", []) if isinstance(x, dict) and x.get("id")}
    for n in brut.get("nouveautes", []):
        if n["id"] not in couverts:
            r.erreur(ou, f"nouveauté brute ni reprise dans `ids_bruts` ni dans `ecartes` : {n['id']} ({n.get('titre', '')[:50]})")
    # D96 : avertissements seulement (jamais d'arrêt d'un passage de nuit) ; une révision garde l'id et porte `revision: true`
    revisions = {e.get("id") for e in q.get("elements", []) if isinstance(e, dict) and e.get("revision") is True}
    ecartes = {x["id"] for x in q.get("ecartes", []) if isinstance(x, dict) and x.get("id")}
    for x in brut.get("reevaluer") or []:
        if isinstance(x, dict) and x.get("id") and x["id"] not in revisions | ecartes:
            r.avertissement(ou, f"D96 : élément à réévaluer ni révisé (`revision: true`, même id) ni écarté « réévalué, inchangé » : {x['id']}")


NOMS_TROP_COURTS = 3  # D95 : un segment de moins de 3 caractères ou une valeur nue (`true`) ne désigne rien
NOMS_VALEURS = {"true", "false", "null", "none"}


def noms_de_la_base(racine: Path, perimetre: str) -> set[str]:
    """D95 : noms des entrées de la base de référence du périmètre (`/add-dir`, `--add-dir`, `advisorModel`…)."""
    kb = "openai" if perimetre == "openai" else "claude"
    noms: set[str] = set()
    for f in (racine / "docs" / "data" / "kb" / kb).glob("*.json"):
        try:
            noms |= {e["nom"] for e in json.loads(f.read_text(encoding="utf-8")).get("entrees", []) if e.get("nom")}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    return noms


def nom_connu(nom: str, texte_contexte: str, noms_base: set[str]) -> bool:
    if len(nom) < NOMS_TROP_COURTS or nom.lower() in NOMS_VALEURS:
        return False
    premier = nom.split()[0]
    return nom in texte_contexte or nom in noms_base or (len(premier) >= NOMS_TROP_COURTS and premier in noms_base)


def avertir_puces(q: dict, brut: dict, texte_contexte: str, noms_base: set[str], r: Rapport, ou: str) -> None:
    """D95 (R2, avertissement seul) : un `ajout` des puces d'une nouveauté brute dont un nom figure dans CONTEXTE.md ou
    dans la base, et que ni `resume` ni `pour_toi` de l'élément ne cite."""
    puces = {n["id"]: n["puces"] for n in brut.get("nouveautes", []) if isinstance(n, dict) and isinstance(n.get("puces"), list)}
    for i, e in enumerate(q.get("elements", [])):
        if not isinstance(e, dict):
            continue
        dits = " ".join(str(e.get(c) or "") for c in ("resume", "pour_toi")).lower()
        for ident in e.get("ids_bruts") or []:
            for p in puces.get(ident, []):
                if not isinstance(p, dict) or p.get("genre") != "ajout":
                    continue
                connus = [n for n in p.get("noms") or [] if isinstance(n, str) and nom_connu(n, texte_contexte, noms_base)]
                if connus and not any(n.lower() in dits for n in p["noms"] if isinstance(n, str)):
                    r.avertissement(f"{ou} elements[{i}] ({e.get('id')})",
                                    f"R2 : ajout de {ident} jamais cité dans `resume` ni `pour_toi` : "
                                    f"{', '.join(f'`{n}`' for n in connus)} (« {p.get('texte', '')[:70]} »)")


def compter_impacts(q: dict) -> dict:
    c = {k: 0 for k in ("fort", "moyen", "faible", "nul")}
    for e in q.get("elements", []):
        if isinstance(e, dict) and e.get("impact") in c:
            c[e["impact"]] += 1
    return c


def verifier_index(dossier: Path, perimetre: str, quotidiens: dict[str, dict], r: Rapport) -> None:
    chemin = dossier / "index.json"
    ou = "index.json"
    if not chemin.exists():
        r.erreur(ou, "absent")
        return
    try:
        idx = json.loads(chemin.read_text(encoding="utf-8"))
    except ValueError as e:
        r.erreur(ou, f"JSON invalide : {e}")
        return
    if not isinstance(idx, dict) or set(idx) != {"perimetre", "agent", "maj_le", "jours"}:
        r.erreur(ou, "champs attendus : perimetre, agent, maj_le, jours")
        return
    if idx["perimetre"] != perimetre or idx["agent"] != AGENTS[perimetre]:
        r.erreur(ou, f"perimetre/agent incohérents : {idx['perimetre']!r}/{idx['agent']!r}")
    jours = idx["jours"]
    if not isinstance(jours, list):
        r.erreur(ou, "`jours` doit être un tableau")
        return
    dates = [j.get("date") for j in jours if isinstance(j, dict)]
    if dates != sorted(dates, reverse=True):
        r.erreur(ou, "`jours` doit être trié par date décroissante")
    if set(dates) != set(quotidiens):
        r.erreur(ou, f"dates de l'index {sorted(dates)} ≠ fichiers quotidiens {sorted(quotidiens)}")
    for j in jours:
        if not isinstance(j, dict) or set(j) != {"date", "genere_le", "elements", "impact", "ecartes"}:
            r.erreur(ou, f"entrée de jour mal formée : {j}")
            continue
        q = quotidiens.get(j["date"])
        if q is None:
            continue
        if j["elements"] != len(q.get("elements", [])):
            r.erreur(ou, f"{j['date']}: `elements` {j['elements']} ≠ {len(q.get('elements', []))}")
        if j["impact"] != compter_impacts(q):
            r.erreur(ou, f"{j['date']}: `impact` {j['impact']} ≠ {compter_impacts(q)}")
        if j["ecartes"] != len(q.get("ecartes", [])):
            r.erreur(ou, f"{j['date']}: `ecartes` {j['ecartes']} ≠ {len(q.get('ecartes', []))}")
        if j["genere_le"] != q.get("genere_le"):
            r.erreur(ou, f"{j['date']}: `genere_le` différent du fichier quotidien")


# ----------------------------------------------------------------------------------------------- base de référence (D40, D41, SPEC §7.4)

CHAMPS_KB = {"id", "produit", "categorie", "nom", "gabarit", "description", "description_source", "usage", "usage_nature", "exemple",
             "disponibilite", "statut_usage", "recommandation", "sources", "commentee", "contexte_empreinte", "contexte_sections", "retiree",
             "origine", "groupe", "maj_le", "historique"}
CHAMPS_KB_FACULTATIFS = {"exemple_origine"}  # D91 : présent seulement quand un exemple a été écrit sous la règle de provenance
MOTS_FR = {"le", "la", "les", "des", "du", "une", "un", "et", "pour", "est", "dans", "qui", "sur", "avec", "pas", "ton", "tes", "tu", "au", "aux", "ce", "cette"}
MOTS_EN = {"the", "and", "to", "of", "is", "for", "with", "this", "that", "you", "your", "when", "are", "it"}
LONGUEURS = {"complet": {"description": 900, "pourquoi": 450}, "court": {"description": 350, "pourquoi": 300}}


def est_francais(texte: str) -> bool:
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", texte.lower())
    fr = sum(1 for m in mots if m in MOTS_FR) + sum(1 for m in mots if re.search(r"[àâçéèêëîïôûùœ]", m))
    en = sum(1 for m in mots if m in MOTS_EN)
    return fr > en and fr >= 2


def verifier_kb(racine: Path, perimetre: str, r: Rapport) -> set[str]:
    from deltalib.kb.catalogue import ORIGINES_EXEMPLE
    from deltalib.kb.modeles import CATEGORIES, PRODUITS_PAR_PERIMETRE, STATUTS_USAGE, VERDICTS, gabarit_de
    if perimetre not in PRODUITS_PAR_PERIMETRE:
        r.erreur("kb", f"pas de base de référence pour le périmètre {perimetre!r}")
        return set()
    dossier = racine / "docs" / "data" / "kb" / perimetre
    ids: set[str] = set()
    sans_exemple = 0
    for cat in CATEGORIES:
        chemin = dossier / f"{cat}.json"
        ou = f"kb/{perimetre}/{cat}.json"
        if not chemin.exists():
            r.erreur(ou, "absent (les sept catégories sont toujours écrites, même vides)")
            continue
        texte = chemin.read_text(encoding="utf-8")
        verifier_secrets(texte, ou, r)
        try:
            doc = json.loads(texte)
        except ValueError as e:
            r.erreur(ou, f"JSON invalide : {e}")
            continue
        if doc.get("perimetre") != perimetre or doc.get("categorie") != cat or not isinstance(doc.get("entrees"), list):
            r.erreur(ou, "en-tête attendu : perimetre, categorie, maj_le, total, commentees, entrees")
            continue
        entrees = doc["entrees"]
        if doc.get("total") != len(entrees) or doc.get("commentees") != sum(1 for e in entrees if isinstance(e, dict) and e.get("commentee")):
            r.erreur(ou, "compteurs `total` ou `commentees` incohérents")
        for i, e in enumerate(entrees):
            o = f"{ou} [{i}] {e.get('id', '?') if isinstance(e, dict) else '?'}"
            if not isinstance(e, dict):
                r.erreur(o, "n'est pas un objet")
                continue
            manquants = CHAMPS_KB - set(e)
            if manquants:
                r.erreur(o, f"champs manquants : {sorted(manquants)}")
                continue
            if set(e) - CHAMPS_KB - CHAMPS_KB_FACULTATIFS:
                r.erreur(o, f"champs inconnus : {sorted(set(e) - CHAMPS_KB - CHAMPS_KB_FACULTATIFS)}")
            if e["id"] in ids:
                r.erreur(o, "identifiant en double dans la base")
            ids.add(e["id"])
            if e["produit"] not in PRODUITS_PAR_PERIMETRE[perimetre]:
                r.erreur(o, f"produit {e['produit']!r} hors du périmètre")
            if e["categorie"] != cat:
                r.erreur(o, f"catégorie {e['categorie']!r} dans le fichier {cat}")
            if not re.fullmatch(rf"{re.escape(str(e['produit']))}-{cat}-[a-z0-9-]+", str(e["id"])):
                r.erreur(o, "identifiant attendu : <produit>-<categorie>-<slug>")
            if e["gabarit"] != gabarit_de(cat):
                r.erreur(o, f"gabarit {e['gabarit']!r} au lieu de {gabarit_de(cat)!r}")
            if not isinstance(e["nom"], str) or not e["nom"].strip():
                r.erreur(o, "`nom` vide")
            if not isinstance(e["usage"], str) or not e["usage"].strip():
                r.erreur(o, "`usage` vide")
            if e["usage_nature"] not in ("syntaxe", "etapes"):
                r.erreur(o, f"`usage_nature` doit valoir syntaxe ou etapes : {e['usage_nature']!r}")
            exemple, origine = e["exemple"], e.get("exemple_origine")
            if exemple is not None and not (isinstance(exemple, str) and exemple.strip()):
                r.erreur(o, "`exemple` : texte non vide ou null")
            elif origine is not None and origine not in ORIGINES_EXEMPLE:
                r.erreur(o, f"`exemple_origine` doit valoir source ou compose : {origine!r}")
            elif origine is not None and exemple is None:
                r.erreur(o, "`exemple_origine` sans `exemple`")
            elif origine is not None and e["usage_nature"] != "syntaxe":
                r.erreur(o, "`exemple_origine` sur une entrée dont `usage_nature` est `etapes` (exemple: null)")
            if (cat in ("commandes", "fonctionnalites") and e["retiree"] is not True and e["usage_nature"] == "syntaxe"
                    and not (isinstance(exemple, str) and exemple.strip())):
                sans_exemple += 1
            src = e["sources"]
            if not isinstance(src, list) or not src or not all(
                    isinstance(s, dict) and str(s.get("url", "")).startswith(("http://", "https://")) and s.get("libelle")
                    and isinstance(s.get("officielle"), bool) for s in src):
                r.erreur(o, "`sources` : au moins une source {url http(s), libelle, officielle}")
            if e["statut_usage"] not in STATUTS_USAGE:
                r.erreur(o, f"`statut_usage` inconnu : {e['statut_usage']!r}")
            if not _date_valide(e["maj_le"]):
                r.erreur(o, "`maj_le` doit être AAAA-MM-JJ")
            if not isinstance(e["historique"], list) or not all(
                    isinstance(h, dict) and _date_valide(h.get("date")) and str(h.get("changement", "")).strip() for h in e["historique"]):
                r.erreur(o, "`historique` : liste de {date, changement}")
            for champ in ("commentee", "retiree"):
                if not isinstance(e[champ], bool):
                    r.erreur(o, f"`{champ}` doit être un booléen")
            ce = e["contexte_empreinte"]
            if ce is not None and not (isinstance(ce, str) and re.fullmatch(r"[0-9a-f]{40}", ce)):
                r.erreur(o, "`contexte_empreinte` : sha1 de CONTEXTE.md (40 hexadécimaux) ou null")
            if e["contexte_sections"] is not None:  # null : antérieur à D64, jamais réévalué pour autant
                verifier_sections(e["contexte_sections"], o, r, ctx_disparu_permis=True)
            if e["commentee"] is True and ce is None:
                r.erreur(o, "entrée commentée sans `contexte_empreinte` (D60)")
            if e["commentee"] is True:
                lim = LONGUEURS[e["gabarit"]]
                d = e["description"]
                if not isinstance(d, str) or not d.strip():
                    r.erreur(o, "entrée commentée sans `description`")
                elif not est_francais(d):
                    r.erreur(o, "`description` d'une entrée commentée doit être en français")
                elif len(d) > lim["description"]:
                    r.erreur(o, f"`description` trop longue pour le gabarit {e['gabarit']} ({len(d)} > {lim['description']})")
                rec = e["recommandation"]
                if not isinstance(rec, dict) or rec.get("verdict") not in VERDICTS or not str(rec.get("pourquoi", "")).strip():
                    r.erreur(o, "entrée commentée sans `recommandation` {verdict, pourquoi}")
                elif len(rec["pourquoi"]) > lim["pourquoi"]:
                    r.erreur(o, f"`pourquoi` trop long pour le gabarit {e['gabarit']}")
    if sans_exemple:  # D91 : avertissement seulement, jamais un arrêt
        r.avertissement(f"kb/{perimetre}", f"{sans_exemple} entrées commandes/fonctionnalités sans exemple")
    verifier_journal(dossier / "reevaluations.jsonl", f"kb/{perimetre}/reevaluations.jsonl", ids, r)
    verifier_recent(racine, perimetre, ids, r)
    verifier_a_tester(racine, perimetre, ids, r)
    return ids


def verifier_recent(racine: Path, perimetre: str, ids: set[str], r: Rapport) -> None:
    """D99 : docs/data/kb/recent.json (ajouts des 30 derniers jours, deux périmètres réunis). Absent : accepté (l'onglet
    Aujourd'hui s'en passe) ; présent : schéma, tri, plafond, et chaque entrée de ce périmètre existe dans la base."""
    from deltalib.kb.catalogue import RECENT_JOURS, RECENT_MAX, chemin_recent
    from deltalib.kb.modeles import CATEGORIES, PRODUITS_PAR_PERIMETRE, VERDICTS
    chemin, ou = chemin_recent(racine), "kb/recent.json"
    if not chemin.exists():
        return
    texte = chemin.read_text(encoding="utf-8")
    verifier_secrets(texte, ou, r)
    try:
        doc = json.loads(texte)
    except json.JSONDecodeError as e:
        r.erreur(ou, f"JSON invalide : {e}")
        return
    if not isinstance(doc, dict) or not isinstance(doc.get("entrees"), list):
        r.erreur(ou, "objet avec une liste `entrees` attendu")
        return
    if not (isinstance(doc.get("genere_le"), str) and RE_DATE.match(doc["genere_le"])):
        r.erreur(ou, "`genere_le` doit être une date AAAA-MM-JJ")
    if doc.get("fenetre_jours") != RECENT_JOURS:
        r.erreur(ou, f"`fenetre_jours` doit valoir {RECENT_JOURS}")
    liste = doc["entrees"]
    if not isinstance(doc.get("total"), int) or isinstance(doc.get("total"), bool) or doc["total"] < len(liste):
        r.erreur(ou, "`total` (entrées de la fenêtre avant coupe) doit être un entier au moins égal à la longueur de `entrees`")
    if not isinstance(doc.get("tronque"), bool) or doc.get("tronque") != (isinstance(doc.get("total"), int) and doc["total"] > len(liste)):
        r.erreur(ou, "`tronque` doit être un booléen vrai exactement quand `total` dépasse la longueur de `entrees`")
    if len(liste) > RECENT_MAX:
        r.erreur(ou, f"{len(liste)} entrées, plafond {RECENT_MAX}")
    if doc.get("plus_ancienne") != (liste[-1].get("date_ajout") if liste and isinstance(liste[-1], dict) else None):
        r.erreur(ou, "`plus_ancienne` doit être la date d'ajout de la dernière entrée (null si aucune)")
    vus, precedente = set(), None
    mes_produits = PRODUITS_PAR_PERIMETRE[perimetre]
    for i, e in enumerate(liste):
        o = f"{ou} entrees[{i}]"
        if not isinstance(e, dict):
            r.erreur(o, "objet attendu")
            continue
        if set(e) != {"id", "produit", "categorie", "nom", "usage", "usage_nature", "exemple", "verdict", "date_ajout"}:
            r.erreur(o, f"champs inattendus ou manquants : {sorted(e)}")
            continue
        if not isinstance(e["id"], str) or e["id"] in vus:
            r.erreur(o, "`id` absent, mal formé ou en double")
        vus.add(e["id"])
        if e["categorie"] not in CATEGORIES:
            r.erreur(o, f"`categorie` inconnue : {e['categorie']!r}")
        if not isinstance(e["nom"], str) or not e["nom"].strip():
            r.erreur(o, "`nom` vide")
        if not isinstance(e["usage"], str) or not e["usage"].strip():
            r.erreur(o, "`usage` vide")
        if e["usage_nature"] not in ("syntaxe", "etapes"):
            r.erreur(o, "`usage_nature` doit valoir syntaxe ou etapes")
        if e["exemple"] is not None and not isinstance(e["exemple"], str):
            r.erreur(o, "`exemple` doit être une chaîne ou null")
        if e["verdict"] is not None and e["verdict"] not in VERDICTS:
            r.erreur(o, f"`verdict` inconnu : {e['verdict']!r}")
        d = e["date_ajout"]
        if not (isinstance(d, str) and RE_DATE.match(d)):
            r.erreur(o, "`date_ajout` doit être une date AAAA-MM-JJ")
        elif precedente is not None and d > precedente:
            r.erreur(o, "entrées à trier par `date_ajout` décroissante")
        else:
            precedente = d
        if e["produit"] in mes_produits and e["id"] not in ids:
            r.erreur(o, f"`id` absent de la base {perimetre}")


def verifier_a_tester(racine: Path, perimetre: str, ids: set[str], r: Rapport) -> None:
    """D103 : docs/data/kb/a-tester.json (essais de la base, verdicts tester puis utiliser, deux périmètres réunis). Absent :
    accepté (l'onglet « À tester » s'en passe) ; présent : schéma, tri, plafond, et chaque entrée de ce périmètre existe."""
    from deltalib.kb.catalogue import A_TESTER_MAX, A_TESTER_VERDICTS, chemin_a_tester
    from deltalib.kb.modeles import CATEGORIES, PRODUITS_PAR_PERIMETRE
    chemin, ou = chemin_a_tester(racine), "kb/a-tester.json"
    if not chemin.exists():
        return
    texte = chemin.read_text(encoding="utf-8")
    verifier_secrets(texte, ou, r)
    try:
        doc = json.loads(texte)
    except json.JSONDecodeError as e:
        r.erreur(ou, f"JSON invalide : {e}")
        return
    if not isinstance(doc, dict) or not isinstance(doc.get("entrees"), list):
        r.erreur(ou, "objet avec une liste `entrees` attendu")
        return
    if not (isinstance(doc.get("genere_le"), str) and RE_DATE.match(doc["genere_le"])):
        r.erreur(ou, "`genere_le` doit être une date AAAA-MM-JJ")
    liste = doc["entrees"]
    if not isinstance(doc.get("total"), int) or isinstance(doc.get("total"), bool) or doc["total"] < len(liste):
        r.erreur(ou, "`total` (entrées retenues avant coupe) doit être un entier au moins égal à la longueur de `entrees`")
    if not isinstance(doc.get("tronque"), bool) or doc.get("tronque") != (isinstance(doc.get("total"), int) and doc["total"] > len(liste)):
        r.erreur(ou, "`tronque` doit être un booléen vrai exactement quand `total` dépasse la longueur de `entrees`")
    if len(liste) > A_TESTER_MAX:
        r.erreur(ou, f"{len(liste)} entrées, plafond {A_TESTER_MAX}")
    vus, precedente = set(), None  # precedente : (rang du verdict, date d'ajout) de l'entrée d'avant
    mes_produits = PRODUITS_PAR_PERIMETRE[perimetre]
    for i, e in enumerate(liste):
        o = f"{ou} entrees[{i}]"
        if not isinstance(e, dict):
            r.erreur(o, "objet attendu")
            continue
        if set(e) != {"id", "produit", "categorie", "nom", "usage", "usage_nature", "exemple", "verdict", "pourquoi", "date_ajout"}:
            r.erreur(o, f"champs inattendus ou manquants : {sorted(e)}")
            continue
        if not isinstance(e["id"], str) or e["id"] in vus:
            r.erreur(o, "`id` absent, mal formé ou en double")
        vus.add(e["id"])
        if e["categorie"] not in CATEGORIES:
            r.erreur(o, f"`categorie` inconnue : {e['categorie']!r}")
        for champ in ("nom", "usage"):
            if not isinstance(e[champ], str) or not e[champ].strip():
                r.erreur(o, f"`{champ}` vide")
        if e["usage_nature"] not in ("syntaxe", "etapes"):
            r.erreur(o, "`usage_nature` doit valoir syntaxe ou etapes")
        if e["exemple"] is not None and not isinstance(e["exemple"], str):
            r.erreur(o, "`exemple` doit être une chaîne ou null")
        if e["pourquoi"] is not None and not isinstance(e["pourquoi"], str):
            r.erreur(o, "`pourquoi` doit être une chaîne ou null")
        if e["verdict"] not in A_TESTER_VERDICTS:
            r.erreur(o, f"`verdict` doit valoir tester ou utiliser : {e['verdict']!r}")
            continue
        d = e["date_ajout"]
        if d is not None and not (isinstance(d, str) and RE_DATE.match(d)):
            r.erreur(o, "`date_ajout` doit être une date AAAA-MM-JJ ou null")
            continue
        cle = (A_TESTER_VERDICTS.index(e["verdict"]), d)
        if precedente is not None and (cle[0] < precedente[0] or (cle[0] == precedente[0] and (cle[1] or "") > (precedente[1] or ""))):
            r.erreur(o, "entrées à trier par verdict (tester d'abord) puis `date_ajout` décroissante")
        else:
            precedente = cle
        if e["produit"] in mes_produits and e["id"] not in ids:
            r.erreur(o, f"`id` absent de la base {perimetre}")


# age, legacy et nouveau-projet ne sont plus produits (D64-bis amendée le 29/09/2026 ; rattrapage legacy openai effectué
# le 29/09/2026, code retiré) ; ils restent valides dans le journal existant
RE_MOTIF = re.compile(r"^(?:section:[A-Za-z0-9._-]+|adoption|age|legacy|nouveau-projet:[A-Za-z0-9._-]+|rejugement demandé \([^\r\n]+\))$")


def verifier_journal(chemin: Path, ou: str, ids: set[str], r: Rapport) -> None:
    """B3 : une ligne JSON {date, id, verdict_avant, verdict_apres, motif} par réévaluation."""
    if not chemin.exists():
        return
    texte = chemin.read_text(encoding="utf-8")
    verifier_secrets(texte, ou, r)
    for n, ligne in enumerate(texte.splitlines(), 1):
        if not ligne.strip():
            continue
        try:
            l = json.loads(ligne)
        except ValueError:
            r.erreur(f"{ou}:{n}", "JSON invalide")
            continue
        if not isinstance(l, dict) or set(l) != {"date", "id", "verdict_avant", "verdict_apres", "motif"}:
            r.erreur(f"{ou}:{n}", "{date, id, verdict_avant, verdict_apres, motif} attendu")
            continue
        if not _date_valide(l["date"]) or l["id"] not in ids or not RE_MOTIF.match(str(l["motif"])):
            r.erreur(f"{ou}:{n}", f"date, id ou motif invalide : {l['date']!r}, {l['id']!r}, {l['motif']!r}")


def verifier_versions(racine: Path, r: Rapport) -> None:
    """D55 : docs/data/versions.json, écrit par scripts/versions.py."""
    chemin = racine / "docs" / "data" / "versions.json"
    ou = "versions.json"
    if not chemin.exists():
        return
    texte = chemin.read_text(encoding="utf-8")
    verifier_secrets(texte, ou, r)
    try:
        lignes = json.loads(texte)
    except ValueError as e:
        r.erreur(ou, f"JSON invalide : {e}")
        return
    if not isinstance(lignes, list) or not lignes:
        r.erreur(ou, "tableau non vide attendu")
        return
    attendus = {"outil", "version", "detectee_le", "methode", "derniere_publiee", "source_derniere", "statut"}
    for i, l in enumerate(lignes):
        o = f"{ou}[{i}]"
        if not isinstance(l, dict) or not attendus <= set(l) or set(l) - attendus - {"raison", "note", "pertinent_pour_profil"}:
            r.erreur(o, f"champs attendus {sorted(attendus)} (+ raison, note, pertinent_pour_profil)")
            continue
        if "pertinent_pour_profil" in l and not isinstance(l["pertinent_pour_profil"], bool):
            r.erreur(o, "`pertinent_pour_profil` doit être un booléen (D79)")
        if l["statut"] not in ("a_jour", "en_retard", "inconnu", "embarque", "non_utilise"):
            r.erreur(o, f"statut inconnu : {l['statut']!r}")
        if l["version"] is None and not l.get("raison"):
            r.erreur(o, "version introuvable sans `raison`")
        if l["statut"] in ("a_jour", "en_retard") and (l["version"] is None or l["derniere_publiee"] is None):
            r.erreur(o, "sans version installée ou publiée, le statut doit être `inconnu`")
        if l["statut"] in ("embarque", "non_utilise") and (l["version"] is None or not l.get("note")):
            r.erreur(o, f"statut `{l['statut']}` : version installée et `note` obligatoires")
        if l["statut"] == "embarque" and l["derniere_publiee"] is not None:
            r.erreur(o, "statut `embarque` : non comparé, `derniere_publiee` doit être null")
        if l["derniere_publiee"] is not None and not l["source_derniere"]:
            r.erreur(o, "`derniere_publiee` sans `source_derniere`")
        if not isinstance(l["detectee_le"], str) or "T" not in l["detectee_le"]:
            r.erreur(o, "`detectee_le` doit être un horodatage ISO 8601")


COMPTES_QUOTAS = ("claude_session_5h", "claude_semaine", "claude_semaine_fable", "chatgpt_semaine")


def _horodatage_ou_null(v) -> bool:
    if v is None:
        return True
    if not isinstance(v, str) or "T" not in v:
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


CREDITS_CHAMPS = {"nom", "solde_usd", "releve_le", "expire_le", "jours_restants"}


def verifier_credits(credits, ou: str, r: Rapport) -> None:
    """D102 (D71) : `comptes.credits`, crédits datés. Une valeur null porte une `raison` ; jamais de date ou de solde deviné."""
    o = f"{ou}.credits"
    if not isinstance(credits, list):
        r.erreur(o, "doit être une liste")
        return
    for i, v in enumerate(credits):
        oc = f"{o}[{i}]"
        if not isinstance(v, dict) or not CREDITS_CHAMPS <= set(v) or set(v) - CREDITS_CHAMPS - {"raison"}:
            r.erreur(oc, "champs attendus : nom, solde_usd, releve_le, expire_le, jours_restants (+ raison)")
            continue
        if not isinstance(v["nom"], str) or not v["nom"].strip():
            r.erreur(oc, "`nom` doit être un texte non vide")
        solde, jours = v["solde_usd"], v["jours_restants"]
        if solde is not None and (isinstance(solde, bool) or not isinstance(solde, (int, float)) or solde != solde or solde < 0):
            r.erreur(oc, "`solde_usd` doit être un nombre positif ou null")
        if jours is not None and (isinstance(jours, bool) or not isinstance(jours, int) or jours < 0):
            r.erreur(oc, "`jours_restants` doit être un entier positif ou null")
        for champ in ("releve_le", "expire_le"):
            if not _horodatage_ou_null(v[champ]):
                r.erreur(oc, f"`{champ}` doit être un horodatage ISO 8601 ou null")
        if v["expire_le"] is None and jours is not None:
            r.erreur(oc, "`jours_restants` sans `expire_le` : valeur devinée")
        if (solde is None or v["expire_le"] is None) and not str(v.get("raison") or "").strip():
            r.erreur(oc, "valeur null sans `raison`")


def verifier_comptes(c, ou: str, r: Rapport) -> None:
    """D93 (D71) : bloc `comptes` d'etat.json. Pourcentages entiers de 0 à 100 (ou null avec raison), dates ISO ou null."""
    o = f"{ou} comptes"
    if not isinstance(c, dict):
        r.erreur(o, "doit être un objet")
        return
    if c.get("statut") == "inconnu":
        if not str(c.get("raison") or "").strip():
            r.erreur(o, "`statut: inconnu` sans `raison`")
        if set(c) - {"statut", "raison", "credits"}:
            r.erreur(o, "`statut: inconnu` n'admet que `statut`, `raison` et `credits` (aucune valeur devinée)")
        if "credits" in c:
            verifier_credits(c["credits"], o, r)
        return
    if c.get("statut") != "ok":
        r.erreur(o, "`statut` doit valoir ok ou inconnu")
        return
    if set(c) - {"statut", "source", "releve_le", "quotas", "credits"}:
        r.erreur(o, "champs admis : statut, source, releve_le, quotas, credits (rien de machine ni de wifi)")
    if "credits" in c:
        verifier_credits(c["credits"], o, r)
    if not _horodatage_ou_null(c.get("releve_le")):
        r.erreur(o, "`releve_le` doit être un horodatage ISO 8601 ou null")
    q = c.get("quotas")
    if not isinstance(q, dict) or set(q) != set(COMPTES_QUOTAS):
        r.erreur(o, f"`quotas` doit porter exactement {', '.join(COMPTES_QUOTAS)}")
        return
    for nom, v in q.items():
        oq = f"{o}.{nom}"
        if not isinstance(v, dict) or not {"pct", "remise_a_zero", "releve_le"} <= set(v) or set(v) - {"pct", "remise_a_zero", "releve_le", "raison"}:
            r.erreur(oq, "champs attendus : pct, remise_a_zero, releve_le (+ raison)")
            continue
        pct = v["pct"]
        if pct is None:
            if not str(v.get("raison") or "").strip():
                r.erreur(oq, "`pct` null sans `raison`")
        elif isinstance(pct, bool) or not isinstance(pct, int) or not 0 <= pct <= 100:
            r.erreur(oq, "`pct` doit être un entier de 0 à 100")
        for champ in ("remise_a_zero", "releve_le"):
            if not _horodatage_ou_null(v[champ]):
                r.erreur(oq, f"`{champ}` doit être un horodatage ISO 8601 ou null")


def verifier_etat(racine: Path, r: Rapport) -> None:
    """D65 : docs/data/etat.json, écrit par scripts/etat.py. Chaque relevé {valeur, source, raison} ; raison si null."""
    chemin = racine / "docs" / "data" / "etat.json"
    ou = "etat.json"
    if not chemin.exists():
        return
    texte = chemin.read_text(encoding="utf-8")
    verifier_secrets(texte, ou, r)
    if re.search(r'"(env|headers|args|token|api_key|bearer_token\w*)"\s*:', texte, re.I):
        r.erreur(ou, "champ sensible publié (env, headers, args, jeton) : interdit (REGLES §5)")
    if re.search(r"https?://[^\s\"]*\?", texte):
        r.erreur(ou, "URL avec paramètres : seules les URL sans paramètres sont publiées")
    try:
        e = json.loads(texte)
    except ValueError as err:
        r.erreur(ou, f"JSON invalide : {err}")
        return
    if not isinstance(e, dict) or not {"releve_le", "outils", "mcp_claude_code", "instructions_globales"} <= set(e):
        r.erreur(ou, "champs attendus : releve_le, outils, mcp_claude_code, instructions_globales")
        return
    if not isinstance(e["releve_le"], str) or "T" not in e["releve_le"]:
        r.erreur(ou, "`releve_le` doit être un horodatage ISO 8601")
    if "pertinent_pour_profil" in e and not isinstance(e["pertinent_pour_profil"], bool):
        r.erreur(ou, "`pertinent_pour_profil` doit être un booléen (D79)")

    if "comptes" in e:
        verifier_comptes(e["comptes"], ou, r)

    def parcourir(n, chemin_):
        if isinstance(n, dict):
            if "valeur" in n and "source" in n:
                if n["valeur"] is None and not str(n.get("raison") or "").strip():
                    r.erreur(ou, f"{chemin_} : valeur null sans `raison`")
            if "elements" in n and "source" in n and not n["elements"] and not str(n.get("raison") or "").strip():
                r.erreur(ou, f"{chemin_} : liste vide sans `raison`")
            for k, v in n.items():
                parcourir(v, f"{chemin_}.{k}")
        elif isinstance(n, list):
            for i, v in enumerate(n):
                parcourir(v, f"{chemin_}[{i}]")
    parcourir(e, "etat")


CHAMPS_SEMAINE = {"semaine", "du", "au", "genere_le", "statut", "raison", "sources", "d71", "elements", "base_ajoutees", "base_verdicts"}
CHAMPS_LIGNE_ELEMENT = {"perimetre", "id", "produit", "titre", "version", "impact", "certitude", "date_publication", "jour", "action"}
CHAMPS_LIGNE_KB = {"perimetre", "id", "produit", "categorie", "nom", "usage", "exemple", "exemple_origine", "verdict"}
CHAMPS_LIGNES_SEMAINE = {
    "d71": CHAMPS_LIGNE_ELEMENT, "elements": CHAMPS_LIGNE_ELEMENT,
    "base_ajoutees": CHAMPS_LIGNE_KB | {"date_ajout"},
    "base_verdicts": CHAMPS_LIGNE_KB | {"date", "verdict_avant", "verdict_apres", "pourquoi"},
}
SOURCES_SEMAINE = {*bilan_semaine.PERIMETRES_JOURS, *(f"kb-{p}" for p in bilan_semaine.PERIMETRES_KB)}


def _est_jour(v) -> bool:
    return isinstance(v, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)) and _date_valide(v)


def _verifier_lignes_semaine(d: dict, ou: str, r: Rapport) -> None:
    for liste, champs in CHAMPS_LIGNES_SEMAINE.items():
        lignes = d[liste]
        if not isinstance(lignes, list):
            r.erreur(ou, f"`{liste}` doit être une liste")
            continue
        for i, l in enumerate(lignes):
            oi = f"{ou} {liste}[{i}]"
            if not isinstance(l, dict) or set(l) != champs:
                r.erreur(oi, f"champs attendus : {', '.join(sorted(champs))}")
                continue
            if not isinstance(l["id"], str) or not l["id"] or l["perimetre"] not in {"claude", "actu", "openai"}:
                r.erreur(oi, "`id` (texte) ou `perimetre` invalide")
            if liste in ("d71", "elements"):
                if l["impact"] not in IMPACTS or not _est_jour(l["jour"]):
                    r.erreur(oi, "`impact` ou `jour` invalide")
                if liste == "elements" and l["impact"] not in bilan_semaine.IMPACTS_RETENUS:
                    r.erreur(oi, "`elements` ne reprend que les impacts fort et moyen")
            elif liste == "base_ajoutees":
                if not _est_jour(l["date_ajout"]) or not d["du"] <= l["date_ajout"] <= d["au"]:
                    r.erreur(oi, "`date_ajout` hors de la semaine")
            else:
                if not _est_jour(l["date"]) or not d["du"] <= l["date"] <= d["au"]:
                    r.erreur(oi, "`date` hors de la semaine")
                if l["verdict_apres"] not in bilan_semaine.VERDICTS_UTILES:
                    r.erreur(oi, "`verdict_apres` doit valoir utiliser ou tester")


def verifier_semaine(racine: Path, r: Rapport) -> None:
    """D98 : docs/data/semaine/AAAA-Www.json et index.json, écrits par scripts/semaine.py (champs recopiés, aucun texte rédigé)."""
    dossier = racine / "docs" / "data" / "semaine"
    if not dossier.exists():
        return
    lus: dict[str, dict] = {}
    for f in sorted(dossier.glob("????-W??.json")):
        ou = f"semaine/{f.name}"
        texte = f.read_text(encoding="utf-8")
        verifier_secrets(texte, ou, r)
        try:
            d = json.loads(texte)
        except ValueError as err:
            r.erreur(ou, f"JSON invalide : {err}")
            continue
        if not isinstance(d, dict) or set(d) != CHAMPS_SEMAINE:
            r.erreur(ou, f"champs attendus : {', '.join(sorted(CHAMPS_SEMAINE))}")
            continue
        try:
            lundi, dimanche = bilan_semaine.bornes(d["semaine"])
        except bilan_semaine.SemaineInvalide as err:
            r.erreur(ou, str(err))
            continue
        if d["semaine"] != f.stem or d["du"] != lundi.isoformat() or d["au"] != dimanche.isoformat():
            r.erreur(ou, "`semaine`, `du` et `au` doivent correspondre au nom du fichier (lundi et dimanche ISO)")
        if not _horodatage_ou_null(d["genere_le"]) or d["genere_le"] is None:
            r.erreur(ou, "`genere_le` doit être un horodatage ISO 8601")
        if d["statut"] not in ("ok", "echec"):
            r.erreur(ou, "`statut` doit valoir ok ou echec")
        elif (d["statut"] == "ok") != (d["raison"] is None) or (d["raison"] is not None and not str(d["raison"]).strip()):
            r.erreur(ou, "`raison` est null si et seulement si `statut` vaut ok")
        src = d["sources"]
        if not isinstance(src, dict) or set(src) != SOURCES_SEMAINE:
            r.erreur(ou, f"`sources` doit nommer exactement : {', '.join(sorted(SOURCES_SEMAINE))}")
        else:
            for nom, s in src.items():
                if not isinstance(s, dict) or set(s) != {"statut", "raison", "jours"} or s["statut"] not in ("ok", "echec") \
                        or not isinstance(s["jours"], list) or (s["statut"] == "ok") != (s["raison"] is None):
                    r.erreur(ou, f"`sources.{nom}` : {{statut ok|echec, raison (null si ok), jours}} attendu")
            if (d["statut"] == "ok") != all(isinstance(s, dict) and s.get("statut") == "ok" for s in src.values()):
                r.erreur(ou, "`statut` doit valoir echec si et seulement si une source est en echec")
        _verifier_lignes_semaine(d, ou, r)
        lus[f.stem] = d
    chemin = dossier / "index.json"
    if lus and not chemin.exists():
        r.erreur("semaine/index.json", "index absent alors que des semaines existent")
    if chemin.exists():
        try:
            index = json.loads(chemin.read_text(encoding="utf-8"))
        except ValueError as err:
            r.erreur("semaine/index.json", f"JSON invalide : {err}")
            return
        attendu = [{"semaine": k, "statut": v["statut"], "d71": len(v["d71"]), "elements": len(v["elements"]),
                    "base_ajoutees": len(v["base_ajoutees"]), "base_verdicts": len(v["base_verdicts"])}
                   for k, v in sorted(lus.items(), reverse=True)]
        recu = [{c: x.get(c) for c in ("semaine", "statut", "d71", "elements", "base_ajoutees", "base_verdicts")}
                for x in index.get("semaines", []) if isinstance(x, dict)] if isinstance(index, dict) else None
        if recu != attendu:
            r.erreur("semaine/index.json", "`semaines` doit correspondre exactement aux fichiers AAAA-Www.json (semaine, statut, compteurs)")


# D64-bis : ctx-id connus (actifs et dépréciés) du CONTEXTE.md de la racine ; None si absent ou illisible
CTX_IDS: set[str] | None = None


def charger_ctx_ids(racine: Path, r: Rapport) -> None:
    global CTX_IDS
    CTX_IDS = None
    chemin = racine / "CONTEXTE.md"
    if not chemin.exists():
        return
    try:
        s, dep = analyser_contexte(chemin.read_text(encoding="utf-8"))
    except ContexteInvalide as err:
        r.erreur("CONTEXTE.md", f"structure ctx-id invalide : {err}")
        return
    CTX_IDS = set(s) | set(dep)


def verifier_sections(cs, ou: str, r: Rapport, ctx_disparu_permis: bool = False) -> None:
    """D64-bis : {ctx-id: {sha1, pourquoi}} ; ctx-id connu de CONTEXTE.md, pourquoi non vide, une ligne, 160 car. max.
    `ctx_disparu_permis` (base de référence, D64-bis amendée le 29/09/2026) : une section citée qui a disparu de CONTEXTE.md
    rend l'entrée périmée (catégorie a, lot `perimees` de 10 entrées) sans être une erreur ; `catalogue.py appliquer`
    refuse déjà un ctx-id inconnu pour tout nouveau commentaire."""
    if not isinstance(cs, dict):
        r.erreur(ou, "`contexte_sections` : {ctx-id: {sha1, pourquoi}} (D64-bis)")
        return
    for k, v in cs.items():
        if not isinstance(v, dict) or set(v) != {"sha1", "pourquoi"} or not (
                isinstance(v["sha1"], str) and re.fullmatch(r"[0-9a-f]{40}", v["sha1"])):
            r.erreur(ou, f"`contexte_sections.{k}` : {{sha1, pourquoi}} attendu (D64-bis)")
            continue
        if v["sha1"] == SHA1_VIDE:
            r.erreur(ou, f"`contexte_sections.{k}` : section au corps vide, cite une sous-section (D64-bis)")
        for err in erreurs_pourquoi(v["pourquoi"]):
            r.erreur(ou, f"`contexte_sections.{k}` : {err}")
        if CTX_IDS is not None and k not in CTX_IDS and not ctx_disparu_permis:
            r.erreur(ou, f"`contexte_sections` : ctx-id inconnu de CONTEXTE.md : {k}")


def ids_kb(racine: Path, perimetre: str) -> set[str] | None:
    kb = "openai" if perimetre == "openai" else "claude"
    dossier = racine / "docs" / "data" / "kb" / kb
    if not dossier.exists() or not any(dossier.glob("*.json")):
        return None
    ids = set()
    for f in dossier.glob("*.json"):
        try:
            ids |= {e["id"] for e in json.loads(f.read_text(encoding="utf-8")).get("entrees", [])}
        except (ValueError, KeyError, AttributeError):
            pass
    return ids


def valider(perimetre: str, racine: Path, jour: date | None, brut: Path | None, contexte: Path) -> Rapport:
    r = Rapport()
    verifier_organisation_privee(racine, r)
    charger_ctx_ids(racine, r)
    dossier = racine / "docs" / "data" / DOSSIERS[perimetre]
    projets = projets_du_contexte(contexte)
    ancrage = termes_ancrage_du_contexte(contexte)
    if not contexte.exists():
        r.erreur("CONTEXTE.md", f"fichier introuvable : {contexte}")
    quotidiens: dict[str, dict] = {}
    jour_strict = (jour or date.today()).isoformat()
    for f in sorted(dossier.glob("????-??-??.json")):
        # Un ancien fichier du jour peut citer une section retirée depuis de CONTEXTE.md : il n'est pas réévalué
        # (D58 et D64-bis amendées le 29/09/2026). Seul le fichier du jour garde le refus strict.
        q = verifier_quotidien(f, perimetre, projets, r, ctx_disparu_permis=f.stem != jour_strict, ancrage=ancrage)
        if q is not None:
            quotidiens[f.stem] = q
    if not quotidiens:
        r.erreur(dossier.name, "aucun fichier quotidien AAAA-MM-JJ.json")
    if perimetre == "claude":
        verifier_versions(racine, r)  # D55 : chemin de Claude Code
        verifier_etat(racine, r)  # D65
        verifier_semaine(racine, r)  # D98
    connus = ids_kb(racine, perimetre)
    if connus is not None:
        for d, q in quotidiens.items():
            for e in q.get("elements", []):
                for ref in (e.get("kb_refs") or []) if isinstance(e, dict) else []:
                    if ref not in connus:
                        r.erreur(f"{d}.json", f"`kb_refs` inconnu dans la base de référence : {ref}")
    for d, q in quotidiens.items():
        for i, e in enumerate(q.get("elements", [])):
            if isinstance(e, dict):
                verifier_ids_kb(e, f"{d}.json elements[{i}]", r, connus)
    avertir_recopies(quotidiens, r)
    jour_iso = (jour or date.today()).isoformat()
    if brut is not None:
        q = quotidiens.get(jour_iso)
        if q is None:
            r.erreur(f"{jour_iso}.json", "fichier quotidien du jour absent, couverture du brut impossible")
        else:
            verifier_couverture(q, brut, r)
            try:
                contenu_brut = json.loads(brut.read_text(encoding="utf-8"))
                texte_contexte = contexte.read_text(encoding="utf-8") if contexte.exists() else ""
            except (OSError, ValueError):
                pass  # déjà signalé par verifier_couverture ; sans brut lisible, rien à comparer
            else:
                avertir_puces(q, contenu_brut, texte_contexte, noms_de_la_base(racine, perimetre), r, f"{jour_iso}.json")
    verifier_index(dossier, perimetre, quotidiens, r)
    return r


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="valider.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--perimetre", required=True, choices=PERIMETRES)
    p.add_argument("--date", type=date.fromisoformat, metavar="AAAA-MM-JJ", help="jour à couvrir avec --brut (défaut : aujourd'hui)")
    p.add_argument("--brut", type=Path, help="fichier raw/<p>-nouveautes.json dont chaque nouveauté doit être comptabilisée")
    p.add_argument("--contexte", type=Path, default=None, help="CONTEXTE.md (défaut : à la racine)")
    p.add_argument("--kb", action="store_true", help="valider la base de référence docs/data/kb/<perimetre>/ (SPEC §7.4)")
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.kb:
        rapport = Rapport()
        verifier_organisation_privee(args.racine, rapport)
        charger_ctx_ids(args.racine, rapport)
        ids = verifier_kb(args.racine, args.perimetre, rapport)
        if rapport.ok:
            print(f"valider.py : base de référence {args.perimetre} valide ({len(ids)} entrées)")
            for a in rapport.avertissements:  # D91 : ne change pas le code de sortie
                print(f"! AVERTISSEMENT {a}")
            return 0
        print(f"valider.py : {len(rapport.erreurs)} erreur(s) dans la base {args.perimetre}", file=sys.stderr)
        for e in rapport.erreurs[:200]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    contexte = args.contexte or (args.racine / "CONTEXTE.md")
    rapport = valider(args.perimetre, args.racine, args.date, args.brut, contexte)
    if rapport.ok:
        print(f"valider.py : {args.perimetre} valide")
    else:
        print(f"valider.py : {len(rapport.erreurs)} erreur(s) pour {args.perimetre}", file=sys.stderr)
        for e in rapport.erreurs:
            print(f"  - {e}", file=sys.stderr)
    for a in rapport.avertissements:  # D85 : ne change pas le code de sortie
        print(f"! AVERTISSEMENT {a}")
    return 0 if rapport.ok else 1


if __name__ == "__main__":
    sys.exit(main())
