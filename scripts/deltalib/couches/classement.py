"""Classement des champs de `docs/data` en couches (conception « Delta-IA en deux couches », annexe) : C commun, P personnel, S à scinder.

Chaque famille de fichiers porte la liste positive de ses chemins de champs normalisés : `*` pour une clé variable (id de
modèle, nom d'outil, ctx-id), `[]` pour un membre de liste. Un chemin absent de la table est inconnu : il n'est jamais
réputé commun (refusé à l'export, conservé localement). Un champ sous un conteneur P hérite de P. Un chemin classé dont
aucun descendant n'est listé est atomique (liste de textes, alias, carte de noms) : toute sa valeur prend sa classe.

Lot L1 (« projection commune conservatrice ») : seuls les champs C certains passent au commun. Les champs C « sous revue
du contenu » qui sont du texte libre (extraits, notes, points forts) sont mis en attente avec les textes S.
"""

from __future__ import annotations

import re

COMMUN, PERSONNEL, SCINDER, INCONNU = "C", "P", "S", "inconnu"

_TABLE = {
    "quotidien": {
        "C": "agent date elements[].certitude elements[].date_publication elements[].id elements[].ids_bruts "
             "elements[].kb_refs elements[].produit elements[].revision elements[].sources elements[].sources[].libelle "
             "elements[].sources[].officielle elements[].sources[].url elements[].type elements[].version genere_le perimetre",
        "P": "contexte_empreinte elements[].action elements[].action.description elements[].action.effort "
             "elements[].action.etapes elements[].contexte_sections elements[].contexte_sections.* "
             "elements[].contexte_sections.*.pourquoi elements[].contexte_sections.*.sha1 elements[].impact "
             "elements[].pour_toi elements[].projets_concernes",
        "S": "ecartes ecartes[].id ecartes[].raison elements elements[].resume elements[].titre sources_en_echec "
             "sources_en_echec[].erreur sources_en_echec[].id sources_en_echec[].partiel sources_en_echec[].url synthese",
    },
    "index_veille": {
        "C": "agent jours[].date jours[].genere_le maj_le perimetre",
        "P": "jours[].impact jours[].impact.faible jours[].impact.fort jours[].impact.moyen jours[].impact.nul",
        "S": "jours jours[].ecartes jours[].elements",
    },
    "etat": {
        # Fichier entier P : ses conteneurs de premier niveau suffisent, leurs descendants héritent.
        "P": "comptes instructions_globales mcp_claude_code outils pertinent_pour_profil releve_le",
    },
    "a_tester": {
        "C": "entrees[].categorie entrees[].date_ajout entrees[].id entrees[].nom entrees[].produit entrees[].usage "
             "entrees[].usage_nature",
        "P": "entrees entrees[].essai entrees[].pourquoi entrees[].verdict genere_le total tronque",
        "S": "entrees[].exemple",
    },
    "kb_catalogue": {
        "C": "categorie entrees[].categorie entrees[].description_source entrees[].gabarit entrees[].groupe entrees[].id "
             "entrees[].nom entrees[].origine entrees[].produit entrees[].retiree entrees[].sources entrees[].sources[].libelle "
             "entrees[].sources[].officielle entrees[].sources[].url entrees[].usage entrees[].usage_nature maj_le perimetre total",
        "P": "contexte_deprecies contexte_empreinte contexte_sections contexte_sections.* entrees[].contexte_empreinte "
             "entrees[].contexte_sections entrees[].contexte_sections.* entrees[].contexte_sections.*.pourquoi "
             "entrees[].contexte_sections.*.sha1 entrees[].recommandation entrees[].recommandation.pourquoi "
             "entrees[].recommandation.verdict entrees[].statut_usage",
        "S": "commentees entrees entrees[].commentee entrees[].description entrees[].disponibilite entrees[].exemple "
             "entrees[].exemple_impossible entrees[].exemple_origine entrees[].historique entrees[].historique[].avant "
             "entrees[].historique[].avant.exemple entrees[].historique[].avant.pourquoi entrees[].historique[].avant.verdict "
             "entrees[].historique[].avant[].affirmation entrees[].historique[].avant[].caduc_si "
             "entrees[].historique[].avant[].releve_le entrees[].historique[].avant[].source entrees[].historique[].changement "
             "entrees[].historique[].date entrees[].historique[].raison entrees[].maj_le entrees[].provenance "
             "entrees[].provenance[].affirmation entrees[].provenance[].caduc_si entrees[].provenance[].releve_le "
             "entrees[].provenance[].revoir_le entrees[].provenance[].source",
    },
    "reevaluations": {
        "P": "date id motif verdict_apres verdict_avant",
    },
    "methodes": {
        "C": "categorie entrees[].categorie entrees[].certitude entrees[].gabarit entrees[].id entrees[].maj_le entrees[].nom "
             "entrees[].origine entrees[].produit entrees[].produits entrees[].retiree entrees[].sources "
             "entrees[].sources[].libelle entrees[].sources[].officielle entrees[].sources[].url entrees[].usage "
             "entrees[].usage_nature entrees[].verifie_le entrees[].versions entrees[].versions.claude-code "
             "entrees[].versions.codex maj_le origine total",
        "P": "entrees[].recommandation entrees[].statut_usage",
        "S": "entrees entrees[].commentee entrees[].description entrees[].description_source entrees[].disponibilite "
             "entrees[].exemple entrees[].fichier_source",
    },
    "modeles": {
        "C": "categorie date_releve entrees[].effet_effort entrees[].effort entrees[].effort_defaut entrees[].id "
             "entrees[].modele entrees[].nom entrees[].usage maj_le modeles.*.aliases_defaut modeles.*.aliases_effort "
             "modeles.*.benchmarks modeles.*.benchmarks[].comparaisons modeles.*.benchmarks[].date "
             "modeles.*.benchmarks[].domaine modeles.*.benchmarks[].effort_mesure modeles.*.benchmarks[].extrait "
             "modeles.*.benchmarks[].nom modeles.*.benchmarks[].source modeles.*.benchmarks[].unite modeles.*.benchmarks[].url "
             "modeles.*.benchmarks[].valeur modeles.*.benchmarks[].verifie modeles.*.categorie modeles.*.certitude "
             "modeles.*.cutoff_connaissances modeles.*.date_releve modeles.*.date_sortie modeles.*.description_commune "
             "modeles.*.effort_defaut_detail modeles.*.effort_defaut_modele modeles.*.effort_defaut_portee modeles.*.executant "
             "modeles.*.famille modeles.*.fenetre_contexte_jetons modeles.*.fournisseur modeles.*.gabarit modeles.*.maj_le "
             "modeles.*.modele modeles.*.niveaux_effort_disponibles modeles.*.niveaux_effort_disponibles[].defaut "
             "modeles.*.niveaux_effort_disponibles[].effet_effort modeles.*.niveaux_effort_disponibles[].effort "
             "modeles.*.niveaux_effort_disponibles[].usage modeles.*.nom_modele modeles.*.origine modeles.*.points_faibles "
             "modeles.*.points_faibles[].date modeles.*.points_faibles[].extrait modeles.*.points_faibles[].source "
             "modeles.*.points_faibles[].texte modeles.*.points_faibles[].url modeles.*.points_faibles[].verifie "
             "modeles.*.points_forts modeles.*.points_forts[].date modeles.*.points_forts[].extrait "
             "modeles.*.points_forts[].source modeles.*.points_forts[].texte modeles.*.points_forts[].url "
             "modeles.*.points_forts[].verifie modeles.*.prix_api modeles.*.prix_api.batch modeles.*.prix_api.cache_ecrit_1h_usd "
             "modeles.*.prix_api.cache_ecrit_5m_usd modeles.*.prix_api.cache_lu_usd modeles.*.prix_api.devise "
             "modeles.*.prix_api.entree_usd modeles.*.prix_api.fast modeles.*.prix_api.note modeles.*.prix_api.portee "
             "modeles.*.prix_api.seuil_long_contexte modeles.*.prix_api.sortie_usd modeles.*.prix_api.source_url "
             "modeles.*.prix_api.unite modeles.*.produit modeles.*.produits modeles.*.retiree modeles.*.sortie_max_jetons "
             "modeles.*.sources modeles.*.sources[].date modeles.*.sources[].libelle modeles.*.sources[].officielle "
             "modeles.*.sources[].url modeles.*.sources_champs modeles.*.sources_champs.* "
             "modeles.*.sources_champs.*.date_lecture modeles.*.sources_champs.*.defaut modeles.*.sources_champs.*.efforts "
             "modeles.*.sources_champs.*.extrait modeles.*.sources_champs.*.modele modeles.*.sources_champs.*.url "
             "modeles.*.tarifs_credits modeles.*.tarifs_credits.cache_lu modeles.*.tarifs_credits.date "
             "modeles.*.tarifs_credits.entree modeles.*.tarifs_credits.extrait modeles.*.tarifs_credits.note "
             "modeles.*.tarifs_credits.sortie modeles.*.tarifs_credits.unite modeles.*.tarifs_credits.url "
             "modeles.*.usage_nature modeles.*.verifie_le origine schema_version total total_modeles",
        "P": "entrees[].recommandation entrees[].recommandation.natures_adaptees entrees[].recommandation.natures_deconseillees "
             "entrees[].recommandation.pourquoi entrees[].recommandation.verdict entrees[].recommandation.verdict_operer "
             "entrees[].recommandation_operer entrees[].recommandation_operer.natures_adaptees "
             "entrees[].recommandation_operer.natures_deconseillees entrees[].recommandation_operer.pourquoi "
             "entrees[].recommandation_operer.verdict forfaits.*.source_interne forfaits.*.source_interne.constat "
             "forfaits.*.source_interne.document forfaits.*.source_interne.releve_le modeles.*.constats_internes "
             "modeles.*.constats_internes[].constat modeles.*.constats_internes[].date modeles.*.constats_internes[].source "
             "modeles.*.constats_internes[].titre modeles.*.niveaux_effort_disponibles[].verdict_operer "
             "modeles.*.sources_internes modeles.*.sources_internes[].constat modeles.*.sources_internes[].date "
             "modeles.*.sources_internes[].document modeles.*.statut_usage",
        "S": "entrees entrees[].cout_quota entrees[].cout_quota.niveau entrees[].cout_quota.poids_relatif "
             "entrees[].cout_quota.resume entrees[].description entrees[].description_source entrees[].exemple forfaits "
             "forfaits.* forfaits.*.abonnement_mensuel_usd forfaits.*.credits_api_mensuels_inclus_usd forfaits.*.date_releve "
             "forfaits.*.fournisseur forfaits.*.id forfaits.*.jauges_operer forfaits.*.jauges_operer[].cle "
             "forfaits.*.jauges_operer[].description forfaits.*.jauges_operer[].fenetre forfaits.*.jauges_operer[].groupe "
             "forfaits.*.jauges_operer[].libelle forfaits.*.jauges_operer[].plafond_relatif_pct forfaits.*.nom "
             "forfaits.*.regles_quota forfaits.*.source_tarif forfaits.*.source_tarif.date_lecture "
             "forfaits.*.source_tarif.extrait forfaits.*.source_tarif.url forfaits.*.sources forfaits.*.sources[].date "
             "forfaits.*.sources[].libelle forfaits.*.sources[].officielle forfaits.*.sources[].url modeles modeles.* "
             "modeles.*.commentee modeles.*.disponibilite modeles.*.executants_operer modeles.*.fichier_source "
             "modeles.*.forfait modeles.*.forfait.fenetre_5h modeles.*.forfait.fenetre_semaine modeles.*.forfait.groupe_quota "
             "modeles.*.forfait.id modeles.*.forfait.jauges_operer modeles.*.forfait.nom modeles.*.forfait.plafonds_et_regles "
             "modeles.*.forfaits_applicables modeles.*.forfaits_applicables[].abonnement_mensuel_usd "
             "modeles.*.forfaits_applicables[].credits_api_mensuels_inclus_usd modeles.*.forfaits_applicables[].fournisseur "
             "modeles.*.forfaits_applicables[].id modeles.*.forfaits_applicables[].jauges_operer "
             "modeles.*.forfaits_applicables[].jauges_operer[].cle modeles.*.forfaits_applicables[].jauges_operer[].description "
             "modeles.*.forfaits_applicables[].jauges_operer[].fenetre modeles.*.forfaits_applicables[].jauges_operer[].groupe "
             "modeles.*.forfaits_applicables[].jauges_operer[].libelle "
             "modeles.*.forfaits_applicables[].jauges_operer[].plafond_relatif_pct modeles.*.forfaits_applicables[].nom "
             "modeles.*.forfaits_applicables[].regles_quota modeles.*.modele_operer "
             "modeles.*.niveaux_effort_disponibles[].cout_quota_niveau modeles.*.niveaux_effort_disponibles[].cout_quota_poids",
    },
    "noms": {"C": "*"},
    "recent": {
        "C": "entrees entrees[].categorie entrees[].date_ajout entrees[].id entrees[].nom entrees[].produit entrees[].usage "
             "entrees[].usage_nature fenetre_jours genere_le plus_ancienne total tronque",
        "P": "entrees[].verdict",
        "S": "entrees[].exemple",
    },
    "recherche": {
        "C": "elements elements[].date elements[].id elements[].perimetre elements[].titre genere_le sources sources.* "
             "sources.*.jours sources.*.statut statut total",
        "P": "elements[].impact",
        "S": "elements[].texte raison sources.*.raison",
    },
    "semaine": {
        "C": "au base_ajoutees base_ajoutees[].categorie base_ajoutees[].date_ajout base_ajoutees[].id base_ajoutees[].nom "
             "base_ajoutees[].perimetre base_ajoutees[].produit base_ajoutees[].usage d71[].certitude d71[].date_publication "
             "d71[].id d71[].jour d71[].perimetre d71[].produit d71[].titre d71[].version du elements[].certitude "
             "elements[].date_publication elements[].id elements[].jour elements[].perimetre elements[].produit "
             "elements[].titre elements[].version genere_le semaine sources sources.* sources.*.jours sources.*.statut statut",
        "P": "base_ajoutees[].verdict base_verdicts base_verdicts[].categorie base_verdicts[].date base_verdicts[].exemple "
             "base_verdicts[].exemple_origine base_verdicts[].id base_verdicts[].nom base_verdicts[].perimetre "
             "base_verdicts[].pourquoi base_verdicts[].produit base_verdicts[].usage base_verdicts[].verdict "
             "base_verdicts[].verdict_apres base_verdicts[].verdict_avant d71[].action d71[].impact elements[].action "
             "elements[].impact",
        "S": "base_ajoutees[].exemple base_ajoutees[].exemple_origine d71 elements raison sources.*.raison",
    },
    "index_semaine": {
        "C": "maj_le semaines semaines[].au semaines[].du semaines[].genere_le semaines[].semaine semaines[].statut",
        "P": "semaines[].base_verdicts",
        "S": "semaines[].base_ajoutees semaines[].d71 semaines[].elements",
    },
    "versions": {
        "C": "[].derniere_publiee [].outil [].source_derniere",
        "P": "[].detectee_le [].methode [].pertinent_pour_profil [].statut [].version",
        "S": "[].note",
    },
}

