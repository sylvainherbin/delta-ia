# P15 — choix d'adresse à examiner après déploiement par le chef

Aucune pose n'est faite et aucune configuration cliente réelle n'est lue. Les données du checkout servent aux recettes locales.
Les adresses ci-dessous sont des choix pour le chef, pas des adresses qualifiées sur le service actuellement publié.

| Besoin du client | Adresse proposée après déploiement |
|---|---|
| Tous les outils avec noms par service | `https://delta-mcp-ruddy.vercel.app/mcp?surface=service` |
| Recherche, détail et versions seulement | `https://delta-mcp-ruddy.vercel.app/mcp?surface=reference` |
| Retour au catalogue historique | `https://delta-mcp-ruddy.vercel.app/mcp` |

La preuve est `mcp/preuve-p15.sh`, lancée par le verrou selon `mcp/mesures/2026-10-28-p15.md` : une archive temporaire
de main devient rouge, puis le serveur de la branche est exercé en boucle locale. Les six anciens appels restent
valides sur les trois surfaces ; le catalogue réduit conserve les résultats des douze recherches, leurs fiches
complètes et les versions. Il ne couvre pas la découverte des outils de veille, essais ou ajouts récents.

La grille P15 retient **R172 : PARTIEL** : les surfaces préfixées sont optionnelles ; `/mcp` conserve le catalogue
historique, aucun déploiement ni client installé utilisant ces adresses n'est qualifié. Les tests du dépôt
ne suffisent pas à passer cette ligne à FAIT.

Après P15b, les descriptions et paramètres des surfaces `service` et `reference` sont éprouvés en français et
en anglais, ainsi que les erreurs et le renvoi de consultation (`P15b R172` dans `mcp/test/mcp.test.js`). Les
descriptions de `reference` renvoient au catalogue complet pour les fonctions absentes. Le Bureau garde
3 fiches par défaut ; `consulter <texte> --limite N` accepte explicitement un entier de 1 à 5.

`mcp/mesurer-surface.js` est une **mesure descriptive, pas un garde-fou de régression** : aucun seuil de 10/12 ni
zéro perte à quatre fiches n'est imposé par son code de retour. Les tests de l'instrument et de conservation du
préfixe de `liste8` ont des assertions ; les chiffres de signal restent des observations sur le corpus fermé.
La recette écrit la nouvelle mesure dans `rapports/grilles-v2-p15/surface.json`, ignoré par git ; les instantanés
suivis restent historiques. La recette P15b est `bash mcp/preuve-p15b.sh`, sous le verrou dev avec un délai
d'au moins 3 600 secondes : quatre témoins rouges sur `5675a43e`, mutation détectée fr/en, puis tests ciblés verts.

Avant toute pose, le chef devra choisir le client concerné et contrôler son catalogue natif après reconnexion.
La recette HTTP suivante pourra seulement confirmer le catalogue du serveur déployé, sans appel de modèle :

```bash
~/.local/bin/verrou-tests-dev --depot "$PWD" --nom grilles-v2-p15-catalogue-deploye -- \
  curl --fail-with-body --silent --show-error --max-time 30 \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  'https://delta-mcp-ruddy.vercel.app/mcp?surface=reference'
```

Attendu après déploiement : exactement les trois noms `orqyra_ai_chercher_reference`, `orqyra_ai_fiche_reference`
et `orqyra_ai_etat_versions`. Cette commande n'a pas été exécutée par P15. Elle ne fournit pas la preuve d'usage
du catalogue dans Claude ou Codex. Aucun retrait définitif d'outil n'est proposé sur la seule absence d'appels W42/W43.
