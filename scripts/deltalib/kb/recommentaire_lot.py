"""Recommentaire en Batch des fiches que la provenance D128 a laissées « à revoir » (mission m-b0809e258011).

Le modèle a dit, au lot de provenance, que les sources envoyées ne fondaient pas la recommandation (souvent une fiche ancienne à
`contexte_sections` vide dont le `pourquoi` cite des faits personnels). Ici il refait le commentaire complet, conforme à
`catalogue.py appliquer` : description, recommandation {verdict, pourquoi}, contexte_sections {ctx-id: pourquoi} et provenance.
Le verdict peut changer (`ignorer` si rien ne fonde la recommandation).

Même cycle et même pont A1 que provenance_lot (`soumettre_lot` / `relever_lot`), usage `delta-ia-recommentaire`, lots dans
raw/recommentaire-lots/<lot>/ (manifeste.json porte `dossier`). Envoyé par fiche : la fiche, sa documentation en cache
(`usage`, `description_source`, URL), le motif « à revoir », les essais déclarés ; CONTEXTE.md entier (sections non vides,
par ctx-id) est dans la consigne commune, mise en cache. Le modèle choisit les sections qui fondent le jugement.

Garde-fous mécaniques (en plus de ceux de `appliquer_commentaires`) :
- une affirmation ne cite que l'URL de la fiche (ancre permise), une section qu'elle cite dans `contexte_sections`, un essai
  déclaré pour elle ; une section citée sans affirmation `contexte:<ctx-id>` rejette la fiche (verdict qui recommande) : aucun
  fait personnel sans section citée et étayée ;
- `releve_le` est posé ici : jour de lecture de la page pour une URL, jour de préparation pour CONTEXTE.md et les essais ;
- une fiche modifiée depuis la préparation (documentation, recommandation, provenance posée) ou dont une section citée a changé
  depuis l'envoi est sautée ;
- application fiche par fiche : une fiche refusée s'écarte seule avec son motif (D129), les autres sont écrites.
"""

from __future__ import annotations

import copy
import json
import time
from datetime import date
from pathlib import Path

from ..contexte import SHA1_VIDE, ContexteInvalide, analyser
from ..modeles import empreinte_contexte
from . import catalogue as cat
from . import provenance_lot as pl
from .modeles import VERDICTS

DOSSIER = Path("raw") / "recommentaire-lots"
USAGE_A1 = "delta-ia-recommentaire"
MAX_TOKENS = 16000
MOTIF_JOURNAL = "rejugement demandé (provenance D128 à revoir)"  # format admis par valider.py (RE_MOTIF)

