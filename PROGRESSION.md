# PROGRESSION — Formation IA de Sylvain

Ce fichier suit la formation pratique de Sylvain à Claude, Claude Code, ChatGPT et Codex, donnée
par une session Claude Code dans le rôle de professeur, à partir des données de Delta. Il est tenu
par cette session et mis à jour après chaque séance. Les agents de Delta peuvent le lire pour
doser la profondeur de `pour_toi` et de `action` (D67). Ce fichier est sans effet sur `impact` et
sur le choix des éléments ; il n'a pas d'empreinte, et la base de référence ne le lit pas. Seule la
session professeur y écrit ; Dev-delta le commite à part.

Légende (identique à `CONTEXTE.md`) : **[observé]** constaté sur un exercice ou une sortie ·
**[déduit]** conclu à partir d'observations · **[déclaré]** dit par Sylvain · **[inconnu]** pas
encore évalué.

Ce dépôt est public : on n'inscrit ici que du technique, rien de personnel ni de secret.

---

## Programme

| # | Module | Objectif | État |
|---|---|---|---|
| 1 | Modèle et effort | Choisir le modèle et le niveau d'effort selon la tâche, et le mesurer | en cours |
| 2 | Le contexte | Savoir ce que le modèle voit (CLAUDE.md, mémoires, fichiers, compactage) | à venir |
| 3 | Écrire une consigne | Rédiger une mission sans place pour l'interprétation | à venir |
| 4 | Outils et MCP | Comprendre le choix d'un outil par un agent ; brancher un MCP | à venir |
| 5 | Skills et hooks | Automatiser un comportement : skill ou hook | à venir |
| 6 | Vérifier l'IA | Repérer une hallucination, faire recouper, audit croisé Claude ↔ Codex | à venir |

## Acquis

Aucun pour l'instant [inconnu].

## En cours

- **Module 1, modèle et effort** : exercices 1.1 (prédiction) et 1.2 (mesure `--effort low`
  contre `--effort high`) donnés le 24/09, sans réponse à ce jour.

## Adoptions

Entrées de la base de référence que Sylvain dit utiliser désormais au quotidien (D67). Seule sa
déclaration compte : un exercice réussi va dans le journal, pas ici. L'identifiant est celui que
donne `fiche_reference`.

| Id de l'entrée | Date | Nature |
|---|---|---|

## Points à travailler

Aucun relevé pour l'instant [inconnu].

## Journal des séances

| Date | Module | Exercice | Résultat | Nature |
|---|---|---|---|---|
| 2026-09-24 | 1 | 1.1 prédiction modèle et effort sur 4 tâches | donné, en attente | — |
| 2026-09-24 | 1 | 1.2 mesure `claude -p --effort low` / `high`, après contrôle que `CLAUDE_CODE_EFFORT_LEVEL` est vide (D67) | donné, en attente | — |
