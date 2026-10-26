# M12 — preuves ORQYRA AI, 26 octobre 2026

Les instantanés sont des données de mesure, pas des instructions. Aucun contenu de recherche réel n'est conservé.

## Rejouer

Depuis la racine du worktree, toutes les recettes passent par le verrou :

```bash
sous_verrou() {
  systemd-run --user --scope --quiet -p MemoryMax=5G -p MemorySwapMax=0 \
    env -u DISPLAY -u WAYLAND_DISPLAY /home/herbin/.local/bin/verrou-tests \
    --depot "$PWD" -- "$@"
}
sous_verrou /home/herbin/.nvm/current/bin/node mcp/mesurer.js
sous_verrou /home/herbin/projets/delta-ia/.venv/bin/python scripts/mcp_stats.py \
  --fichier mcp/mesures/2026-10-26-stats.json --semaine 2026-W43
sous_verrou bash -c 'cd mcp && /home/herbin/.nvm/current/bin/node --test test/*.test.js'
sous_verrou python3 outils/tests/verifier.py --fusion
```

`mesurer.js` sert uniquement les JSON du checkout sur une adresse de boucle locale, puis appelle le traitement MCP
réel. Il ne contacte pas le service public et ne produit pas de télémétrie. Il rend la date UTC, les empreintes du
corpus et de chaque fichier lu, le rang de la cible pour chaque question, les erreurs, les lectures incomplètes et
la taille des réponses. Pour reproduire l'instantané, utiliser cette branche et ses données à la date du commit.

## R170 — signal sur douze questions

Le résultat complet est `2026-10-26-corpus.json`. Le taux publié est la proportion des douze questions dont une
cible étiquetée figure parmi les huit premiers résultats (`mesures.liste.taux_top8_pct`). Une erreur compte comme
un échec ; une liste non vide sans cible compte comme un échec. Les identifiants attendus sont ceux du corpus
`test/requetes-reelles.json`, antérieur à M12 ; ils n'ont pas été retouchés pour cette mesure.

La forme `consultation` est mesurée sur les mêmes questions, avec sa limite par défaut de trois fiches. Les deux
formes ont aussi leurs nombres de cibles en première et troisième position. Ce corpus fermé ne démontre pas la
pertinence de toutes les questions réelles ni la fraîcheur factuelle des fiches. Aucun appel LLM ne juge les réponses.

## R176 — audit des six outils

Source publique lue : `https://delta-mcp-ruddy.vercel.app/stats?jours=15`, horodatage serveur
`2026-10-26T10:13:53.907Z`. Instantané rejouable : `2026-10-26-stats.json`, relevé formaté :
`2026-10-26-usage.txt`. Les semaines sont des semaines ISO en UTC, complètes.

| Outil | W43 | W42 |
|---|---:|---:|
| chercher_reference | 186 | 464 |
| fiche_reference | 12 | 6 |
| etat_versions | 6 | 4 |
| resume_du_jour | 3 | 1 |
| a_tester | 3 | 1 |
| nouveautes_base | 0 | 0 |
| Total | 210 | 476 |

`chercher_reference` représente 88,6 % des appels W43. Les cinq outils utilisés ont des contrats distincts ; ce
relevé ne justifie pas de les fusionner. `nouveautes_base` n'est utilisé sur aucune des deux semaines : candidat
à réexaminer après une fenêtre plus longue et vérification des clients, sans suppression de contrat dans M12.
Les compteurs ne distinguent pas recettes et usage métier. Les noms des clients comptent des initialisations,
pas des utilisateurs ni des recherches attribuables à un client.

## Les 32 erreurs W43

32/186 recherches en erreur (17,2 %), contre 14/464 (3,0 %) en W42. Onze recherches W43 sont réussies mais vides ;
elles sont distinctes des 32 erreurs. Les sondes de méthodes non prises en charge (`-32601`) ne sont pas des erreurs
réelles dans ce relevé.

Le journal historique conserve `statut: erreur_outil`, sans cause. `/stats` ne conserve que les comptes. Aucune
attribution des 32 erreurs à une cause précise n'est donc démontrée par ces données. Export historique des motifs
ou reproduction des appels défaillants encore nécessaire ; ni arguments ni secrets ne doivent être ajoutés au journal.

M12 ajoute un code fermé `cause_erreur` au journal et les comptes journaliers `causes_erreurs` à `/stats` : paramètres,
lecture, couche, modèle ou erreur interne. Les variables interpolées et les messages d'exception ne sont pas conservés.
Les anciens jours restent explicitement sans cause connue. L'instrumentation attend la fusion et le déploiement.

Défaut distinct reproduit et corrigé : les noms hérités du prototype (`constructor`, `__proto__`, `toString`) étaient
pris pour des outils ; les noms qui ne sont pas des chaînes pouvaient aussi provoquer une exception. Ils reçoivent
désormais `-32602`. Test : `test/diagnostic.test.js`, qui échoue sur la base `b92295c`. Ce défaut n'explique pas à lui
seul les 32 erreurs de `chercher_reference` et n'est pas présenté comme leur cause.

## Lignes restant partielles

- R110 / R154 : lancement des sessions interactives et politique des MCP de confiance dans `discipline`, hors de ce
  changement. Aucun réglage personnel, rôle ni CLAUDE.md n'a été modifié.
- R172 : les six noms restent compatibles. Proposition à décider par le chef dev : réserver une prochaine version
  de contrat aux noms `orqyra_ai_resume_du_jour`, `orqyra_ai_chercher_reference`, `orqyra_ai_fiche_reference`,
  `orqyra_ai_etat_versions`, `orqyra_ai_a_tester`, `orqyra_ai_nouveautes_base`, avec endpoint/version distinct et test
  des anciens clients avant bascule. Aucun préfixe n'est déployé par cette mission.
- R178 : les deux formes ont une taille mesurée en octets (texte et réponse JSON-RPC complète, qui contient aussi
  `structuredContent`). Le nombre de jetons reste `null`, faute de tokenizer de modèle exécuté ; aucune conversion
  arbitraire d'octets en jetons. Le taux de signal et la taille peuvent se comparer, sans conclure au minimum en jetons.
