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
