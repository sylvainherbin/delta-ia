"""Fiches de modèles et d'efforts (kb-modeles/*.yaml → docs/data/kb/modeles.json).

Chaque modèle lançable par OPÉRER est décrit dans `kb-modeles/<famille>.yaml` avec ses niveaux d'effort,
son coût en quota sur les forfaits réels de Sylvain (`kb-modeles/forfaits.yaml`), son prix API public à part,
ses points forts/faibles et benchmarks sourcés et datés (`verifie: false` si source secondaire),
et les constats internes datés. Aucun passage automatique ne réécrit ces fiches.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

from .modeles import PERIMETRE_DU_PRODUIT, STATUTS_USAGE, slug
from ..versions_evenements import ajouter_evenements, lire_precedent

DOSSIER_SOURCE = "kb-modeles"
CATEGORIE = "modeles"
FAMILLES = ("claude", "codex", "antigravity", "locaux")
VERDICTS_OPERER = ("utiliser", "tester", "ignorer")
VERDICT_KB_DE_OPERER = {
    "utiliser": "utiliser",
    "tester": "tester",
    "ignorer": "ignorer",
}
RE_PRIVE_INTERDIT = re.compile(r"\bm-[0-9a-f]{12}\b|\bcc-socks\b|/home/")


class FicheModeleInvalide(ValueError):
    pass


def chemin_kb_modeles(racine: Path) -> Path:
    return racine / "docs" / "data" / "kb" / "modeles.json"


def _verifier_date_iso(valeur: object, contexte: str) -> str:
    texte = valeur.isoformat() if isinstance(valeur, date) else str(valeur or "").strip()
    try:
        date.fromisoformat(texte)
    except ValueError as err:
        raise FicheModeleInvalide(f"{contexte} : date AAAA-MM-JJ attendue, reçu {valeur!r}") from err
    return texte


def _verifier_url_https(valeur: object, contexte: str) -> str:
    url = str(valeur or "").strip()
    if not url.startswith("https://"):
        raise FicheModeleInvalide(f"{contexte} : URL https:// attendue, reçu {valeur!r}")
    return url


def _verifier_sans_fuite_privee(texte: str, contexte: str) -> None:
    m = RE_PRIVE_INTERDIT.search(texte)
    if m:
        raise FicheModeleInvalide(f"{contexte} : motif interne interdit par D77 détecté ({m.group(0)!r})")


def _charger_yaml(chemin: Path) -> dict:
    if not chemin.is_file():
        raise FicheModeleInvalide(f"{chemin.name} : fichier introuvable")
    brut = chemin.read_text(encoding="utf-8")
    _verifier_sans_fuite_privee(brut, chemin.name)
    try:
        doc = yaml.safe_load(brut)
    except yaml.YAMLError as err:
        raise FicheModeleInvalide(f"{chemin.name} : YAML illisible ({err})") from err
    if not isinstance(doc, dict):
        raise FicheModeleInvalide(f"{chemin.name} : la racine YAML doit être un dictionnaire")
    return doc


def charger_forfaits(racine: Path) -> dict[str, dict]:
    chemin = racine / DOSSIER_SOURCE / "forfaits.yaml"
    doc = _charger_yaml(chemin)
    date_rel = _verifier_date_iso(doc.get("date_releve"), "forfaits.yaml:date_releve")
    forfaits = doc.get("forfaits")
    if not isinstance(forfaits, dict) or not forfaits:
        raise FicheModeleInvalide("forfaits.yaml : dictionnaire `forfaits` vide ou absent")
    resultat: dict[str, dict] = {}
    for fid, f in forfaits.items():
        if not isinstance(f, dict) or f.get("id") != fid:
            raise FicheModeleInvalide(f"forfaits.yaml:{fid} : champ `id` incohérent")
        for cle in ("nom", "fournisseur", "jauges_operer", "regles_quota", "sources"):
            if f.get(cle) in (None, "", []):
                raise FicheModeleInvalide(f"forfaits.yaml:{fid} : champ `{cle}` manquant")
        sources = []
        for idx, s in enumerate(f.get("sources", [])):
            if not isinstance(s, dict):
                raise FicheModeleInvalide(f"forfaits.yaml:{fid}:sources[{idx}] : dictionnaire attendu")
            sources.append({
                "url": _verifier_url_https(s.get("url"), f"forfaits.yaml:{fid}:sources[{idx}]"),
                "libelle": str(s.get("libelle") or "").strip(),
                "date": _verifier_date_iso(s.get("date"), f"forfaits.yaml:{fid}:sources[{idx}]"),
                "officielle": bool(s.get("officielle", True)),
            })
        if not sources:
            raise FicheModeleInvalide(f"forfaits.yaml:{fid} : `sources` vide")
        resultat[fid] = {**f, "date_releve": date_rel, "sources": sources}
    return resultat


def _formater_description_markdown(
    modele_doc: dict,
    eff: dict,
    forfaits_applicables: list[dict],
    date_releve: str,
) -> str:
    """Construit la description Markdown complète pour l'interface Web et MCP."""
    lignes: list[str] = []
    rec = eff["recommandation_operer"]
    cout = eff["cout_quota"]
    forfait = modele_doc["forfait"]
    prix = modele_doc["prix_api"]

    note_defaut = "effort par défaut du modèle" if eff["defaut"] else f"défaut du modèle : `{modele_doc['effort_defaut']}`"
    lignes.append(
        f"**Couple `{modele_doc['modele']}` × `{eff['effort']}`** ({note_defaut}) — "
        f"exécutant `{modele_doc['executant']}`, relevé du {date_releve}."
    )
    lignes.append("")
    lignes.append(f"Portée du défaut : {modele_doc.get('effort_defaut_portee')}. {modele_doc['effort_defaut_detail']}")
    lignes.append("### Ce que change cet effort")
    lignes.append(f"- **Invocation** : `{eff['usage']}`")
    lignes.append(f"- **Effet de `{eff['effort']}`** : {eff['effet_effort']}")
    lignes.append(f"- **Coût de `{eff['effort']}`** : **{cout['niveau']}** — {cout['poids_relatif'] or 'inconnu'}. {cout['resume']}")
    lignes.append(
        f"- **Recommandation OPÉRER (`{rec['verdict']}`)** : {rec['pourquoi']} "
        f"(adapté à : {', '.join(rec['natures_adaptees']) or 'aucune'} ; "
        f"déconseillé pour : {', '.join(rec['natures_deconseillees']) or 'aucune'})."
    )
    lignes.append("")
    lignes.append("### Tous les niveaux d'effort du modèle")
    for e in modele_doc["efforts"]:
        marqueur = " (défaut)" if e["defaut"] else ""
        lignes.append(
            f"- **`{e['effort']}`**{marqueur} — quota : {e['cout_quota']['niveau']} ({e['cout_quota']['poids_relatif'] or 'inconnu'}) — "
            f"{e['effet_effort']}"
        )
    lignes.append("")
    lignes.append("### Coût en quota sur les forfaits de Sylvain")
    lignes.append(f"- **Forfait principal** : {forfait['nom']} (groupe `{forfait['groupe_quota']}`)")
    lignes.append(f"- **Fenêtre 5 h** : {forfait['fenetre_5h']}")
    lignes.append(f"- **Fenêtre semaine** : {forfait['fenetre_semaine']}")
    lignes.append(f"- **Règles et gardes** : {forfait['plafonds_et_regles']}")
    if len(forfaits_applicables) > 1:
        noms_forfaits = ", ".join(fa["nom"] for fa in forfaits_applicables)
        lignes.append(f"- **Forfaits rattachés** : {noms_forfaits}")
    lignes.append("")
    lignes.append("### Prix API public (à part du forfait)")
    entree = f"{prix['entree_usd']:.2f} $" if isinstance(prix.get("entree_usd"), (int, float)) else "n/d"
    sortie = f"{prix['sortie_usd']:.2f} $" if isinstance(prix.get("sortie_usd"), (int, float)) else "n/d"
    cache_lu = f"{prix['cache_lu_usd']:.2f} $" if isinstance(prix.get("cache_lu_usd"), (int, float)) else "n/d"
    lignes.append(
        f"- **Tarif public ({prix['unite']})** : entrée {entree}, sortie {sortie}, cache lu {cache_lu}. "
        f"{prix['seuil_long_contexte']}"
    )
    lignes.append(f"- **Note facturation** : {prix['note']}")
    lignes.append("")
    credits = modele_doc.get("tarifs_credits")
    if credits:
        lignes.append("### Barème de crédits Codex")
        lignes.append(f"- **{credits['unite']}** : entrée {credits['entree']}, cache lu {credits['cache_lu']}, sortie {credits['sortie']}.")
        lignes.append(f"- {credits['note']} ({credits['url']}, {credits['date']})")
        lignes.append("")
    lignes.append("### Points forts annoncés")
    for pf in modele_doc["points_forts"]:
        statut = "vérifié contre la source" if pf["verifie"] else "non vérifié"
        lignes.append(f"- {pf['texte']} ({pf['source']}, {pf['date']}, {statut})")
    lignes.append("")
    lignes.append("### Points faibles et limites")
    for pf in modele_doc["points_faibles"]:
        statut = "vérifié contre la source" if pf["verifie"] else "non vérifié"
        lignes.append(f"- {pf['texte']} ({pf['source']}, {pf['date']}, {statut})")
    lignes.append("")
    lignes.append("### Benchmarks publics et mesures")
    for b in modele_doc["benchmarks"]:
        statut = "vérifié" if b["verifie"] else "non vérifié"
        lignes.append(
            f"- **{b['nom']}** ({b['domaine']}) : **{b['valeur']} {b['unite']}** "
            f"(effort mesuré : `{b['effort_mesure'] or 'non précisé par la source'}`) — {b['comparaisons']} "
            f"[{b['source']}, {b['date']}, {statut}]"
        )
    lignes.append("")
    lignes.append("### Constats internes datés")
    for ci in modele_doc["constats_internes"]:
        lignes.append(f"- **{ci['date']} — {ci['titre']}** : {ci['constat']} ({ci['source']})")

    for si in modele_doc.get("sources_internes", []):
        lignes.append(f"- **Observation interne — {si['date']}** : {si['constat']} ({si['document']})")
    return "\n".join(lignes)