TABLE: dict[str, dict[str, str]] = {
    famille: {chemin: classe for classe, chemins in classes.items() for chemin in chemins.split()}
    for famille, classes in _TABLE.items()
}

# L1 : champs C « sous revue du contenu » (conception §1.3) en texte libre, mis en attente avec les textes S. Les valeurs
# numériques, dates, URL et identités de ces mêmes blocs restent communes.
EN_ATTENTE_L1 = {
    "modeles": {
        "modeles.*.description_commune", "modeles.*.benchmarks[].extrait", "modeles.*.benchmarks[].comparaisons",
        "modeles.*.points_forts[].texte", "modeles.*.points_forts[].extrait",
        "modeles.*.points_faibles[].texte", "modeles.*.points_faibles[].extrait",
        "modeles.*.prix_api.note", "modeles.*.tarifs_credits.note", "modeles.*.tarifs_credits.extrait",
        "modeles.*.sources_champs.*.extrait", "modeles.*.effort_defaut_detail",
    },
}

PERIMETRES_VEILLE = ("claude", "openai", "actu")
PERIMETRES_KB = ("claude", "openai")
RE_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
RE_SEMAINE = re.compile(r"\d{4}-W\d{2}")


def famille_de(rel: str) -> str | None:
    """Famille d'un chemin relatif à `docs/data` (`claude/2026-10-22.json` → `quotidien`) ; None si inconnue."""
    parties = rel.split("/")
    nom = parties[-1]
    if len(parties) == 1:
        return {"etat.json": "etat", "versions.json": "versions", "recherche.json": "recherche"}.get(nom)
    if len(parties) == 2 and parties[0] in PERIMETRES_VEILLE:
        if nom == "index.json":
            return "index_veille"
        if nom.endswith(".json") and RE_JOUR.fullmatch(nom[:-5]):
            return "quotidien"
    if len(parties) == 2 and parties[0] == "semaine":
        if nom == "index.json":
            return "index_semaine"
        if nom.endswith(".json") and RE_SEMAINE.fullmatch(nom[:-5]):
            return "semaine"
    if len(parties) == 2 and parties[0] == "kb":
        return {"a-tester.json": "a_tester", "methodes.json": "methodes", "modeles.json": "modeles",
                "noms.json": "noms", "recent.json": "recent"}.get(nom)
    if len(parties) == 3 and parties[0] == "kb" and parties[1] in PERIMETRES_KB:
        if nom == "reevaluations.jsonl":
            return "reevaluations"
        if nom.endswith(".json"):
            return "kb_catalogue"
    return None


