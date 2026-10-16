"""D128 : provenance des fiches qui recommandent (D127) reprise en masse en mode Batch, par les crédits API (A1).

Un lot = un dossier `raw/provenance-lots/<lot>/` (ignoré par git) :
- `requetes.jsonl` : une requête Message Batches par fiche (`{custom_id, params}`), sortie JSON contrainte ;
- `manifeste.json` : périmètre, modèle, usage A1, et par fiche ce qui a été lu (empreinte de `usage` et de
  `description_source`, jour de lecture de la page en cache, URL, sections de CONTEXTE.md et essais autorisés) ;
- `soumission.json` puis `resultats.jsonl` (format des résultats Batch) ; `bilan.json` après application.

Aucune date devinée : `releve_le` est posé par ce module, jamais par le modèle, au jour où la page de documentation a été
récupérée (`raw/kb/<produit>/empreintes.json`, `recupere_le`) ; une fiche dont la page n'a pas de jour de lecture, dont la
documentation en cache ne correspond plus à la fiche, ou dont une section citée a changé, n'est pas envoyée.
Une affirmation ne peut citer que ce qui a été envoyé : l'URL de la fiche (ancre permise), une section citée par la fiche,
un essai déclaré pour elle. Le modèle peut dire que la recommandation ne tient pas : la fiche n'est pas touchée, elle est
listée pour le lot `perimees` ou une révision complète (la recommandation n'est jamais changée par ce module).

Garde-fous : un seul lot en cours à la fois ; premier lot limité à PREMIER_LOT_MAX fiches ; aucun lot suivant tant que la
suite n'a pas été autorisée (`autoriser`, après présentation du coût du premier lot à Sylvain par Delta-pilote).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path

from ..contexte import ContexteInvalide, analyser
from . import catalogue as cat
from .documentation import charger_documentation

PREMIER_LOT_MAX = 10
MODELE_DEFAUT = "claude-opus-5-5"
EFFORT_DEFAUT = "medium"
MAX_TOKENS = 16000
USAGE_A1 = "delta-ia-provenance"  # nom d'usage du compteur commun (A1) : un seul usage, la dépense par lot vient du bilan
DOSSIER = Path("raw") / "provenance-lots"
AUTORISATION = "autorisation.json"
STATUTS = ("prepare", "soumis", "releve", "applique", "abandonne")
EN_COURS = ("prepare", "soumis", "releve")

SYSTEME = """Tu établis la provenance d'une fiche de la base de référence Delta (D127). La fiche recommande un outil à \
Sylvain (verdict `utiliser` ou `tester`, avec son `pourquoi`). Tu ne refais pas le jugement : tu écris les affirmations \
qui fondent cette recommandation, chacune rattachée à une source fournie.

Règles :
- 1 à 8 affirmations ; chacune vérifiable dans UNE source fournie, 300 caractères au plus, en français, factuelle ; noms \
de commandes, d'options et de produits en version originale.
- `source` est exactement l'une des valeurs de `sources_permises` : l'URL de la documentation (une ancre `#…` de cette \
page est permise), `contexte:<ctx-id>` ou `essai:<id>`. Une affirmation sur l'outil vient de l'extrait de documentation \
(`usage`, `description_source`) ; une affirmation sur Sylvain, ses projets ou ses habitudes vient du texte de la section \
de CONTEXTE.md citée. N'affirme rien qui ne soit pas écrit dans la source citée ; aucun chiffre, aucune version, aucune \
date absents de la source.
- `caduc_si` (200 caractères au plus) : l'événement précis qui rendrait l'affirmation fausse (« la commande change de \
syntaxe ou disparaît de la documentation », « CONTEXTE.md ne décrit plus ce projet »).
- Si les sources fournies ne fondent pas la recommandation (outil retiré, projet absent, pourquoi contredit par la \
source), réponds `recommandation_tient: false`, explique-le dans `motif` (une phrase) et laisse `provenance` vide.
- Sinon `recommandation_tient: true` et `motif` vide.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "recommandation_tient": {"type": "boolean"},
        "motif": {"type": "string"},
        "provenance": {"type": "array", "items": {
            "type": "object",
            "properties": {"affirmation": {"type": "string"}, "source": {"type": "string"}, "caduc_si": {"type": "string"}},
            "required": ["affirmation", "source", "caduc_si"],
            "additionalProperties": False,
        }},
    },
    "required": ["recommandation_tient", "motif", "provenance"],
    "additionalProperties": False,
}