def _construire_aliases(
    famille: str,
    executant: str,
    modele: str,
    modele_operer: str,
    aliases_modele: list[str],
    effort: str,
    est_defaut: bool,
) -> list[str]:
    bruts: list[str] = []
    noms_base = [modele, modele_operer, slug(modele), slug(modele_operer), *aliases_modele]
    for base in noms_base:
        b = str(base).strip()
        if not b:
            continue
        for variante in (b, b.lower()):
            bruts.extend([
                f"{variante}:{effort}",
                f"{variante}/{effort}",
                f"{variante}-{effort}",
                f"{variante}@{effort}",
                f"{executant}:{variante}:{effort}",
                f"{executant}/{variante}/{effort}",
                f"{famille}:{variante}:{effort}",
            ])
            if est_defaut:
                bruts.extend([
                    variante,
                    f"modele-{slug(variante)}",
                    f"{executant}:{variante}",
                    f"{executant}/{variante}",
                    f"{famille}:{variante}",
                ])
    vus: set[str] = set()
    uniques: list[str] = []
    for a in bruts:
        if a not in vus:
            vus.add(a)
            uniques.append(a)
    return uniques


def _valider_affirmations(items: object, contexte: str) -> list[dict]:
    if not isinstance(items, list):
        raise FicheModeleInvalide(f"{contexte} : liste attendue")
    resultat = []
    for idx, it in enumerate(items):
        ctx = f"{contexte}[{idx}]"
        if not isinstance(it, dict):
            raise FicheModeleInvalide(f"{ctx} : dictionnaire attendu")
        texte = str(it.get("texte") or "").strip()
        source = str(it.get("source") or "").strip()
        if not texte or not source:
            raise FicheModeleInvalide(f"{ctx} : `texte` et `source` obligatoires")
        if it.get("verifie") is True and not str(it.get("extrait") or "").strip():
            raise FicheModeleInvalide(f"{ctx} : extrait obligatoire pour une affirmation vérifiée")
        if not isinstance(it.get("verifie"), bool):
            raise FicheModeleInvalide(f"{ctx} : booléen `verifie` obligatoire")
        resultat.append({
            "texte": texte,
            "source": source,
            "url": _verifier_url_https(it.get("url"), ctx),
            "date": _verifier_date_iso(it.get("date"), ctx),
            "verifie": it["verifie"],
            **({"extrait": it["extrait"]} if it.get("extrait") else {}),
        })
    return resultat


