"""Scission des sources modèles et méthodes avant génération (conception §1.3, lot L2).

`kb-modeles/*.yaml` et `kb-methodes/*.md` mêlent faits publics (identités, prix, limites, sources) et rattachements de
l'instance (constats internes, recommandations OPÉRER, statut d'usage, forfait souscrit, jauges). La scission les sépare
par une liste positive de chemins : seul un chemin C passe dans la part publique ; P, S et tout chemin inconnu vont dans la
part privée, conservée dans le magasin personnel. La recomposition des deux parts redonne exactement la source : rien
n'est perdu, et un régénérateur public (lot L5) pourra lire la seule part publique.

Les textes privés de la scission servent aussi de sentinelles : aucun ne doit apparaître dans la génération commune.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

# Chemins normalisés : `[]` membre de liste, `*` clé variable. Une clé sans descendant listé est atomique.
PUBLIC_MODELES = set("""
date_releve famille fournisseur produit produits
modeles[].modele modeles[].nom modeles[].aliases_modele modeles[].date_sortie modeles[].cutoff_connaissances
modeles[].fenetre_contexte_jetons modeles[].sortie_max_jetons modeles[].effort_defaut modeles[].effort_defaut_portee
modeles[].prix_api.batch modeles[].prix_api.cache_ecrit_1h_usd modeles[].prix_api.cache_ecrit_5m_usd
modeles[].prix_api.cache_lu_usd modeles[].prix_api.devise modeles[].prix_api.entree_usd modeles[].prix_api.fast
modeles[].prix_api.portee modeles[].prix_api.seuil_long_contexte modeles[].prix_api.sortie_usd
modeles[].prix_api.source_url modeles[].prix_api.unite
modeles[].benchmarks[].date modeles[].benchmarks[].domaine modeles[].benchmarks[].effort_mesure modeles[].benchmarks[].nom
modeles[].benchmarks[].source modeles[].benchmarks[].unite modeles[].benchmarks[].url modeles[].benchmarks[].valeur
modeles[].benchmarks[].verifie
modeles[].points_forts[].date modeles[].points_forts[].source modeles[].points_forts[].url modeles[].points_forts[].verifie
modeles[].points_faibles[].date modeles[].points_faibles[].source modeles[].points_faibles[].url
modeles[].points_faibles[].verifie
modeles[].sources[].date modeles[].sources[].libelle modeles[].sources[].officielle modeles[].sources[].url
modeles[].sources_champs.*.date_lecture modeles[].sources_champs.*.url
modeles[].efforts[].effort modeles[].efforts[].defaut modeles[].efforts[].usage modeles[].efforts[].effet_effort
modeles[].tarifs_credits.cache_lu modeles[].tarifs_credits.date modeles[].tarifs_credits.entree
modeles[].tarifs_credits.sortie modeles[].tarifs_credits.unite modeles[].tarifs_credits.url
""".split())
# Rattachements de l'instance (classe P) : seules sentinelles fiables. Les parts S privées (corps d'une méthode, notes,
# extraits) recoupent légitimement des champs communs (la syntaxe d'une méthode est tirée de son corps).
PERSONNEL_MODELES = set("""
executants_operer modeles[].statut_usage modeles[].constats_internes modeles[].sources_internes
modeles[].efforts[].recommandation_operer modeles[].forfait.jauges_operer forfaits.*.source_interne forfaits.*.jauges_operer
""".split())
# En-tête d'une méthode : identité, produits, vérification et sources ; le corps (description rédigée) est privé en L2.
PUBLIC_METHODES = {"id", "nom", "produits", "verifie_le", "versions", "versions.*", "certitude", "sources",
                   "sources[].url", "sources[].libelle", "sources[].officielle"}
TAILLE_SENTINELLE = 24  # un texte privé plus court (verdict, nom de forfait) n'est pas une sentinelle fiable


def _jetons(chemin) -> list[str]:
    """`modeles[].sources_champs.*.url` ou chemin réel `["modeles", 0, "sources_champs", "prix", "url"]` → jetons."""
    if isinstance(chemin, str):
        return [j for j in re.split(r"\.|(\[\])", chemin) if j]
    return ["[]" if isinstance(c, int) else str(c) for c in chemin]


def _correspond(motif: list[str], jetons: list[str]) -> bool:
    return len(motif) == len(jetons) and all(m == j or (m == "*" and j != "[]") for m, j in zip(motif, jetons))


def _public(motifs: list[list[str]], jetons: list[str]) -> bool:
    return any(_correspond(m, jetons) for m in motifs)


def _a_descendant(motifs: list[list[str]], jetons: list[str]) -> bool:
    return any(len(m) > len(jetons) and _correspond(m[:len(jetons)], jetons) for m in motifs)


def _scinder(valeur, motifs: list[list[str]], chemin: list, pub: dict, priv: dict) -> None:
    jetons = _jetons(chemin)
    if chemin and _public(motifs, jetons):
        _placer(pub, chemin, valeur)
        return
    if isinstance(valeur, dict) and valeur and (not chemin or _a_descendant(motifs, jetons)):
        for k, v in valeur.items():
            _scinder(v, motifs, chemin + [k], pub, priv)
        return
    if isinstance(valeur, list) and valeur and _a_descendant(motifs, jetons):
        for i, v in enumerate(valeur):
            _scinder(v, motifs, chemin + [i], pub, priv)
        return
    _placer(priv, chemin, valeur)


def _placer(arbre: dict, chemin: list, valeur) -> None:
    noeud = arbre
    for cle in chemin[:-1]:
        noeud = noeud.setdefault(f"#{cle}" if isinstance(cle, int) else cle, {})
    noeud[f"#{chemin[-1]}" if isinstance(chemin[-1], int) else chemin[-1]] = valeur


def scinder(doc, public: set[str]) -> tuple[dict, dict]:
    """(part publique, part privée) d'un document ; les membres de liste sont repérés `#<indice>` dans chaque part."""
    pub: dict = {}
    priv: dict = {}
    _scinder(doc, [_jetons(c) for c in sorted(public)], [], pub, priv)
    return pub, priv


