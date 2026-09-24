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
| 1 | Modèle et effort | Choisir le modèle et le niveau d'effort selon la tâche, et le mesurer | terminé le 24/09 |
| 2 | Le contexte | Savoir ce que le modèle voit (CLAUDE.md, mémoires, fichiers, compactage) | terminé le 24/09 |
| 3 | Écrire une consigne | Rédiger une mission sans place pour l'interprétation | terminé le 24/09 |
| 4 | Outils et MCP | Comprendre le choix d'un outil par un agent ; brancher un MCP | terminé le 24/09 |
| 5 | Skills et hooks | Automatiser un comportement : skill ou hook | prochain |
| 6 | Vérifier l'IA | Repérer une hallucination, faire recouper, audit croisé Claude ↔ Codex | à venir |

## Acquis

Un point passe ici après deux réussites à des jours différents. Avant ça, il reste en
consolidation (D67 amendée).

Aucun pour l'instant : tous les points ci-dessous n'ont été vus qu'une fois, le 24/09.

## En consolidation

- **Quand monter l'effort** [observé : exercice 1.3, 24/09] : l'effort haut sert quand le modèle
  doit découvrir quelque chose qu'il ne sait pas (bug intermittent) ; une consigne claire, sans rien
  à découvrir, n'en a pas besoin. Formulé par Sylvain lui-même, avec une justification correcte.