def _valider_benchmarks(items: object, contexte: str) -> list[dict]:
    if not isinstance(items, list):
        raise FicheModeleInvalide(f"{contexte} : liste attendue")
    resultat = []
    for idx, it in enumerate(items):
        ctx = f"{contexte}[{idx}]"
        if not isinstance(it, dict):
            raise FicheModeleInvalide(f"{ctx} : dictionnaire attendu")
        for cle in ("nom", "domaine", "unite", "comparaisons", "source"):
            if not str(it.get(cle) or "").strip():
                raise FicheModeleInvalide(f"{ctx} : `{cle}` obligatoire")
        if it.get("valeur") in (None, ""):
            raise FicheModeleInvalide(f"{ctx} : `valeur` obligatoire")
        if it.get("verifie") is True and not str(it.get("extrait") or "").strip():
            raise FicheModeleInvalide(f"{ctx} : extrait obligatoire pour une affirmation vérifiée")
        if not isinstance(it.get("verifie"), bool):
            raise FicheModeleInvalide(f"{ctx} : booléen `verifie` obligatoire")
        resultat.append({
            "nom": str(it["nom"]).strip(),
            "domaine": str(it["domaine"]).strip(),
            "valeur": it["valeur"],
            "unite": str(it["unite"]).strip(),
            "effort_mesure": it.get("effort_mesure"),
            "comparaisons": str(it["comparaisons"]).strip(),
            "source": str(it["source"]).strip(),
            "url": _verifier_url_https(it.get("url"), ctx),
            "date": _verifier_date_iso(it.get("date"), ctx),
            "verifie": it["verifie"],
            **({"extrait": it["extrait"]} if it.get("extrait") else {}),
        })
    return resultat