def _a_descendants(table: dict[str, str], chemin: str) -> bool:
    return any(c.startswith(chemin + ".") or c.startswith(chemin + "[]") for c in table)


def _enfant(table: dict[str, str], parent: str, cle: str) -> str:
    """Chemin normalisé de `parent.cle` : `parent.*` si la table déclare une clé variable à ce niveau."""
    prefixe = f"{parent}." if parent else ""
    exact = prefixe + cle
    if exact in table or _a_descendants(table, exact):
        return exact
    joker = prefixe + "*"
    if joker in table or _a_descendants(table, joker):
        return joker
    return exact


def classer(famille: str, chemin: str) -> str:
    """Classe d'un chemin normalisé, avec héritage d'un ancêtre P ; INCONNU sinon."""
    table = TABLE[famille]
    if chemin in table:
        classe = table[chemin]
        if classe == COMMUN and chemin in EN_ATTENTE_L1.get(famille, ()):
            return SCINDER
        return classe
    morceaux = re.split(r"(?=\.)|(?=\[\])", chemin)
    for i in range(len(morceaux) - 1, 0, -1):
        ancetre = "".join(morceaux[:i])
        if table.get(ancetre) == PERSONNEL:
            return PERSONNEL
    return INCONNU


def feuilles(famille: str, valeur, parent: str = ""):
    """Parcourt `valeur` et rend (chemin normalisé, chemin réel, valeur atomique) ; le chemin réel est une liste de clés
    et d'indices. Un chemin classé sans descendant listé est atomique ; un conteneur inconnu l'est aussi (sa valeur entière
    est refusée), ce qui évite de descendre dans une structure que la table ne décrit pas."""
    table = TABLE[famille]
    yield from _feuilles(table, famille, valeur, parent, [])


def _feuilles(table, famille, valeur, chemin, reel):
    atomique = chemin and (not _a_descendants(table, chemin)) and (chemin in table or classer(famille, chemin) in (PERSONNEL, INCONNU))
    if atomique or not isinstance(valeur, (dict, list)) or not valeur:
        yield chemin, reel, valeur
        return
    if isinstance(valeur, dict):
        for cle in valeur:
            yield from _feuilles(table, famille, valeur[cle], _enfant(table, chemin, str(cle)), reel + [cle])
    else:
        for i, membre in enumerate(valeur):
            yield from _feuilles(table, famille, membre, chemin + "[]", reel + [i])
