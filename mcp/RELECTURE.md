# Relecture des outils du connecteur MCP

Étape de toute mission qui modifie `mcp/api/mcp.js` : outils, schémas, titres, descriptions, réponses ou erreurs.
Hors de ces missions, rien à faire. Origine : idée de Sylvain du 11/10/2026, jugée par JUGER
(`run_20261011-182228_a7b4a5`), conçue par la mission m-9871226c4940.

## Source

Le plugin `mcp-server-dev` d'Anthropic (marketplace `claude-plugins-official`, entrée Delta
`claude-code-plugins-mcp-server-dev`). Trois skills de construction (`build-mcp-server`, `build-mcp-app`,
`build-mcpb`) : choix du déploiement, échafaudage, authentification, MCPB, widgets. Pour un serveur déjà en
service comme celui-ci, seule la référence `skills/build-mcp-server/references/tool-design.md` sert à la
relecture ; le reste ne s'applique pas (déploiement Vercel, sans jeton ni écriture par D61).

Lecture sur place, sans installation :

```
~/.claude/plugins/marketplaces/claude-plugins-official/plugins/mcp-server-dev/skills/build-mcp-server/references/tool-design.md
```

Pour avoir les skills entières le temps d'une session : `claude --plugin-dir <dossier du plugin>`.

## Critère : remarque applicable

Une remarque issue de la relecture est **applicable** si elle remplit les quatre conditions :

1. elle cite une règle de `tool-design.md` (ou de la spécification MCP) ;
2. elle vise un outil ou une ligne qui existe dans `mcp/api/mcp.js` ;
3. elle change ce qu'un client réel reçoit ou affiche : schéma, titre, description, réponse, message d'erreur ;
4. elle tient dans un test de `mcp/test/mcp.test.js` qui échoue avant le correctif et passe après ;

et elle ne contredit aucune décision Delta : lecture seule sans jeton (D61), journal et compteur sans contenu
(D66, D100), recherche par nom exact d'abord (D105), descriptions qui disent quand appeler l'outil.

Une remarque applicable devient un correctif et son test dans la mission. Les autres s'écrivent en une ligne
dans le rapport de mission, avec la raison de l'écart.

## Grille (première relecture, 11/10/2026)

Retenu, vérifié par le test « grille de relecture » :

- chaque outil a un titre lisible, distinct du nom recopié ;
- les quatre annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) sont posées ;
- schémas fermés (`additionalProperties: false`), nom de 64 caractères au plus ;
- chaque paramètre est décrit ; les valeurs par défaut appliquées par le serveur sont déclarées (`default`) ;
- les motifs vérifiés par le serveur (`id`, `date`) sont déclarés dans le schéma (`pattern`) ;
- une erreur dit comment repartir : identifiant inconnu → `chercher_reference`.

Écarté, avec la raison :

- « Les descriptions ne doivent pas dire à Claude quoi faire » : critère d'admission à l'annuaire Anthropic ;
  le connecteur n'y est pas soumis, et « À appeler AVANT de donner une commande » est voulu (test existant).
- `outputSchema` : facultatif ; aucun client ne s'en sert aujourd'hui, et six formes à maintenir.
- Version de protocole renvoyée telle que demandée par le client : écart à la spécification MCP, mais aucun
  défaut observé ; la restreindre risque de couper un client sans gain constaté. À reprendre si un client échoue.
- Nombre d'outils (6), retours JSON, troncature annoncée (`total`, `affichees`), erreurs d'outil `isError` :
  déjà conformes.