def _valider_constats(items: object, contexte: str) -> list[dict]:
    if not isinstance(items, list):
        raise FicheModeleInvalide(f"{contexte} : liste attendue")
    resultat = []
    for idx, it in enumerate(items):
        ctx = f"{contexte}[{idx}]"
        if not isinstance(it, dict):
            raise FicheModeleInvalide(f"{ctx} : dictionnaire attendu")
        for cle in ("titre", "constat", "source"):
            if not str(it.get(cle) or "").strip():
                raise FicheModeleInvalide(f"{ctx} : `{cle}` obligatoire")
        resultat.append({
            "date": _verifier_date_iso(it.get("date"), ctx),
            "titre": str(it["titre"]).strip(),
            "constat": str(it["constat"]).strip(),
            "source": str(it["source"]).strip(),
        })
    return resultat


def lire_famille(chemin: Path, forfaits: dict[str, dict]) -> list[dict]:
    doc = _charger_yaml(chemin)
    ctx_f = chemin.name
    date_releve = _verifier_date_iso(doc.get("date_releve"), f"{ctx_f}:date_releve")
    famille = str(doc.get("famille") or "").strip()
    if famille not in FAMILLES or famille != chemin.stem:
        raise FicheModeleInvalide(f"{ctx_f} : `famille` doit être {chemin.stem!r}")
    fournisseur = str(doc.get("fournisseur") or "").strip()
    executant = str(doc.get("executant") or "").strip()
    executants_operer = doc.get("executants_operer")
    if not fournisseur or not executant or not isinstance(executants_operer, list) or not executants_operer:
        raise FicheModeleInvalide(f"{ctx_f} : `fournisseur`, `executant` et `executants_operer` obligatoires")
    produit = str(doc.get("produit") or "").strip()
    produits = doc.get("produits")
    if produit not in PERIMETRE_DU_PRODUIT or not isinstance(produits, list) or any(p not in PERIMETRE_DU_PRODUIT for p in produits):
        raise FicheModeleInvalide(f"{ctx_f} : `produit` / `produits` invalides")
    forfaits_cibles = doc.get("forfaits_cibles")
    if not isinstance(forfaits_cibles, list) or not forfaits_cibles or any(fc not in forfaits for fc in forfaits_cibles):
        raise FicheModeleInvalide(f"{ctx_f} : `forfaits_cibles` doit référencer des clés de forfaits.yaml")
    forfaits_applicables = [forfaits[fc] for fc in forfaits_cibles]

    modeles = doc.get("modeles")
    if not isinstance(modeles, list) or not modeles:
        raise FicheModeleInvalide(f"{ctx_f} : liste `modeles` vide")

    entrees: list[dict] = []
    for m in modeles:
        if not isinstance(m, dict):
            raise FicheModeleInvalide(f"{ctx_f} : chaque modèle doit être un dictionnaire")
        id_mod = str(m.get("modele") or "").strip()
        if not id_mod:
            raise FicheModeleInvalide(f"{ctx_f} : `modele` manquant")
        ctx_m = f"{ctx_f}:{id_mod}"
        modele_operer = str(m.get("modele_operer") or id_mod).strip()
        aliases_modele = [str(a).strip() for a in m.get("aliases_modele", []) if str(a).strip()]
        nom_modele = str(m.get("nom") or "").strip()
        if not nom_modele:
            raise FicheModeleInvalide(f"{ctx_m} : `nom` manquant")
        date_sortie = _verifier_date_iso(m["date_sortie"], f"{ctx_m}:date_sortie") if m.get("date_sortie") is not None else None
        cutoff = m.get("cutoff_connaissances")
        fenetre = m.get("fenetre_contexte_jetons")
        sortie_max = m.get("sortie_max_jetons")
        if any(v is not None and (not isinstance(v, int) or isinstance(v, bool)) for v in (fenetre, sortie_max)):
            raise FicheModeleInvalide(f"{ctx_m} : `cutoff_connaissances`, `fenetre_contexte_jetons` et `sortie_max_jetons` requis")
        effort_defaut = str(m.get("effort_defaut") or "").strip()
        effort_defaut_detail = str(m.get("effort_defaut_detail") or "").strip()
        if not effort_defaut or not effort_defaut_detail:
            raise FicheModeleInvalide(f"{ctx_m} : `effort_defaut` et `effort_defaut_detail` requis")
        statut_usage = str(m.get("statut_usage") or "").strip()
        if statut_usage not in STATUTS_USAGE:
            raise FicheModeleInvalide(f"{ctx_m} : `statut_usage` parmi {STATUTS_USAGE}")

        forfait = m.get("forfait")
        if not isinstance(forfait, dict) or forfait.get("id") not in forfaits:
            raise FicheModeleInvalide(f"{ctx_m}:forfait : `id` doit exister dans forfaits.yaml")
        for cle in ("nom", "groupe_quota", "fenetre_5h", "fenetre_semaine", "plafonds_et_regles"):
            if not str(forfait.get(cle) or "").strip():
                raise FicheModeleInvalide(f"{ctx_m}:forfait : `{cle}` manquant")
        if not isinstance(forfait.get("jauges_operer"), list):
            raise FicheModeleInvalide(f"{ctx_m}:forfait : `jauges_operer` doit être une liste")

        prix_api = m.get("prix_api")
        if not isinstance(prix_api, dict):
            raise FicheModeleInvalide(f"{ctx_m}:prix_api : dictionnaire attendu")
        for cle in ("devise", "unite", "seuil_long_contexte", "batch", "fast", "note"):
            if not str(prix_api.get(cle) or "").strip():
                raise FicheModeleInvalide(f"{ctx_m}:prix_api : `{cle}` manquant")

        points_forts = _valider_affirmations(m.get("points_forts"), f"{ctx_m}:points_forts")
        points_faibles = _valider_affirmations(m.get("points_faibles"), f"{ctx_m}:points_faibles")
        benchmarks = _valider_benchmarks(m.get("benchmarks"), f"{ctx_m}:benchmarks")
        constats_internes = _valider_constats(m.get("constats_internes"), f"{ctx_m}:constats_internes")

        sources = []
        for idx, s in enumerate(m.get("sources") if isinstance(m.get("sources"), list) else []):
            ctx_s = f"{ctx_m}:sources[{idx}]"
            if not isinstance(s, dict) or not str(s.get("libelle") or "").strip():
                raise FicheModeleInvalide(f"{ctx_s} : `libelle` obligatoire")
            sources.append({
                "url": _verifier_url_https(s.get("url"), ctx_s),
                "libelle": str(s["libelle"]).strip(),
                "date": _verifier_date_iso(s.get("date"), ctx_s),
                "officielle": bool(s.get("officielle", True)),
            })
        if not sources:
            raise FicheModeleInvalide(f"{ctx_m} : `sources` vide")

        efforts_bruts = m.get("efforts")
        if not isinstance(efforts_bruts, list) or not efforts_bruts:
            raise FicheModeleInvalide(f"{ctx_m} : `efforts` vide")

        efforts_valides: list[dict] = []
        nb_defaut = 0
        for idx, eff in enumerate(efforts_bruts):
            ctx_e = f"{ctx_m}:efforts[{idx}]"
            if not isinstance(eff, dict):
                raise FicheModeleInvalide(f"{ctx_e} : dictionnaire attendu")
            nom_eff = str(eff.get("effort") or "").strip()
            usage = str(eff.get("usage") or "").strip()
            effet = str(eff.get("effet_effort") or "").strip()
            if not nom_eff or not usage or not effet:
                raise FicheModeleInvalide(f"{ctx_e} : `effort`, `usage` et `effet_effort` obligatoires")
            est_defaut = bool(eff.get("defaut", False))
            if est_defaut:
                if nom_eff != effort_defaut:
                    raise FicheModeleInvalide(f"{ctx_e} : `defaut: true` sur {nom_eff!r} mais `effort_defaut` vaut {effort_defaut!r}")
                nb_defaut += 1
            cout = eff.get("cout_quota")
            if not isinstance(cout, dict) or any(not str(cout.get(c) or "").strip() for c in ("niveau", "resume")):
                raise FicheModeleInvalide(f"{ctx_e}:cout_quota : `niveau`, `poids_relatif` et `resume` obligatoires")
            rec = eff.get("recommandation_operer")
            if not isinstance(rec, dict) or rec.get("verdict") not in VERDICTS_OPERER or not str(rec.get("pourquoi") or "").strip():
                raise FicheModeleInvalide(f"{ctx_e}:recommandation_operer : `verdict` parmi {VERDICTS_OPERER} et `pourquoi` obligatoires")
            if not isinstance(rec.get("natures_adaptees"), list) or not isinstance(rec.get("natures_deconseillees"), list):
                raise FicheModeleInvalide(f"{ctx_e}:recommandation_operer : `natures_adaptees` et `natures_deconseillees` doivent être des listes")
            efforts_valides.append({
                "effort": nom_eff,
                "defaut": est_defaut,
                "usage": usage,
                "cout_quota": {
                    "niveau": str(cout["niveau"]).strip(),
                    "poids_relatif": cout.get("poids_relatif"),
                    "resume": str(cout["resume"]).strip(),
                },
                "effet_effort": effet,
                "recommandation_operer": {
                    "verdict": rec["verdict"],
                    "natures_adaptees": [str(x).strip() for x in rec["natures_adaptees"]],
                    "natures_deconseillees": [str(x).strip() for x in rec["natures_deconseillees"]],
                    "pourquoi": str(rec["pourquoi"]).strip(),
                },
            })

        if nb_defaut != 1:
            raise FicheModeleInvalide(f"{ctx_m} : exactement un effort doit porter `defaut: true` (trouvé : {nb_defaut})")

        niveaux_resume = [
            {
                "effort": e["effort"],
                "defaut": e["defaut"],
                "usage": e["usage"],
                "effet_effort": e["effet_effort"],
                "cout_quota_niveau": e["cout_quota"]["niveau"],
                "cout_quota_poids": e["cout_quota"]["poids_relatif"],
                "verdict_operer": e["recommandation_operer"]["verdict"],
            }
            for e in efforts_valides
        ]

        modele_normalise = {
            "modele": id_mod,
            "modele_operer": modele_operer,
            "aliases_modele": aliases_modele,
            "nom": nom_modele,
            "executant": executant,
            "date_sortie": date_sortie,
            "cutoff_connaissances": cutoff,
            "fenetre_contexte_jetons": fenetre,
            "sortie_max_jetons": sortie_max,
            "effort_defaut": effort_defaut,
            "effort_defaut_detail": effort_defaut_detail,
            "effort_defaut_portee": m.get("effort_defaut_portee"),
            "statut_usage": statut_usage,
            "forfait": forfait,
            "prix_api": prix_api,
            "tarifs_credits": m.get("tarifs_credits"),
            "points_forts": points_forts,
            "points_faibles": points_faibles,
            "benchmarks": benchmarks,
            "constats_internes": constats_internes,
            "sources_internes": m.get("sources_internes", []),
            "sources": sources,
            "efforts": efforts_valides,
        }

        for eff in efforts_valides:
            ident = f"modele-{slug(id_mod)}-{slug(eff['effort'])}"
            suffixe_defaut = " (défaut)" if eff["defaut"] else ""
            nom_fiche = f"{nom_modele} — effort {eff['effort']}{suffixe_defaut}"
            description = _formater_description_markdown(modele_normalise, eff, forfaits_applicables, date_releve)
            _verifier_sans_fuite_privee(description, f"{ctx_m}:{eff['effort']}:description")
            rec_op = eff["recommandation_operer"]
            entrees.append({
                "id": ident,
                "aliases_modele": aliases_modele,
                "aliases": _construire_aliases(
                    famille=famille,
                    executant=executant,
                    modele=id_mod,
                    modele_operer=modele_operer,
                    aliases_modele=aliases_modele,
                    effort=eff["effort"],
                    est_defaut=eff["defaut"],
                ),
                "produit": produit,
                "produits": list(produits),
                "categorie": CATEGORIE,
                "origine": "locale",
                "fichier_source": f"{DOSSIER_SOURCE}/{chemin.name}",
                "date_releve": date_releve,
                "verifie_le": date_releve,
                "maj_le": date_releve,
                "famille": famille,
                "fournisseur": fournisseur,
                "executant": executant,
                "executants_operer": list(executants_operer),
                "modele": id_mod,
                "modele_operer": modele_operer,
                "nom_modele": nom_modele,
                "nom": nom_fiche,
                "effort": eff["effort"],
                "effort_defaut": eff["defaut"],
                "effort_defaut_modele": effort_defaut,
                "effort_defaut_detail": effort_defaut_detail,
                "effort_defaut_portee": m.get("effort_defaut_portee"),
                "niveaux_effort_disponibles": niveaux_resume,
                "effet_effort": eff["effet_effort"],
                "date_sortie": date_sortie,
                "cutoff_connaissances": cutoff,
                "fenetre_contexte_jetons": fenetre,
                "sortie_max_jetons": sortie_max,
                "gabarit": "complet",
                "description": description,
                "description_source": eff["effet_effort"],
                "usage": eff["usage"],
                "usage_nature": "syntaxe",
                "exemple": eff["usage"],
                "disponibilite": forfait["nom"],
                "statut_usage": statut_usage,
                "forfait": forfait,
                "forfaits_applicables": [
                    {
                        "id": fa["id"],
                        "nom": fa["nom"],
                        "fournisseur": fa["fournisseur"],
                        "abonnement_mensuel_usd": fa.get("abonnement_mensuel_usd"),
                        "credits_api_mensuels_inclus_usd": fa.get("credits_api_mensuels_inclus_usd"),
                        "jauges_operer": fa["jauges_operer"],
                        "regles_quota": fa["regles_quota"],
                    }
                    for fa in forfaits_applicables
                ],
                "cout_quota": eff["cout_quota"],
                "prix_api": prix_api,
                "tarifs_credits": m.get("tarifs_credits"),
                "recommandation": {
                    "verdict": VERDICT_KB_DE_OPERER[rec_op["verdict"]],
                    "verdict_operer": rec_op["verdict"],
                    "natures_adaptees": rec_op["natures_adaptees"],
                    "natures_deconseillees": rec_op["natures_deconseillees"],
                    "pourquoi": rec_op["pourquoi"],
                },
                "recommandation_operer": rec_op,
                "points_forts": points_forts,
                "points_faibles": points_faibles,
                "benchmarks": benchmarks,
                "constats_internes": constats_internes,
                "sources_internes": m.get("sources_internes", []),
                "sources_champs": m.get("sources_champs", {}),
                "sources": sources,
                "commentee": True,
                "certitude": "officiel" if any(s["officielle"] for s in sources) else "rapporte",
                "retiree": False,
            })

    return entrees


