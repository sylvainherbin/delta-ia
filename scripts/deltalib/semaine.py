"""D98 : bilan de la semaine ISO, sans modèle. Rassemble des champs déjà publiés (fichiers quotidiens des trois périmètres,
base de référence et son journal de réévaluations) dans `docs/data/semaine/AAAA-Www.json`, plus l'index `index.json`.
Aucune phrase n'est rédigée : chaque valeur est recopiée de sa source. Source illisible : `statut: echec` et la raison,
jamais une liste vide muette."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from .dates import maintenant_iso
from .kb.catalogue import date_ajout
from .sujet_d71 import mots_trouves_element

PERIMETRES_JOURS = ("claude", "actu", "openai")
PERIMETRES_KB = ("claude", "openai")
IMPACTS_RETENUS = ("fort", "moyen")  # bloc (a) ; le bloc D71 prend tout élément d'impact autre que `nul`
VERDICTS_UTILES = ("utiliser", "tester")
RANG_IMPACT = {"fort": 0, "moyen": 1, "faible": 2, "nul": 3}
RANG_VERDICT = {"utiliser": 0, "tester": 1, "ignorer": 2}
RE_SEMAINE = re.compile(r"(\d{4})-W(\d{2})")
RE_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
DOSSIER = Path("docs") / "data" / "semaine"


class SemaineInvalide(ValueError):
    pass


def semaine_de(jour: date) -> str:
    iso = jour.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def bornes(semaine: str) -> tuple[date, date]:
    """Lundi et dimanche de la semaine ISO `AAAA-Www`."""
    m = RE_SEMAINE.fullmatch(semaine or "")
    if not m:
        raise SemaineInvalide(f"semaine attendue au format AAAA-Www (reçu : {semaine!r})")
    try:
        lundi = date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError as e:
        raise SemaineInvalide(f"semaine ISO inexistante : {semaine} ({e})") from e
    return lundi, lundi + timedelta(days=6)


def _lire_json(chemin: Path):
    return json.loads(chemin.read_text(encoding="utf-8"))


def _texte(v) -> str | None:
    return v if isinstance(v, str) and v.strip() else None


def _description_action(action) -> str | None:
    """`action.description` recopiée telle quelle (aucun résumé rédigé) ; une action en texte simple est reprise."""
    if isinstance(action, dict):
        return _texte(action.get("description"))
    return _texte(action)


def _ligne_element(perimetre: str, jour: str, e: dict) -> dict:
    return {
        "perimetre": perimetre, "id": e["id"], "produit": _texte(e.get("produit")), "titre": _texte(e.get("titre")),
        "version": _texte(e.get("version")), "impact": e.get("impact"), "certitude": _texte(e.get("certitude")),
        "date_publication": _texte(e.get("date_publication")), "jour": jour, "action": _description_action(e.get("action")),
    }


def _cle_element(l: dict):
    return (RANG_IMPACT.get(l["impact"], 9), _inverse(l["jour"]), l["perimetre"], l["id"])


def _inverse(texte: str) -> tuple:
    return tuple(-ord(c) for c in texte)  # tri décroissant sur une chaîne, à rang égal


def _elements_de_la_semaine(racine: Path, du: date, au: date, source: dict, perimetre: str) -> list[dict]:
    """Éléments des fichiers quotidiens du périmètre dans la semaine ; un id repris plusieurs jours garde sa version la plus récente."""
    dossier = racine / "docs" / "data" / perimetre
    retenus: dict[str, dict] = {}
    for f in sorted(dossier.glob("????-??-??.json")):
        if not RE_JOUR.fullmatch(f.stem):
            continue
        try:
            jour = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if not du <= jour <= au:
            continue
        try:
            q = _lire_json(f)
            if not isinstance(q, dict) or not isinstance(q.get("elements"), list):
                raise ValueError("clé `elements` absente ou invalide")
            valides = [e for e in q["elements"] if isinstance(e, dict) and isinstance(e.get("id"), str)]
        except (OSError, ValueError) as err:
            _echec(source, f"{perimetre}/{f.name} illisible : {err}")
            continue
        source["jours"].append(f.stem)
        for e in valides:  # fichiers lus par date croissante : la version du jour le plus récent l'emporte
            l = _ligne_element(perimetre, f.stem, e)
            l["_d71"] = bool(mots_trouves_element(_texte(e.get("titre")), _texte(e.get("resume"))))
            retenus[l["id"]] = l
    return list(retenus.values())


def _echec(source: dict, raison: str) -> None:
    source["statut"] = "echec"
    source["raison"] = f"{source['raison']} ; {raison}" if source.get("raison") else raison


def _source_vide() -> dict:
    return {"statut": "ok", "raison": None, "jours": []}


def _entrees_kb(racine: Path, perimetre: str, source: dict) -> dict[str, dict]:
    entrees: dict[str, dict] = {}
    dossier = racine / "docs" / "data" / "kb" / perimetre
    for f in sorted(dossier.glob("*.json")):
        try:
            d = _lire_json(f)
            liste = d.get("entrees") if isinstance(d, dict) else None
            if not isinstance(liste, list):
                raise ValueError("clé `entrees` absente ou invalide")
        except (OSError, ValueError) as err:
            _echec(source, f"kb/{perimetre}/{f.name} illisible : {err}")
            continue
        source["jours"].append(f.stem)  # catégories lues
        for e in liste:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                entrees[e["id"]] = e
    return entrees


def _journal(racine: Path, perimetre: str, source: dict) -> list[dict]:
    chemin = racine / "docs" / "data" / "kb" / perimetre / "reevaluations.jsonl"
    if not chemin.exists():
        return []
    lignes = []
    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError as err:
        _echec(source, f"kb/{perimetre}/reevaluations.jsonl illisible : {err}")
        return []
    for n, brut in enumerate(texte.splitlines(), 1):
        if not brut.strip():
            continue
        try:
            l = json.loads(brut)
            if not (isinstance(l, dict) and isinstance(l.get("id"), str) and isinstance(l.get("date"), str)):
                raise ValueError("ligne sans id ou date")
        except ValueError as err:
            _echec(source, f"kb/{perimetre}/reevaluations.jsonl ligne {n} illisible : {err}")
            continue
        lignes.append(l)
    return lignes


def _ligne_kb(perimetre: str, e: dict) -> dict:
    reco = e.get("recommandation") if isinstance(e.get("recommandation"), dict) else {}
    return {
        "perimetre": perimetre, "id": e["id"], "produit": _texte(e.get("produit")), "categorie": _texte(e.get("categorie")),
        "nom": _texte(e.get("nom")), "usage": _texte(e.get("usage")), "exemple": _texte(e.get("exemple")),
        "exemple_origine": _texte(e.get("exemple_origine")), "verdict": _texte(reco.get("verdict")),
    }


def _cle_kb(l: dict):
    return (RANG_VERDICT.get(l.get("verdict_apres", l.get("verdict")), 9), l["perimetre"], l.get("categorie") or "", (l.get("nom") or "").lower(), l["id"])


def _date_commentee(e: dict) -> str | None:
    dates = [h["date"] for h in e.get("historique", []) if isinstance(h, dict) and h.get("changement") == "commentée"
             and isinstance(h.get("date"), str) and RE_JOUR.fullmatch(h["date"])]
    return min(dates) if dates else None


def construire(racine: Path, semaine: str, maintenant: str | None = None) -> dict:
    du, au = bornes(semaine)
    sources = {p: _source_vide() for p in (*PERIMETRES_JOURS, *(f"kb-{p}" for p in PERIMETRES_KB))}
    d71: list[dict] = []
    elements: list[dict] = []
    for p in PERIMETRES_JOURS:
        for l in _elements_de_la_semaine(racine, du, au, sources[p], p):
            drapeau = l.pop("_d71")
            if drapeau and l["impact"] != "nul":
                d71.append(l)
            elif l["impact"] in IMPACTS_RETENUS:
                elements.append(l)
    d71.sort(key=_cle_element)
    elements.sort(key=_cle_element)

    ajoutees: list[dict] = []
    verdicts: list[dict] = []
    jd, jf = du.isoformat(), au.isoformat()
    for p in PERIMETRES_KB:
        source = sources[f"kb-{p}"]
        entrees = _entrees_kb(racine, p, source)
        ids_ajoutes = set()
        for e in entrees.values():
            a = date_ajout(e)
            if a and jd <= a <= jf:
                ids_ajoutes.add(e["id"])
                ajoutees.append({**_ligne_kb(p, e), "date_ajout": a})
        dernier: dict[str, dict] = {}
        for l in _journal(racine, p, source):  # fichier en ordre chronologique : la dernière ligne de la semaine l'emporte
            if jd <= l["date"] <= jf and l.get("verdict_avant") != l.get("verdict_apres"):
                dernier[l["id"]] = l
        for i, l in dernier.items():
            e = entrees.get(i)
            if e is None or i in ids_ajoutes or l.get("verdict_apres") not in VERDICTS_UTILES:
                continue
            reco = e.get("recommandation") if isinstance(e.get("recommandation"), dict) else {}
            verdicts.append({**_ligne_kb(p, e), "date": l["date"], "verdict_avant": l.get("verdict_avant"),
                             "verdict_apres": l["verdict_apres"], "pourquoi": _texte(reco.get("pourquoi"))})
        for e in entrees.values():  # premier jugement de la semaine sur une entrée plus ancienne, sans ligne de changement
            c = _date_commentee(e)
            reco = e.get("recommandation") if isinstance(e.get("recommandation"), dict) else {}
            if c and jd <= c <= jf and e["id"] not in ids_ajoutes and e["id"] not in dernier \
                    and reco.get("verdict") in VERDICTS_UTILES and not any(v["id"] == e["id"] for v in verdicts):
                verdicts.append({**_ligne_kb(p, e), "date": c, "verdict_avant": None,
                                 "verdict_apres": reco["verdict"], "pourquoi": _texte(reco.get("pourquoi"))})
    ajoutees.sort(key=lambda l: (RANG_VERDICT.get(l["verdict"], 9), _inverse(l["date_ajout"]), l["perimetre"], l["categorie"] or "", (l["nom"] or "").lower(), l["id"]))
    verdicts.sort(key=lambda l: (RANG_VERDICT.get(l["verdict_apres"], 9), _inverse(l["date"]), l["perimetre"], l["categorie"] or "", (l["nom"] or "").lower(), l["id"]))

    for s in sources.values():
        s["jours"].sort()
    pannes = [f"{nom} : {s['raison']}" for nom, s in sources.items() if s["statut"] != "ok"]
    return {
        "semaine": semaine, "du": jd, "au": jf, "genere_le": maintenant or maintenant_iso(),
        "statut": "echec" if pannes else "ok", "raison": " | ".join(pannes) if pannes else None,
        "sources": sources, "d71": d71, "elements": elements, "base_ajoutees": ajoutees, "base_verdicts": verdicts,
    }


def _sans_horodatage(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "genere_le"}


def _ecrire_json(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(chemin)


def ecrire(racine: Path, doc: dict) -> bool:
    """Écrit `AAAA-Www.json` puis l'index. Vrai si le fichier a changé ; un contenu identique (hors `genere_le`) n'est pas réécrit."""
    chemin = racine / DOSSIER / f"{doc['semaine']}.json"
    if chemin.exists():
        try:
            if _sans_horodatage(_lire_json(chemin)) == _sans_horodatage(doc):
                reconstruire_index(racine)
                return False
        except (OSError, ValueError):
            pass  # fichier existant illisible : repris à zéro
    _ecrire_json(chemin, doc)
    reconstruire_index(racine)
    return True


def reconstruire_index(racine: Path) -> dict:
    """Index léger de `docs/data/semaine/` : une entrée par fichier `AAAA-Www.json` lisible, la plus récente d'abord."""
    dossier = racine / DOSSIER
    semaines = []
    for f in sorted(dossier.glob("????-W??.json")):
        try:
            d = _lire_json(f)
            bornes(d["semaine"])
            semaines.append({
                "semaine": d["semaine"], "du": d["du"], "au": d["au"], "genere_le": d.get("genere_le"), "statut": d["statut"],
                "d71": len(d["d71"]), "elements": len(d["elements"]),
                "base_ajoutees": len(d["base_ajoutees"]), "base_verdicts": len(d["base_verdicts"]),
            })
        except (OSError, ValueError, KeyError, TypeError):
            continue  # fichier illisible : absent de l'index (valider.py le signale)
    semaines.sort(key=lambda s: s["semaine"], reverse=True)
    index = {"maj_le": max((s["genere_le"] for s in semaines if s["genere_le"]), default=None), "semaines": semaines}
    chemin = dossier / "index.json"
    if chemin.exists():
        try:
            if _lire_json(chemin) == index:
                return index
        except (OSError, ValueError):
            pass
    _ecrire_json(chemin, index)
    return index