def recomposer(pub: dict, priv: dict):
    """Inverse de `scinder` : fusion des deux parts, listes rétablies dans l'ordre de leurs indices."""
    def fusion(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            sortie = dict(a)
            for k, v in b.items():
                sortie[k] = fusion(sortie[k], v) if k in sortie else v
            return sortie
        return b if a is None else a

    def figer(v):
        if isinstance(v, dict):
            if v and all(isinstance(k, str) and k.startswith("#") and k[1:].isdigit() for k in v):
                return [figer(v[k]) for k in sorted(v, key=lambda k: int(k[1:]))]
            return {k: figer(x) for k, x in v.items()}
        return v
    return figer(fusion(pub, priv))


def iso(valeur):
    """Dates YAML (`2026-10-20` lu comme date) → chaînes ISO : les parts se sérialisent en JSON sans perte de valeur."""
    if isinstance(valeur, (dt.date, dt.datetime)):
        return valeur.isoformat()
    if isinstance(valeur, dict):
        return {k: iso(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [iso(v) for v in valeur]
    return valeur


def lire_modele(chemin: Path) -> dict:
    return iso(yaml.safe_load(chemin.read_text(encoding="utf-8")) or {})


def lire_methode(chemin: Path) -> dict:
    """Une méthode : en-tête YAML entre `---` et corps Markdown (`corps`)."""
    texte = chemin.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n?(.*)\Z", texte, re.S)
    if not m:
        raise ValueError(f"{chemin.name}: en-tête YAML absent")
    entete = yaml.safe_load(m.group(1)) or {}
    if not isinstance(entete, dict) or "corps" in entete:
        raise ValueError(f"{chemin.name}: en-tête invalide")
    return iso({**entete, "corps": m.group(2)})


def scinder_sources(depot: Path) -> tuple[dict, dict]:
    """Parts publique et privée de `kb-modeles/*.yaml` (sauf README) et `kb-methodes/*.md`, par fichier relatif au dépôt.
    `forfaits.yaml` est privé entier en L2 (classe S : tarifs publics et rattachements de compte mêlés)."""
    publique: dict[str, dict] = {}
    privee: dict[str, dict] = {}
    for chemin in sorted((depot / "kb-modeles").glob("*.yaml")):
        rel = chemin.relative_to(depot).as_posix()
        doc = lire_modele(chemin)
        pub, priv = ({}, doc) if chemin.name == "forfaits.yaml" else scinder(doc, PUBLIC_MODELES)
        publique[rel], privee[rel] = pub, priv
    for chemin in sorted((depot / "kb-methodes").glob("*.md")):
        rel = chemin.relative_to(depot).as_posix()
        publique[rel], privee[rel] = scinder(lire_methode(chemin), PUBLIC_METHODES)
    return publique, privee


def textes_prives(privee: dict) -> list[str]:
    """Textes des rattachements personnels (P) de la part privée, assez longs pour servir de sentinelle."""
    vus: set[str] = set()
    motifs = [_jetons(c) for c in sorted(PERSONNEL_MODELES)]

    def chercher(v, chemin: list):
        if chemin and any(len(m) <= len(chemin) and _correspond(m, chemin[:len(m)]) for m in motifs):
            parcourir(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                chercher(x, chemin + (["[]"] if k.startswith("#") and k[1:].isdigit() else [k]))

    def parcourir(v):
        if isinstance(v, str):
            for ligne in v.splitlines():
                ligne = ligne.strip()
                if len(ligne) >= TAILLE_SENTINELLE and " " in ligne:
                    vus.add(ligne)
        elif isinstance(v, dict):
            for x in v.values():
                parcourir(x)
        elif isinstance(v, list):
            for x in v:
                parcourir(x)
    for rel, doc in privee.items():
        if rel.startswith("kb-modeles/"):
            chercher(doc, [])
    return sorted(vus)
