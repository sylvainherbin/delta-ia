#!/usr/bin/env python3
"""Delta — validation des JSON produits par un agent avant commit (SPEC §7, D15).

Usage :
  valider.py --perimetre {claude,openai,actu} [--date AAAA-MM-JJ] [--brut raw/<p>-nouveautes.json]
             [--contexte CONTEXTE.md] [--racine <dossier>]
  valider.py --perimetre {claude,openai} --kb         base de référence (SPEC §7.4)

Vérifie tous les fichiers quotidiens du dossier `docs/data/<p>/` (schéma, énumérations, dates, unicité des
identifiants, cohérences, secrets), la couverture des nouveautés brutes par le fichier du jour (`--brut`),
et la cohérence de `index.json`. Code de sortie 0 si tout est valide, 1 sinon ; les erreurs sont listées.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deltalib.etat import DOSSIERS  # noqa: E402
from deltalib.contexte import SHA1_VIDE, ContexteInvalide, analyser as analyser_contexte, erreurs_pourquoi  # noqa: E402
from deltalib.modeles import PERIMETRES, PRODUITS  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent

AGENTS = {"claude": "claude-code", "actu": "claude-code", "openai": "codex"}
PRODUITS_PAR_PERIMETRE = {"claude": {"claude", "claude-code"}, "openai": {"chatgpt", "codex"}, "actu": {"actu"}}
TYPES = {"nouveaute", "amelioration", "correction", "changement_rupture", "depreciation", "actu"}
CERTITUDES = {"officiel", "rapporte", "non_confirme"}
IMPACTS = {"fort", "moyen", "faible", "nul"}
EFFORTS = {"5min", "30min", "plus"}
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_D58 = "2026-09-23"
DATE_D64 = "2026-09-24"  # éléments quotidiens datés après ce jour : `contexte_sections` obligatoire, format D64-bis
RE_SECRETS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "jeton GitHub (ghp_)"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "jeton GitHub (github_pat_)"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "clé API (sk-)"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "clé AWS (AKIA)"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|-----BEGIN"), "clé privée (-----BEGIN)"),
    (re.compile(r"https?://[^\s\"'<>]*[?&/;#](?:[A-Za-z_-]*(?:token|key|secret)[A-Za-z_-]*)=[^\s\"'<>&]+", re.I), "URL contenant token, key ou secret"),
]


class Rapport:
    def __init__(self) -> None:
        self.erreurs: list[str] = []

    def erreur(self, ou: str, message: str) -> None:
        self.erreurs.append(f"{ou}: {message}")

    @property
    def ok(self) -> bool:
        return not self.erreurs


def projets_du_contexte(chemin: Path) -> set[str]:
    """Noms de projets : titres `### 2.x <nom> — …` de CONTEXTE.md §2."""
    if not chemin.exists():
        return set()
    projets: set[str] = set()
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^###\s+2\.\d+\s+([^\s—]+(?:\s+[^\s—]+)*?)\s+—", ligne)
        if m:
            projets.add(m.group(1).strip())
    return projets


def _date_valide(v) -> bool:
    if not isinstance(v, str) or not RE_DATE.match(v):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def verifier_element(e: dict, i: int, perimetre: str, projets: set[str], r: Rapport, ou: str) -> None:
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
        if hors:
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
            verifier_sections(e["contexte_sections"], ou, r)
    if "revision" in e and not isinstance(e["revision"], bool):
        r.erreur(ou, "`revision` doit être un booléen")


def verifier_quotidien(chemin: Path, perimetre: str, projets: set[str], r: Rapport) -> dict | None:
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
        verifier_element(e, i, perimetre, projets, r, ou)
        if isinstance(e, dict) and "contexte_sections" not in e and isinstance(q.get("date"), str) and q["date"] > DATE_D64:
            r.erreur(f"{ou} elements[{i}]", "`contexte_sections` absent : sections de CONTEXTE.md citées (D64)")
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
MOTS_FR = {"le", "la", "les", "des", "du", "une", "un", "et", "pour", "est", "dans", "qui", "sur", "avec", "pas", "ton", "tes", "tu", "au", "aux", "ce", "cette"}
MOTS_EN = {"the", "and", "to", "of", "is", "for", "with", "this", "that", "you", "your", "when", "are", "it"}
LONGUEURS = {"complet": {"description": 900, "pourquoi": 450}, "court": {"description": 350, "pourquoi": 300}}


def est_francais(texte: str) -> bool:
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", texte.lower())
    fr = sum(1 for m in mots if m in MOTS_FR) + sum(1 for m in mots if re.search(r"[àâçéèêëîïôûùœ]", m))
    en = sum(1 for m in mots if m in MOTS_EN)
    return fr > en and fr >= 2


def verifier_kb(racine: Path, perimetre: str, r: Rapport) -> set[str]:
    from deltalib.kb.modeles import CATEGORIES, PRODUITS_PAR_PERIMETRE, STATUTS_USAGE, VERDICTS, gabarit_de
    if perimetre not in PRODUITS_PAR_PERIMETRE:
        r.erreur("kb", f"pas de base de référence pour le périmètre {perimetre!r}")
        return set()
    dossier = racine / "docs" / "data" / "kb" / perimetre
    ids: set[str] = set()
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
            if set(e) - CHAMPS_KB:
                r.erreur(o, f"champs inconnus : {sorted(set(e) - CHAMPS_KB)}")
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
            if e["contexte_sections"] is not None:
                verifier_sections(e["contexte_sections"], o, r)
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
    verifier_journal(dossier / "reevaluations.jsonl", f"kb/{perimetre}/reevaluations.jsonl", ids, r)
    return ids


RE_MOTIF = re.compile(r"^(?:section:[A-Za-z0-9._-]+|age|legacy|nouveau-projet:[A-Za-z0-9._-]+)$")


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
        if not isinstance(l, dict) or not attendus <= set(l) or set(l) - attendus - {"raison", "note"}:
            r.erreur(o, f"champs attendus {sorted(attendus)} (+ raison, note)")
            continue
        if l["statut"] not in ("a_jour", "en_retard", "inconnu"):
            r.erreur(o, f"statut inconnu : {l['statut']!r}")
        if l["version"] is None and not l.get("raison"):
            r.erreur(o, "version introuvable sans `raison`")
        if (l["version"] is None or l["derniere_publiee"] is None) and l["statut"] != "inconnu":
            r.erreur(o, "sans version installée ou publiée, le statut doit être `inconnu`")
        if l["derniere_publiee"] is not None and not l["source_derniere"]:
            r.erreur(o, "`derniere_publiee` sans `source_derniere`")
        if not isinstance(l["detectee_le"], str) or "T" not in l["detectee_le"]:
            r.erreur(o, "`detectee_le` doit être un horodatage ISO 8601")


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


def verifier_sections(cs, ou: str, r: Rapport) -> None:
    """D64-bis : {ctx-id: {sha1, pourquoi}} ; ctx-id connu de CONTEXTE.md, pourquoi non vide, une ligne, 160 car. max."""
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
        if CTX_IDS is not None and k not in CTX_IDS:
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
    charger_ctx_ids(racine, r)
    dossier = racine / "docs" / "data" / DOSSIERS[perimetre]
    projets = projets_du_contexte(contexte)
    if not projets:
        r.erreur("CONTEXTE.md", f"aucun projet trouvé dans {contexte} (titres `### 2.x <nom> — …`)")
    quotidiens: dict[str, dict] = {}
    for f in sorted(dossier.glob("????-??-??.json")):
        q = verifier_quotidien(f, perimetre, projets, r)
        if q is not None:
            quotidiens[f.stem] = q
    if not quotidiens:
        r.erreur(dossier.name, "aucun fichier quotidien AAAA-MM-JJ.json")
    if perimetre == "claude":
        verifier_versions(racine, r)  # D55 : chemin de Claude Code
        verifier_etat(racine, r)  # D65
    connus = ids_kb(racine, perimetre)
    if connus is not None:
        for d, q in quotidiens.items():
            for e in q.get("elements", []):
                for ref in (e.get("kb_refs") or []) if isinstance(e, dict) else []:
                    if ref not in connus:
                        r.erreur(f"{d}.json", f"`kb_refs` inconnu dans la base de référence : {ref}")
    jour_iso = (jour or date.today()).isoformat()
    if brut is not None:
        q = quotidiens.get(jour_iso)
        if q is None:
            r.erreur(f"{jour_iso}.json", "fichier quotidien du jour absent, couverture du brut impossible")
        else:
            verifier_couverture(q, brut, r)
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
        charger_ctx_ids(args.racine, rapport)
        ids = verifier_kb(args.racine, args.perimetre, rapport)
        if rapport.ok:
            print(f"valider.py : base de référence {args.perimetre} valide ({len(ids)} entrées)")
            return 0
        print(f"valider.py : {len(rapport.erreurs)} erreur(s) dans la base {args.perimetre}", file=sys.stderr)
        for e in rapport.erreurs[:200]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    contexte = args.contexte or (args.racine / "CONTEXTE.md")
    rapport = valider(args.perimetre, args.racine, args.date, args.brut, contexte)
    if rapport.ok:
        print(f"valider.py : {args.perimetre} valide")
        return 0
    print(f"valider.py : {len(rapport.erreurs)} erreur(s) pour {args.perimetre}", file=sys.stderr)
    for e in rapport.erreurs:
        print(f"  - {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
