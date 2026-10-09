"""D114 : index de recherche de la veille, sans modèle. Une ligne par élément des fichiers quotidiens publiés des trois
périmètres, écrite dans `docs/data/recherche.json`, pour que le site retrouve un mot dans `titre`, `resume`, `pour_toi` et
`action` sans charger chaque jour. Aucune phrase n'est rédigée : chaque valeur est recopiée de sa source, espaces réduits,
coupée à une longueur fixe. Fichier illisible : `statut: echec` et la raison, jamais une liste vide muette."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from .dates import maintenant_iso

PERIMETRES = ("claude", "actu", "openai")
FICHIER = Path("docs") / "data" / "recherche.json"
# longueur maximale de chaque champ recopié dans `texte` (le titre n'est pas coupé : il est court) ; le texte entier fait
# donc au plus 600 + 400 + 300 + 2 séparateurs de 3 caractères
MAX_RESUME, MAX_POUR_TOI, MAX_ACTION = 600, 400, 300
MAX_TEXTE = MAX_RESUME + MAX_POUR_TOI + MAX_ACTION + 2 * 3
SEPARATEUR = " · "
CHAMPS = {"genere_le", "statut", "raison", "sources", "total", "elements"}
CHAMPS_ELEMENT = {"id", "date", "perimetre", "titre", "impact", "texte"}
RE_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")


def _lire_json(chemin: Path):
    return json.loads(chemin.read_text(encoding="utf-8"))


def _propre(v) -> str:
    """Texte recopié : NFC, espaces (retours à la ligne compris) réduits à un seul, vide si ce n'est pas une chaîne."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", v)).strip() if isinstance(v, str) else ""


def _coupe(s: str, maximum: int) -> str:
    """Coupe à `maximum` caractères au plus, sur une limite de mot, avec « … » ; `s` est rendu tel quel s'il tient."""
    if len(s) <= maximum:
        return s
    court = s[: maximum - 1]
    if " " in court and not s[maximum - 1].isspace():
        court = court.rsplit(" ", 1)[0]
    return court.rstrip(" ,;:.") + "…"


def _description_action(action) -> str:
    return _propre(action.get("description") if isinstance(action, dict) else action)


def ligne(perimetre: str, jour: str, e: dict) -> dict:
    morceaux = [_coupe(_propre(e.get("resume")), MAX_RESUME), _coupe(_propre(e.get("pour_toi")), MAX_POUR_TOI),
                _coupe(_description_action(e.get("action")), MAX_ACTION)]
    impact = e.get("impact")
    return {"id": e["id"], "date": jour, "perimetre": perimetre, "titre": _propre(e.get("titre")),
            "impact": impact if isinstance(impact, str) else None, "texte": SEPARATEUR.join(m for m in morceaux if m)}


def _cle(l: dict):
    return (l["date"], l["perimetre"], l["id"])


def construire(racine: Path, maintenant: str | None = None) -> dict:
    sources = {p: {"statut": "ok", "raison": None, "jours": []} for p in PERIMETRES}
    lignes: list[dict] = []
    for p in PERIMETRES:
        s = sources[p]
        for f in sorted((racine / "docs" / "data" / p).glob("????-??-??.json")):
            if not RE_JOUR.fullmatch(f.stem):
                continue
            try:
                date.fromisoformat(f.stem)
                q = _lire_json(f)
                if not isinstance(q, dict) or not isinstance(q.get("elements"), list):
                    raise ValueError("clé `elements` absente ou invalide")
                valides = [e for e in q["elements"] if isinstance(e, dict) and isinstance(e.get("id"), str)]
            except (OSError, ValueError) as err:
                s["statut"] = "echec"
                raison = f"{p}/{f.name} illisible : {err}"
                s["raison"] = f"{s['raison']} ; {raison}" if s["raison"] else raison
                continue
            s["jours"].append(f.stem)
            lignes.extend(ligne(p, f.stem, e) for e in valides)
    lignes.sort(key=_cle, reverse=True)  # date décroissante, puis périmètre et id (ordre stable)
    pannes = [f"{nom} : {s['raison']}" for nom, s in sources.items() if s["statut"] != "ok"]
    return {"genere_le": maintenant or maintenant_iso(), "statut": "echec" if pannes else "ok",
            "raison": " | ".join(pannes) if pannes else None, "sources": sources, "total": len(lignes), "elements": lignes}


def _sans_horodatage(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "genere_le"}


def ecrire(racine: Path, doc: dict) -> bool:
    """Écrit `recherche.json` (JSON compact : le fichier est lu par le navigateur, pas par un humain). Vrai si le fichier a
    changé ; un contenu identique (hors `genere_le`) n'est pas réécrit."""
    chemin = racine / FICHIER
    if chemin.exists():
        try:
            if _sans_horodatage(_lire_json(chemin)) == _sans_horodatage(doc):
                return False
        except (OSError, ValueError):
            pass  # fichier existant illisible : repris à zéro
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(chemin)
    return True