def construire_modeles(racine: Path) -> dict:
    """Construit le document complet de `modeles.json` depuis `kb-modeles/*.yaml`."""
    dossier = racine / DOSSIER_SOURCE
    if not dossier.is_dir():
        raise FicheModeleInvalide(f"dossier {DOSSIER_SOURCE}/ introuvable")
    forfaits = charger_forfaits(racine)
    entrees: list[dict] = []
    for fam in FAMILLES:
        entrees.extend(lire_famille(dossier / f"{fam}.yaml", forfaits))
    ids = [e["id"] for e in entrees]
    doublons = sorted({i for i in ids if ids.count(i) > 1})
    if doublons:
        raise FicheModeleInvalide(f"identifiants de couple modèle × effort en double : {', '.join(doublons)}")
    modeles = {}
    couples = []
    variables = {"id", "aliases", "nom", "effort", "effort_defaut", "effet_effort", "description",
                 "description_source", "usage", "exemple", "cout_quota", "recommandation", "recommandation_operer", "aliases_modele"}
    for e in entrees:
        cle = e["modele"]
        debut, commun = e["description"].split("### Tous les niveaux d'effort du modèle", 1)
        if cle not in modeles:
            modele = {k: v for k, v in e.items() if k not in variables}
            modele["description_commune"] = "### Tous les niveaux d'effort du modèle" + commun
            modele["aliases_effort"] = _construire_aliases(e["famille"], e["executant"], cle,
                e["modele_operer"], e["aliases_modele"], "{effort}", False)
            modele["aliases_defaut"] = []
            modeles[cle] = modele
        if e["effort_defaut"]:
            sans_defaut = _construire_aliases(e["famille"], e["executant"], cle, e["modele_operer"], e["aliases_modele"], e["effort"], False)
            modeles[cle]["aliases_defaut"] = [a for a in e["aliases"] if a not in sans_defaut]
        couples.append({"modele": cle, **{k: e[k] for k in sorted(variables) if k not in {"aliases", "description", "aliases_modele"}}, "description": debut.rstrip()})
    maj_le = max((e["maj_le"] for e in entrees), default=None)
    return {"schema_version": 2, "categorie": CATEGORIE, "origine": "locale", "date_releve": maj_le,
            "maj_le": maj_le, "forfaits": forfaits, "modeles": modeles,
            "total_modeles": len(modeles), "total": len(couples), "entrees": couples}


def _ecrire_json_atomique(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(chemin)


def ecrire_modeles(racine: Path) -> dict:
    """Écrit `docs/data/kb/modeles.json` de manière atomique."""
    doc = construire_modeles(racine)
    precedent = lire_precedent(chemin_kb_modeles(racine))
    changements = []
    if isinstance(precedent, dict) and isinstance(precedent.get("modeles"), dict):
        anciens = precedent["modeles"]
        for ident, modele in doc["modeles"].items():
            if ident not in anciens:
                changements.append({"modele": ident, "avant": None, "apres": modele.get("version") or ident})
            elif (anciens[ident].get("version") is not None and modele.get("version") is not None
                  and anciens[ident]["version"] != modele["version"]):
                changements.append({"modele": ident, "avant": anciens[ident]["version"], "apres": modele["version"]})
    _ecrire_json_atomique(chemin_kb_modeles(racine), doc)
    ajouter_evenements(racine, changements)
    return doc