SYSTEME = """Tu refais le commentaire d'une fiche de la base de référence Delta. La fiche décrit une commande, une option, \
un paramètre ou une fonctionnalité de Claude, Claude Code, ChatGPT ou Codex ; son commentaire dit à Sylvain s'il doit \
l'utiliser, la tester ou l'ignorer. Un premier contrôle (D128) a jugé que les sources ne fondaient pas la recommandation \
actuelle : son motif est fourni (`motif_a_revoir`). Tu repars des sources, pas de l'ancien commentaire.

Sources : la documentation de la fiche (`usage`, `description_source`, `urls`), les essais déclarés (`essais`) et \
CONTEXTE.md ci-dessous, découpé en sections par ctx-id. Rien d'autre : aucune connaissance extérieure sur Sylvain, ses \
projets, ses limites, ses outils ou ses habitudes.

Rendu :
- `description` : ce que fait l'élément, d'après la documentation, en français, 1 à 3 phrases ; noms de commandes, \
d'options et de produits en version originale ; aucun chiffre, version ou date absents de la source.
- `recommandation.verdict` : `utiliser`, `tester` ou `ignorer`. `utiliser` ou `tester` seulement si une section de \
CONTEXTE.md décrit un projet, un outil ou une habitude de Sylvain que l'élément sert concrètement ; une restriction \
écrite dans CONTEXTE.md (outil interdit, projet arrêté, autre outil retenu) l'emporte. Sinon `ignorer` : c'est une \
réponse normale, jamais un échec.
- `recommandation.pourquoi` : 1 à 3 phrases. Chaque fait personnel (projet, outil, habitude, limite, compte) qu'il nomme \
vient d'une section citée dans `contexte_sections`. Si aucune section ne le fonde, ne le nomme pas.
- `contexte_sections` : les sections qui fondent le jugement (ctx-id exact de la liste, section au contenu non vide), chacune \
avec un `pourquoi` d'une ligne, 160 caractères au plus. Liste vide si le jugement ne dépend d'aucune section.
- `provenance` (verdict `utiliser` ou `tester`) : 1 à 8 affirmations factuelles, 300 caractères au plus, chacune \
vérifiable dans UNE source : `source` = une URL de `urls` (ancre `#…` permise), `contexte:<ctx-id>` d'une section que tu \
cites dans `contexte_sections`, ou `essai:<id>` d'un essai fourni. Chaque section citée a au moins une affirmation \
`contexte:<ctx-id>`. `caduc_si` (200 caractères au plus) : l'événement précis qui rendrait l'affirmation fausse. \
Verdict `ignorer` : `provenance` vide.
- `raison` : une phrase, ce qui a changé par rapport à l'ancien commentaire et pourquoi.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "recommandation": {
            "type": "object",
            "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}, "pourquoi": {"type": "string"}},
            "required": ["verdict", "pourquoi"],
            "additionalProperties": False,
        },
        "contexte_sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"ctx_id": {"type": "string"}, "pourquoi": {"type": "string"}},
            "required": ["ctx_id", "pourquoi"],
            "additionalProperties": False,
        }},
        "provenance": pl.SCHEMA["properties"]["provenance"],
        "raison": {"type": "string"},
    },
    "required": ["description", "recommandation", "contexte_sections", "provenance", "raison"],
    "additionalProperties": False,
}


def lots(racine: Path) -> list[dict]:
    return pl.lots(racine, DOSSIER)


def lot_courant(racine: Path) -> dict:
    return pl.lot_courant(racine, DOSSIER)


def a_revoir(racine: Path, perimetre: str) -> dict[str, str]:
    """{id: motif} des fiches « à revoir » des lots de provenance appliqués (`bilan.a_revoir`), encore dues (toujours
    `utiliser` ou `tester`, sans provenance). Le motif du lot le plus récent l'emporte."""
    entrees = cat.charger(racine, perimetre)
    res = {}
    for m in pl.lots(racine):
        if m.get("perimetre") == perimetre:
            res.update((m.get("bilan") or {}).get("a_revoir") or {})
    return {k: v for k, v in res.items() if k in entrees and cat.provenance_due(entrees[k])}


def _sections_envoyees(texte_ctx: str) -> tuple[dict[str, str], dict[str, str]]:
    """({ctx-id: texte}, {ctx-id: sha1}) des sections courantes au contenu non vide (les seules citables)."""
    courantes = analyser(texte_ctx)[0]
    textes = pl.textes_contexte(texte_ctx)
    citables = {k for k, v in courantes.items() if v["sha1"] != SHA1_VIDE and k in textes}
    return {k: textes[k] for k in courantes if k in citables}, {k: courantes[k]["sha1"] for k in courantes if k in citables}


def systeme(sections: dict[str, str]) -> str:
    blocs = "\n\n".join(f"### contexte:{k}\n{t}" for k, t in sections.items())
    return f"{SYSTEME}\nCONTEXTE.md, sections citables :\n\n{blocs}\n"