class LotRefuse(Exception):
    """Garde-fou : le lot ne peut pas être préparé, soumis ou appliqué (message pour Sylvain ou Delta-pilote)."""


def _sha(texte) -> str:
    return hashlib.sha1(str(texte or "").encode("utf-8")).hexdigest()


def dossier(racine: Path) -> Path:
    return racine / DOSSIER


def lots(racine: Path) -> list[dict]:
    """Manifestes des lots, du plus ancien au plus récent (le nom du lot commence par son horodatage)."""
    d = dossier(racine)
    res = []
    for m in sorted(d.glob("*/manifeste.json")) if d.exists() else []:
        res.append(json.loads(m.read_text(encoding="utf-8")))
    return res


def ecrire_manifeste(racine: Path, manifeste: dict) -> None:
    p = dossier(racine) / manifeste["lot"] / "manifeste.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def autorisation(racine: Path) -> dict | None:
    p = dossier(racine) / AUTORISATION
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def autoriser(racine: Path, par: str, jour: str | None = None) -> dict:
    """Suite autorisée après présentation du coût du premier lot (Delta-pilote, accord de Sylvain)."""
    appliques = [m for m in lots(racine) if m["statut"] == "applique"]
    if not appliques:
        raise LotRefuse("aucun lot appliqué : le coût du premier lot n'a pas encore été mesuré")
    if not par.strip():
        raise LotRefuse("`--par` : qui autorise (ex. « Sylvain via Delta-pilote, 17/10 »)")
    a = {"date": jour or date.today().isoformat(), "par": par.strip(), "premier_lot": appliques[0]["lot"],
         "cout_premier_lot": appliques[0].get("bilan", {}).get("cout")}
    p = dossier(racine) / AUTORISATION
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return a


# ----------------------------------------------------------------------------------------------- lecture des sources

def textes_contexte(texte: str) -> dict[str, str]:
    """{ctx-id: corps de la section} (même découpage que `contexte.analyser`, qui valide d'abord le fichier)."""
    analyser(texte)
    lignes = texte.splitlines()
    titres = [i for i, l in enumerate(lignes) if re.match(r"^#{1,3}\s+\S", l)]
    res = {}
    for k, i in enumerate(titres):
        fin = titres[k + 1] if k + 1 < len(titres) else len(lignes)
        corps = lignes[i + 1:fin]
        m = next((re.match(r"^\s*<!--\s*ctx-id:\s*([A-Za-z0-9._-]+)\s*-->\s*$", l) for l in corps if l.strip()), None)
        if m:
            res[m.group(1)] = "\n".join(l.rstrip() for l in corps if not re.match(r"^\s*<!--\s*ctx-id(-deprecie)?:", l)).strip()
    return res


def _url_sans_ancre(u: str) -> str:
    u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return u[:-3] if u.endswith(".md") else u