- **Lire l'effort réel d'une session** [observé : exercice 1.4, 24/09] : `/effort status` (et non
  `/effort` seul, qui n'affiche que la syntaxe).
- **Les quatre questions d'une consigne** [observé : module 3, 24/09] : but (l'état voulu, pas
  l'action ni la méthode), contraintes (vérifiables après coup), fini quand, format de réponse.
  Exercice réussi en fill-in-the-blank après une première tentative trop abstraite.
- **Une règle durable va dans `CLAUDE.md`, pas dans la conversation** [observé : exercice 2.1,
  24/09] : ce qui n'est dit qu'en conversation peut disparaître à la compaction.
- **`CLAUDE.md` sert aux règles permanentes, pas à l'état d'une tâche** [observé : pratique sur
  herbin-mint, 24/09] : il est relu à chaque séance, pour toujours ; y stocker « où j'en étais »
  avant un `/clear` le fait grossir sans fin. L'état d'un travail va dans un rapport daté, lu une
  fois à la demande (réflexe déjà appliqué aux rapports D63 de delta-ia).

## En cours

- Modules 1, 2, 3 et 4 terminés le 24/09, en une seule séance, avec deux missions réelles
  (pratique /compact sur herbin-mint, relecture d'un prompt d'automatisation avant envoi). Module 5
  (skills et hooks) à ouvrir à la prochaine séance, après un rappel rapide des points en
  consolidation ci-dessus.

## Adoptions

Entrées de la base de référence que Sylvain dit utiliser désormais au quotidien (D67). Seule sa
déclaration compte : un exercice réussi va dans le journal, pas ici. L'identifiant est celui que
donne `fiche_reference`.

| Id de l'entrée | Date | Nature |
|---|---|---|

## Points à travailler

- **L'effort traité comme une valeur par défaut** [observé : exercice 1.1] : le modèle varie selon
  la tâche, l'effort presque pas (« moyen » sur 3 tâches sur 4). Or « moyen » est justement le
  défaut d'Opus 5.5 : le laisser revient à ne pas choisir.
- **Débogage d'un non-déterminisme sous-dimensionné** [observé : 1.1 b] : c'est la tâche qui
  gagne le plus à un effort élevé (élimination d'hypothèses), et elle a été mise en « moyen ».
- **Effort sur Haiku 4.5** [observé : 1.1 c] : Haiku 4.5 n'a pas de niveaux d'effort (l'API
  refuse le paramètre sur ce modèle) ; « Haiku moyen » n'est pas un réglage possible.
- **Exercice 1.2 trop technique** [observé] : l'exercice portait sur un piège bash que Sylvain
  n'avait pas les moyens de juger ; il n'a pas pu comparer les réponses. Ce n'est pas une lacune de
  sa part mais un défaut de conception : les exercices doivent porter sur un domaine qu'il peut
  évaluer lui-même.
- **Choisir `/compact` par crainte de perdre le contexte** [observé : exercice 2.3] : le choix
  devrait dépendre de la suite (même mission ou nouvelle), pas de la peur. Sylvain a lui-même noté
  que les rapports écrits gardent l'essentiel ; il reste à en tirer la conséquence (`/clear` en fin
  de mission, l'ancienne conversation restant accessible par `/resume`).
- **Justifications absentes** [observé : 1.1] : les choix ont été donnés sans la phrase de
  justification demandée.

## Journal des séances

| Date | Module | Exercice | Résultat | Nature |
|---|---|---|---|---|
| 2026-09-24 | 1 | 1.1 prédiction modèle et effort sur 4 tâches | 2 choix justes (a, d), 1 sous-dimensionné (b : Opus moyen au lieu de high/xhigh), 1 impossible (c : effort sur Haiku 4.5) ; justifications absentes | [observé] |
| 2026-09-24 | 1 | 1.2 mesure `claude -p --effort low` / `high`, après contrôle que `CLAUDE_CODE_EFFORT_LEVEL` est vide (D67) | mesure lancée par le professeur : réponses quasi identiques, `high` n'ajoute qu'un cas rare (sous-shell). Prédiction « pareille » juste mais pour une raison fausse (confusion entre la variable d'effort et celle de la question) ; exercice non compris, trop technique | [observé] |
| 2026-09-24 | 1 | 1.3 choisir l'effort entre renommer 30 photos et un bug intermittent de Carnet | réussi : effort haut sur le bug, « il doit découvrir quelque chose qu'il ne sait pas », rien à découvrir dans un ordre clair | [observé] |
| 2026-09-24 | 1 | 1.4 lire l'effort réel d'une session Claude Code | réussi après une indication : `/effort status` affiche « auto (currently medium) », soit le défaut du modèle, aucun niveau choisi | [observé] |
| 2026-09-24 | 2 | 2.1 règle « ne touche pas à `data/` » perdue après compaction : pourquoi, et où l'écrire | réussi : `CLAUDE.md`, qui survit aux compactions ; nuance apportée : consigne ≠ verrou (permissions, module 5) | [observé] |
| 2026-09-24 | 2 | 2.2 lire `/context` dans herbin-trading | fait (capture iPhone) : 75 % utilisé (749k sur 1M), dont 71,6 % de messages ; outils, skills, prompt système et mémoires ≈ 3 % | [observé] |
| 2026-09-24 | 2 | 2.3 `/clear` ou `/compact` en fin de tâche | partiel : `/compact` par crainte de perdre le contexte, mais bonne intuition sur les rapports écrits ; critère corrigé : même mission → `/compact` ciblé, mission finie → rapport puis `/clear <nom>` | [observé] |
| 2026-09-24 | 3 | 3.1 repérer ce qui manque dans « corrige le bug d'affichage des séries » | 3/4 justes (contraintes, fin, format) ; « but » confondu avec l'action : « corrige le bug » répète la consigne, ne dit pas pourquoi ni ce que le bon état donnerait à voir | [observé] |
| 2026-09-24 | 3 | 3.2 réécrire « corrige le bug d'affichage » en consigne complète | 2/4 : « fini quand » net et vérifiable (formats identiques sur toutes les séances) ; but implicite correct ; contraintes et format de réponse absents ; nuance signalée : consigne prescrit la méthode (copier le format de la 1ère série) au lieu de décrire l'état voulu, en supposant sans le dire que la 1ère série est la bonne référence | [observé] |
| 2026-09-24 | 3 | 3.3 compléter la consigne (contrainte + format), en fill-in-the-blank après une première consigne trop abstraite | réussi : contrainte précise et vérifiable (FC par série) ; format encore un peu ouvert (« la différence » sans préciser la forme) | [observé] |
| 2026-09-24 | 2 | Mise en pratique réelle sur herbin-mint : `/context` (36 %) puis `/compact` x2 | 362,6k → 63,9k jetons (356k économisés, 36 % → 6 %) ; question posée sur `CLAUDE.md` comme mémoire avant `/clear`, corrigée vers le réflexe rapport daté (pattern D63 delta-ia) | [observé] |
| 2026-09-24 | 3 | Application réelle : relecture d'un prompt d'automatisation (cron /delta + $delta) avant envoi à herbin-mint | Sylvain avait bien repris la contrainte D21 (ordre strict) depuis SPEC.md ; grille des 4 questions appliquée par le professeur : fini quand et format absents, méthode (IDs de session figés) prescrite au lieu du but. Blocage trouvé en croisant SPEC.md §10 (cron hors périmètre v1) et §3 (`disable-model-invocation: true`) : proposition reformulée et envoyée directement à la session delta-ia pour décision, plutôt qu'exécutée sur herbin-mint | [observé] |
| 2026-09-24 | 4 | 4.1 lire `/mcp` et dire ce qui sert vraiment dans la session | réussi : 7 connectés, 1 seul utilisé (delta-ia) ; confirme la piste 9 de Delta (Gmail/Drive/Calendar/Canva/GoDaddy connectés sans servir dans Claude Code) | [observé] |