def requete(custom_id: str, e: dict, f: dict, consigne: str, essais: dict[str, dict], modele: str, effort: str) -> dict:
    fiche = {k: e.get(k) for k in ("id", "produit", "nom", "categorie", "usage", "description_source", "description",
                                   "recommandation", "exemple")}
    fiche["contexte_sections_avant"] = {c: (v or {}).get("pourquoi") for c, v in (e.get("contexte_sections") or {}).items()}
    contenu = {"fiche": fiche, "motif_a_revoir": f["motif_a_revoir"], "urls": f["urls"],
               "essais": {i: essais[i] for i in f["essais"]}}
    return {"custom_id": custom_id, "params": {
        "model": modele, "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": consigne, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": json.dumps(contenu, ensure_ascii=False, indent=1)}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    }}


def _motif_ecart(e: dict | None, x, jour_lu: str | None) -> str | None:
    if e is None:
        return "identifiant inconnu dans la base"
    if not cat.provenance_due(e):
        return "plus due (provenance déjà posée, verdict changé ou fiche retirée)"
    if x is None:
        return "absente de la documentation en cache (lancer `fetch.py --kb`)"
    if x.usage != e.get("usage") or x.description_source != e.get("description_source"):
        return "documentation en cache différente de la fiche (`catalogue.py maj` d'abord)"
    if jour_lu is None:
        return "jour de lecture de la page inconnu (raw/kb/<produit de l'origine>/empreintes.json)"
    return None


def preparer(racine: Path, perimetre: str, ids: dict[str, str] | None = None, modele: str = pl.MODELE_DEFAUT,
             effort: str = pl.EFFORT_DEFAUT, horodatage: str | None = None, extraites: dict | None = None) -> dict:
    """Prépare un lot de recommentaire : `ids` ({id: motif}, par défaut `a_revoir`). Un seul lot en cours à la fois."""
    en_cours = [m["lot"] for m in lots(racine) if m["statut"] in pl.EN_COURS]
    if en_cours:
        raise pl.LotRefuse(f"lot de recommentaire en cours : {', '.join(en_cours)} (le relever et l'appliquer d'abord, ou `abandonner`)")
    ids = a_revoir(racine, perimetre) if ids is None else ids
    if not ids:
        raise pl.LotRefuse(f"aucune fiche à revoir pour {perimetre}")
    entrees = cat.charger(racine, perimetre)
    try:
        sections, shas = _sections_envoyees((racine / "CONTEXTE.md").read_text(encoding="utf-8"))
    except (OSError, ContexteInvalide) as err:
        raise pl.LotRefuse(f"CONTEXTE.md illisible ou invalide : {err}") from err
    try:
        essais = cat.lire_essais(racine)
    except ValueError as err:
        raise pl.LotRefuse(str(err)) from err
    extraites = pl.extraction_courante(racine, perimetre) if extraites is None else extraites
    consigne = systeme(sections)
    jour = date.today().isoformat()
    lot = f"{horodatage or time.strftime('%Y%m%d-%H%M%S')}-{perimetre}"
    produits = pl.produits_des_origines(racine)
    fiches, ecartees, requetes = {}, {}, []
    for k, motif in sorted(ids.items()):
        e = entrees.get(k)
        jour_lu = pl.jour_de_lecture(racine, e, produits) if e else None
        ecart = _motif_ecart(e, extraites.get(k), jour_lu)
        urls = sorted({s["url"] for s in (e or {}).get("sources") or [] if str(s.get("url", "")).startswith(("http://", "https://"))})
        if not ecart and not urls:
            ecart = "aucune URL de documentation sur la fiche"
        if ecart:
            ecartees[k] = ecart
            continue
        f = {"custom_id": f"r{len(fiches) + 1:04d}", "motif_a_revoir": motif, "releve_doc": min(jour_lu, jour),
             "releve_contexte": jour, "urls": urls, "essais": [k] if k in essais else [],
             "usage_sha": pl._sha(e.get("usage")), "description_sha": pl._sha(e.get("description_source")),
             "recommandation": e.get("recommandation"), "statut_usage": e.get("statut_usage")}
        fiches[k] = f
        requetes.append(requete(f["custom_id"], e, f, consigne, essais, modele, effort))
    if not requetes:
        raise pl.LotRefuse("aucune fiche à envoyer" + (f" ({len(ecartees)} écartées : {next(iter(ecartees.values()))} …)" if ecartees else ""))
    manifeste = {"lot": lot, "dossier": str(DOSSIER), "perimetre": perimetre, "cree_le": jour, "statut": "prepare",
                 "modele": modele, "effort": effort, "usage": USAGE_A1, "sections_sha": shas, "fiches": fiches,
                 "ecartees": ecartees}
    d = pl.dossier(racine, DOSSIER) / lot
    d.mkdir(parents=True, exist_ok=True)
    (d / "requetes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requetes), encoding="utf-8")
    pl.ecrire_manifeste(racine, manifeste)
    return manifeste


# ----------------------------------------------------------------------------------------------- résultats

def _commentaire(sortie: dict, f: dict, shas: dict[str, str]) -> dict | str:
    """Sortie du modèle -> commentaire pour `appliquer_commentaires`, ou motif de rejet."""
    r = sortie.get("recommandation") or {}
    verdict = r.get("verdict")
    cs = {}
    for s in sortie.get("contexte_sections") or []:
        c = str((s or {}).get("ctx_id", "")).strip()
        if c not in shas:
            return f"section citée inconnue, dépréciée ou vide : {c!r}"
        cs[c] = str(s.get("pourquoi", "")).strip()
    c = {"description": str(sortie.get("description", "")).strip(), "statut_usage": f["statut_usage"],
         "recommandation": {"verdict": verdict, "pourquoi": str(r.get("pourquoi", "")).strip()}, "contexte_sections": cs}
    raison = str(sortie.get("raison", "")).strip()
    c["raison_correction"] = f"recommentaire D128 : {raison or f['motif_a_revoir']}"[:cat.LONGUEUR_RAISON].strip()
    if verdict not in cat.VERDICTS_RECOMMANDANTS:
        return c
    prov = []
    for a in sortie.get("provenance") or []:
        if not isinstance(a, dict):
            continue
        src = str(a.get("source", "")).strip()
        if src.startswith(("http://", "https://")):
            ok, jour = pl._url_sans_ancre(src) in {pl._url_sans_ancre(u) for u in f["urls"]}, f["releve_doc"]
        elif src.startswith("contexte:"):
            ok, jour = src[len("contexte:"):] in cs, f["releve_contexte"]
        elif src.startswith("essai:"):
            ok, jour = src[len("essai:"):] in f["essais"], f["releve_contexte"]
        else:
            ok, jour = False, None
        if not ok:
            return f"source non envoyée ou section non citée : {src}"
        prov.append({"affirmation": str(a.get("affirmation", "")).strip(), "source": src, "releve_le": jour,
                     "caduc_si": str(a.get("caduc_si", "")).strip()})
    sans = sorted(k for k in cs if f"contexte:{k}" not in {a["source"] for a in prov})
    if sans:
        return f"section citée sans affirmation qui l'étaye : {', '.join(sans)}"
    c["provenance"] = prov
    return c


def analyser_resultats(manifeste: dict, resultats: list[dict]) -> dict:
    """Résultats Batch -> {commentaires: {id: commentaire}, rejets: {id: motif}, jetons, compte}."""
    par_custom = {f["custom_id"]: k for k, f in manifeste["fiches"].items()}
    jetons = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    commentaires, rejets, vus = {}, {}, set()
    compte = {"succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}
    for r in map(pl._en_dict, resultats):
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
            assert isinstance(sortie, dict)
        except (ValueError, AssertionError):
            rejets[k] = "sortie JSON illisible"
            continue
        c = _commentaire(sortie, manifeste["fiches"][k], manifeste["sections_sha"])
        if isinstance(c, str):
            rejets[k] = c
        else:
            commentaires[k] = c
    for k in manifeste["fiches"]:
        if k not in vus:
            rejets[k] = "aucun résultat"
    return {"commentaires": commentaires, "rejets": rejets, "jetons": jetons, "compte": compte}


def appliquer(racine: Path, manifeste: dict, resultats: list[dict], jour: str | None = None, ecrire: bool = True,
              exclure_systemes: list[str] | None = None, controle=None) -> dict:
    """Applique les commentaires valides par `catalogue.appliquer_commentaires` (exiger_provenance, sections résolues), fiche
    par fiche : une fiche refusée s'écarte seule (D129). Historique : ancienne recommandation et ancienne description gardées
    (« … corrigée », avant, raison) ; journal B3 des réévaluations (reevaluations.jsonl). `controle(entrée)` -> message ou
    None : contrôles de valider.py sur la fiche écrite (français, longueurs) ; un refus remet la fiche dans son état d'avant.
    Rend le bilan (aussi écrit dans le manifeste)."""
    from ..contexte import resoudre
    jour = jour or date.today().isoformat()
    a = analyser_resultats(manifeste, resultats)
    entrees = cat.charger(racine, manifeste["perimetre"])
    try:
        courantes = {k: v["sha1"] for k, v in analyser((racine / "CONTEXTE.md").read_text(encoding="utf-8"))[0].items()}
    except (OSError, ContexteInvalide) as err:
        raise pl.LotRefuse(f"CONTEXTE.md illisible ou invalide : {err}") from err
    try:
        essais = set(cat.lire_essais(racine))
    except ValueError:
        essais = None
    contexte = empreinte_contexte(racine)
    sautees, refusees, journal, appliquees = {}, {}, [], []
    for k, c in sorted(a["commentaires"].items()):
        e, f = entrees.get(k), manifeste["fiches"][k]
        if e is None or not cat.provenance_due(e):
            sautees[k] = "plus due (provenance déjà posée, verdict changé ou fiche retirée)"
            continue
        if pl._sha(e.get("usage")) != f["usage_sha"] or pl._sha(e.get("description_source")) != f["description_sha"]:
            sautees[k] = "documentation modifiée depuis la préparation"
            continue
        if e.get("recommandation") != f["recommandation"]:
            sautees[k] = "recommandation révisée depuis la préparation"
            continue
        changees = [s for s in c["contexte_sections"] if courantes.get(s) != manifeste["sections_sha"].get(s)]
        if changees:
            sautees[k] = f"section de CONTEXTE.md modifiée depuis l'envoi : {', '.join(changees)}"
            continue
        description_avant, avant, n_journal = e.get("description"), copy.deepcopy(e), len(journal)
        erreurs = cat.appliquer_commentaires(entrees, {k: c}, jour=jour, contexte=contexte,
                                             resoudre=lambda cites: resoudre(racine, cites), journal=journal,
                                             motif_de=lambda _e: MOTIF_JOURNAL, exclure_systemes=exclure_systemes,
                                             essais=essais, exiger_provenance=True)
        if erreurs:
            refusees[k] = "; ".join(x.split(": ", 1)[-1] for x in erreurs)
            continue
        if controle is not None and (msg := controle(entrees[k])):
            entrees[k], journal[n_journal:] = avant, []
            refusees[k] = msg
            continue
        if description_avant != c["description"]:
            cat.noter_correction(entrees[k], jour, "description", description_avant, c["raison_correction"])
        appliquees.append(k)
    verdicts = {l["id"]: [l["verdict_avant"], l["verdict_apres"]] for l in journal}
    if ecrire and appliquees:
        cat.ecrire(racine, manifeste["perimetre"], entrees)
        with open(cat.dossier(racine, manifeste["perimetre"]) / "reevaluations.jsonl", "a", encoding="utf-8") as fj:
            for l in journal:
                fj.write(json.dumps(l, ensure_ascii=False) + "\n")
    bilan = {"applique_le": jour, "appliquees": appliquees,
             "provenance_posee": [k for k in appliquees if verdicts[k][1] in cat.VERDICTS_RECOMMANDANTS],
             "ignorees": [k for k in appliquees if verdicts[k][1] == "ignorer"],
             "verdicts_changes": {k: v for k, v in verdicts.items() if v[0] != v[1]},
             "rejets": {**a["rejets"], **refusees}, "sautees": sautees, "jetons": a["jetons"], "compte": a["compte"],
             "cout": manifeste.get("cout")}
    if ecrire:
        manifeste["statut"], manifeste["bilan"] = "applique", bilan
        pl.ecrire_manifeste(racine, manifeste)
    return bilan


def ligne_bilan(manifeste: dict) -> str:
    b = manifeste.get("bilan") or {}
    j = b.get("jetons") or {}
    c = b.get("cout")
    cout = f"{c['usd']:.4f} $ (A1, {c['source']})" if isinstance(c, dict) and isinstance(c.get("usd"), (int, float)) else "coût non mesuré"
    return (f"{manifeste['lot']} : {len(b.get('appliquees', []))}/{len(manifeste['fiches'])} recommentées "
            f"({len(b.get('provenance_posee', []))} avec provenance, {len(b.get('ignorees', []))} passées à ignorer, "
            f"{len(b.get('verdicts_changes', {}))} verdicts changés), {len(b.get('rejets', {}))} rejetées, "
            f"{len(b.get('sautees', {}))} sautées ; jetons entrée {j.get('input_tokens', 0)}, sortie {j.get('output_tokens', 0)}, "
            f"cache écrit {j.get('cache_creation_input_tokens', 0)}, lu {j.get('cache_read_input_tokens', 0)} ; {cout} ; "
            f"modèle {manifeste['modele']}")