def jour_de_lecture(racine: Path, e: dict) -> str | None:
    """Jour où la page de la fiche a été récupérée (`recupere_le` de raw/kb/<produit>/empreintes.json) ; None si inconnu.
    Plusieurs fichiers pour la même documentation : celui de la page de la fiche, sinon le plus ancien (prudent)."""
    try:
        index = json.loads((racine / "raw" / "kb" / e["produit"] / "empreintes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cles = {k: v for k, v in index.items() if k.startswith(f"{e.get('origine')}/") and isinstance(v, dict) and v.get("recupere_le")}
    if not cles:
        return None
    urls = {_url_sans_ancre(s["url"]) for s in e.get("sources") or [] if s.get("url")}
    page = [v for v in cles.values() if _url_sans_ancre(str(v.get("url", ""))) in urls]
    choix = page or list(cles.values())
    jours = sorted(str(v["recupere_le"])[:10] for v in choix)
    return jours[0] if jours and cat._date_iso(jours[0]) else None


def extraction_courante(racine: Path, perimetre: str) -> dict:
    """{id: EntreeExtraite} extraites de la copie locale de la documentation (sans réseau)."""
    docs = [d for d in charger_documentation(racine / "sources.yaml") if d.perimetre == perimetre and d.active]
    extraites, _, _ = cat.extraire(racine, docs)
    return {x.id: x for x in extraites}


# ----------------------------------------------------------------------------------------------- préparation

def _motif_ecart(e: dict, x, jour_lu: str | None, sections: dict[str, str], sha_courants: dict[str, str]) -> str | None:
    if x is None:
        return "absente de la documentation en cache (lancer `fetch.py --kb`)"
    if x.usage != e.get("usage") or x.description_source != e.get("description_source"):
        return "documentation en cache différente de la fiche (`catalogue.py maj` d'abord)"
    if jour_lu is None:
        return "jour de lecture de la page inconnu (raw/kb/<produit>/empreintes.json)"
    for ctx, v in (e.get("contexte_sections") or {}).items():
        if ctx not in sections or sha_courants.get(ctx) != (v or {}).get("sha1"):
            return f"section {ctx} modifiée ou dépréciée (lot `perimees` d'abord)"
    return None


def requete(custom_id: str, e: dict, f: dict, sections: dict[str, str], essais: dict[str, dict], modele: str, effort: str) -> dict:
    fiche = {k: e.get(k) for k in ("id", "nom", "categorie", "usage", "description_source", "description", "recommandation", "exemple")}
    contenu = {
        "fiche": fiche,
        "sources_permises": f["urls"] + [f"contexte:{c}" for c in f["sections"]] + [f"essai:{i}" for i in f["essais"]],
        "contexte": {c: {"pourquoi_cite": (e["contexte_sections"][c] or {}).get("pourquoi"), "texte": sections[c]} for c in f["sections"]},
        "essais": {i: essais[i] for i in f["essais"]},
    }
    return {"custom_id": custom_id, "params": {
        "model": modele, "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEME, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": json.dumps(contenu, ensure_ascii=False, indent=1)}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    }}


def preparer(racine: Path, perimetre: str, maximum: int | None = None, modele: str = MODELE_DEFAUT, effort: str = EFFORT_DEFAUT,
             horodatage: str | None = None, extraites: dict | None = None) -> dict:
    """Prépare un lot : `requetes.jsonl` et `manifeste.json`. Refuse (LotRefuse) un lot en cours, un lot suivant non autorisé,
    un premier lot de plus de PREMIER_LOT_MAX fiches."""
    tous = lots(racine)
    en_cours = [m["lot"] for m in tous if m["statut"] in EN_COURS]
    if en_cours:
        raise LotRefuse(f"lot en cours : {', '.join(en_cours)} (le relever et l'appliquer d'abord, ou `abandonner`)")
    premier = not any(m["statut"] == "applique" for m in tous)
    if premier:
        maximum = min(maximum or PREMIER_LOT_MAX, PREMIER_LOT_MAX)
    elif autorisation(racine) is None:
        raise LotRefuse("premier lot appliqué : son coût est présenté à Sylvain par Delta-pilote avant la suite "
                        "(`provenance_lot.py autoriser --par …` une fois l'accord donné)")
    if maximum is not None and maximum < 1:
        raise LotRefuse("`--max` doit valoir au moins 1")
    entrees = cat.charger(racine, perimetre)
    try:
        texte_ctx = (racine / "CONTEXTE.md").read_text(encoding="utf-8")
        sha_courants = {k: v["sha1"] for k, v in analyser(texte_ctx)[0].items()}
        sections = textes_contexte(texte_ctx)
    except (OSError, ContexteInvalide) as err:
        raise LotRefuse(f"CONTEXTE.md illisible ou invalide : {err}") from err
    try:
        essais = cat.lire_essais(racine)
    except ValueError as err:
        raise LotRefuse(str(err)) from err
    extraites = extraction_courante(racine, perimetre) if extraites is None else extraites
    jour = date.today().isoformat()
    horodatage = horodatage or time.strftime("%Y%m%d-%H%M%S")
    lot = f"{horodatage}-{perimetre}"
    fiches, ecartees, requetes = {}, {}, []
    for k in cat.provenance_detail(entrees, maximum=None):
        if maximum is not None and len(fiches) >= maximum:
            break
        e = entrees[k]
        jour_lu = jour_de_lecture(racine, e)
        motif = _motif_ecart(e, extraites.get(k), jour_lu, sections, sha_courants)
        if motif:
            ecartees[k] = motif
            continue
        f = {"custom_id": f"f{len(fiches) + 1:04d}", "releve_le": min(jour_lu, jour),
             "urls": sorted({s["url"] for s in e.get("sources") or [] if str(s.get("url", "")).startswith(("http://", "https://"))}),
             "sections": sorted(e.get("contexte_sections") or {}), "essais": [k] if k in essais else [],
             "usage_sha": _sha(e.get("usage")), "description_sha": _sha(e.get("description_source")),
             "recommandation": e.get("recommandation")}
        if not f["urls"]:
            ecartees[k] = "aucune URL de documentation sur la fiche"
            continue
        fiches[k] = f
        requetes.append(requete(f["custom_id"], e, f, sections, essais, modele, effort))
    if not requetes:
        raise LotRefuse("aucune fiche à envoyer" + (f" ({len(ecartees)} écartées : {next(iter(ecartees.values()))} …)" if ecartees else ""))
    manifeste = {"lot": lot, "perimetre": perimetre, "cree_le": jour, "statut": "prepare", "premier": premier, "modele": modele,
                 "effort": effort, "usage": USAGE_A1, "fiches": fiches, "ecartees": ecartees}
    d = dossier(racine) / lot
    d.mkdir(parents=True, exist_ok=True)
    (d / "requetes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requetes), encoding="utf-8")
    ecrire_manifeste(racine, manifeste)
    return manifeste


def charger_requetes(racine: Path, manifeste: dict) -> list[dict]:
    p = dossier(racine) / manifeste["lot"] / "requetes.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def lot_courant(racine: Path) -> dict:
    en_cours = [m for m in lots(racine) if m["statut"] in EN_COURS]
    if not en_cours:
        raise LotRefuse("aucun lot en cours (`provenance_lot.py preparer` d'abord)")
    return en_cours[-1]


# ----------------------------------------------------------------------------------------------- résultats

def _en_dict(r) -> dict:
    for m in ("model_dump", "to_dict"):
        if hasattr(r, m):
            return getattr(r, m)()
    return r


def ecrire_resultats(racine: Path, manifeste: dict, resultats) -> Path:
    p = dossier(racine) / manifeste["lot"] / "resultats.jsonl"
    p.write_text("".join(json.dumps(_en_dict(r), ensure_ascii=False) + "\n" for r in resultats), encoding="utf-8")
    return p


def _source_permise(src: str, f: dict) -> bool:
    if src.startswith(("http://", "https://")):
        return _url_sans_ancre(src) in {_url_sans_ancre(u) for u in f["urls"]}
    if src.startswith("contexte:"):
        return src[len("contexte:"):] in f["sections"]
    if src.startswith("essai:"):
        return src[len("essai:"):] in f["essais"]
    return False


def analyser_resultats(manifeste: dict, resultats: list[dict]) -> dict:
    """Résultats Batch -> {provenances: {id: [...]}, a_revoir: {id: motif}, rejets: {id: motif}, jetons: {...}, compte: {...}}.
    `releve_le` est celui du manifeste ; une affirmation hors des sources envoyées rejette la fiche entière."""
    par_custom = {f["custom_id"]: k for k, f in manifeste["fiches"].items()}
    jetons = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    provenances, a_revoir, rejets = {}, {}, {}
    compte = {"succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}
    vus = set()
    for r in map(_en_dict, resultats):
        k = par_custom.get(r.get("custom_id"))
        if k is None or k in vus:
            continue
        vus.add(k)
        res = r.get("result") or {}
        t = res.get("type")
        compte[t] = compte.get(t, 0) + 1
        if t != "succeeded":
            rejets[k] = f"requête {t}"
            continue
        msg = res.get("message") or {}
        for c in jetons:
            jetons[c] += int((msg.get("usage") or {}).get(c) or 0)
        if msg.get("stop_reason") not in ("end_turn", "stop_sequence"):
            rejets[k] = f"réponse arrêtée ({msg.get('stop_reason')})"
            continue
        texte = next((b.get("text") for b in msg.get("content") or [] if b.get("type") == "text"), None)
        try:
            sortie = json.loads(texte or "")
            assert isinstance(sortie, dict) and isinstance(sortie.get("provenance"), list)
        except (ValueError, AssertionError):
            rejets[k] = "sortie JSON illisible"
            continue
        if sortie.get("recommandation_tient") is not True:
            a_revoir[k] = str(sortie.get("motif") or "recommandation non fondée par les sources").strip()[:300]
            continue
        f = manifeste["fiches"][k]
        prov = [{"affirmation": str(a.get("affirmation", "")).strip(), "source": str(a.get("source", "")).strip(),
                 "releve_le": f["releve_le"], "caduc_si": str(a.get("caduc_si", "")).strip()}
                for a in sortie["provenance"] if isinstance(a, dict)]
        hors = [a["source"] for a in prov if not _source_permise(a["source"], f)]
        if hors:
            rejets[k] = f"source non envoyée : {hors[0]}"
            continue
        msg_err = cat.verifier_provenance(prov, set(f["sections"]), None, set(f["essais"]))
        if msg_err:
            rejets[k] = msg_err
            continue
        provenances[k] = prov
    for k in manifeste["fiches"]:
        if k not in vus:
            rejets[k] = "aucun résultat"
    return {"provenances": provenances, "a_revoir": a_revoir, "rejets": rejets, "jetons": jetons, "compte": compte}


def appliquer(racine: Path, manifeste: dict, resultats: list[dict], jour: str | None = None, ecrire: bool = True) -> dict:
    """Pose les provenances valides par `catalogue.appliquer_commentaires` ({id: {provenance}} seuls : historique
    « provenance ajoutée »). Une fiche modifiée depuis la préparation (usage, description, recommandation, section citée)
    ou déjà pourvue est sautée. Rend le bilan (aussi écrit dans le manifeste)."""
    jour = jour or date.today().isoformat()
    a = analyser_resultats(manifeste, resultats)
    entrees = cat.charger(racine, manifeste["perimetre"])
    try:
        sha_courants = {k: v["sha1"] for k, v in analyser((racine / "CONTEXTE.md").read_text(encoding="utf-8"))[0].items()}
    except (OSError, ContexteInvalide) as err:
        raise LotRefuse(f"CONTEXTE.md illisible ou invalide : {err}") from err
    sautees, commentaires = {}, {}
    for k, prov in a["provenances"].items():
        e, f = entrees.get(k), manifeste["fiches"][k]
        if e is None or not cat.provenance_due(e):
            sautees[k] = "plus due (provenance déjà posée, verdict changé ou fiche retirée)"
        elif _sha(e.get("usage")) != f["usage_sha"] or _sha(e.get("description_source")) != f["description_sha"]:
            sautees[k] = "documentation modifiée depuis la préparation"
        elif e.get("recommandation") != f["recommandation"] or sorted(e.get("contexte_sections") or {}) != f["sections"]:
            sautees[k] = "recommandation révisée depuis la préparation"
        elif any(sha_courants.get(c) != (e["contexte_sections"][c] or {}).get("sha1") for c in f["sections"]):
            sautees[k] = "section de CONTEXTE.md modifiée depuis la préparation"
        else:
            commentaires[k] = {"provenance": prov}
    erreurs = []
    if commentaires:
        try:
            essais = set(cat.lire_essais(racine))
        except ValueError:
            essais = None
        erreurs = cat.appliquer_commentaires(entrees, commentaires, jour=jour, essais=essais, exiger_provenance=True)
        if erreurs:
            raise LotRefuse("rien n'est écrit : " + " ; ".join(erreurs[:3]))
        if ecrire:
            cat.ecrire(racine, manifeste["perimetre"], entrees)
    bilan = {"applique_le": jour, "posees": sorted(commentaires), "a_revoir": a["a_revoir"], "rejets": a["rejets"],
             "sautees": sautees, "jetons": a["jetons"], "compte": a["compte"], "cout": manifeste.get("cout")}
    if ecrire:
        manifeste["statut"], manifeste["bilan"] = "applique", bilan
        ecrire_manifeste(racine, manifeste)
    return bilan


def ligne_bilan(manifeste: dict) -> str:
    """Une ligne pour Delta-pilote : lot, fiches posées / envoyées, jetons, coût mesuré par A1."""
    b = manifeste.get("bilan") or {}
    j = b.get("jetons") or {}
    c = b.get("cout")
    cout = f"{c['usd']:.4f} $ (A1, {c['source']})" if isinstance(c, dict) and isinstance(c.get("usd"), (int, float)) else "coût non mesuré"
    return (f"{manifeste['lot']} : {len(b.get('posees', []))}/{len(manifeste['fiches'])} provenances posées, "
            f"{len(b.get('a_revoir', {}))} à revoir, {len(b.get('rejets', {}))} rejetées, {len(b.get('sautees', {}))} sautées ; "
            f"jetons entrée {j.get('input_tokens', 0)}, sortie {j.get('output_tokens', 0)}, cache écrit "
            f"{j.get('cache_creation_input_tokens', 0)}, lu {j.get('cache_read_input_tokens', 0)} ; {cout} ; modèle {manifeste['modele']}")
