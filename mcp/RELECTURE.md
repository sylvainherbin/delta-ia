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

## Lot 1 : validité, pagination et classement

### Validité des résumés et des fiches complètes

`chercher_reference` et `fiche_reference` rendent les mêmes champs :

- `validite` : `actuelle`, `perimee`, `anterieure_d64`, `non_commentee` ou `inconnue` ;
- `perimee` : booléen quand la comparaison est possible, sinon `null` ;
- `sections_perimees` : identifiants des sections citées modifiées, disparues ou dépréciées ;
- `verifie_le` : date explicite de vérification, sinon dernière date d'historique « commentée »,
  « commentaire révisé » ou « réévaluée », sinon `null`. `maj_le` n'est pas une vérification.

La comparaison reprend `badgeContexte` du site : empreintes de la fiche contre
`contexte_sections` et `contexte_deprecies` du fichier de catégorie publié. Une référence vide
`{}` ne cite aucune section ; une référence absente est antérieure à D64. Un fichier sans ces
métadonnées ne prouve aucune actualité, même si `verifie_le` existe (notamment méthodes et modèles).
« Actuelle » signifie que les sections citées concordent avec ce fichier publié, sans garantie
sur une modification locale de CONTEXTE qui n'aurait pas encore été publiée. La péremption
concerne le commentaire personnalisé, pas nécessairement la syntaxe de l'éditeur ; le verdict
est conservé avec son état, jamais rendu implicitement actuel.

Test : « validité : mêmes états dans chercher_reference et fiche_reference » ; les tests existants
sur les méthodes et modèles vérifient aussi leurs dates explicites.

### Pagination de `a_tester`

Appels : `a_tester({})`, puis `a_tester({curseur: curseur_suivant})` ; `limite` entier de 1 à 20,
défaut 5. La limite s'applique au **total** des résumés de la page : actions d'abord (impact puis
date décroissante), puis essais de la base dans leur ordre publié. Réponse : `total`, `affichees`,
`limite`, `curseur_suivant` (`null` à la fin), `actions_total`, `actions` et
`essais_base: {total, affichees, entrees}`. Les anciens conteneurs restent présents ; leur contenu
est désormais résumé et paginé. Les textes d'action, usages et exemples complets sont retirés
de la liste. Titres et noms sont bornés à 160 caractères, sources à 500/160 caractères.

Détail : `a_tester({id})` renvoie `detail` pour une action, sans tronquer ses étapes ; pour un
essai, il renvoie la même `fiche` que `fiche_reference({id})`. `id` et `curseur` sont exclusifs.
Chaque action reçoit `action:<périmètre>:<date>:<position dans le fichier>`, avec l'ancien
identifiant dans `id_element`. Cet identifiant désigne la position dans le catalogue courant ;
il faut relire la liste après une mise à jour. Une fiche conserve son identifiant canonique.

Le curseur opaque contient une empreinte du contenu et un offset ; il reste utilisable entre
instances sur le même contenu, et avec une autre limite. Tout curseur mal formé, hors bornes ou
périmé produit `isError` et demande de recommencer sans curseur. Un index ou fichier indisponible
reste une erreur explicite, sans réponse partielle présentée comme complète. Le calcul lit
encore la fenêtre complète côté serveur ; la pagination borne la réponse au client.

Tests : parcours sans omissions/doublons, traversée actions/base, liste vide, D119, 101 actions
à étapes longues (moins de 6 000 caractères pour la page par défaut, moins de 18 000 à la limite
maximale), détail intégral, limites et curseurs invalides, curseur invalidé après changement.

### Classement de `chercher_reference`

Les appels existants restent valables (`requete`, `produit`, `categorie`, `limite`) ; `statut`
est un filtre optionnel supplémentaire (`utilise`, `non_utilise`, `inconnu`). Les filtres
s'appliquent avant les deux étapes de recherche, y compris aux fiches multi-produits.
L'index des noms D105 et les alias exacts restent prioritaires. Sinon, couverture des termes,
poids du titre, proximité et normalisation par la longueur du texte. Les correspondances
partielles (au moins la moitié des termes utiles) peuvent concurrencer les longues fiches
complètes et sont signalées dans `avis`. Un nom exact trouvé limite la réponse à ses fiches ;
un identifiant ou une commande littérale garde son écriture, sans découpage lexical.
Les mots vides sont retirés avant la recherche. Les familles lexicales limitées
(contexte/context, mémoire/memory, conversation/chat, compacter/compact, réduire/libérer, reprendre/resume) et
pluriels permettent de chercher les descriptions françaises et anglaises, sans service externe
ni règle liée à un identifiant de fiche. Les préfixes d'options restent significatifs.

Tests : titre/proximité/mots vides/filtres combinés, jeu `test/requetes-reelles.json`, noms exacts
et tests D105 existants. La mesure du classement et ses limites figurent au rapport de mission.

### Relecture de tool-design.md appliquée à ce lot

Retenu : « Truncate huge payloads and say so » et « Include IDs […] for follow-up calls »
(pagination, compte et détail) ; « Tight schemas prevent bad calls » (limite, curseur, statut,
identifiant validés) ; « The description is the contract » (résumés, détail et reprise expliqués).
Chaque remarque est couverte par les tests ci-dessus et la grille existante.
Les autres points déjà écartés dans la grille restent inchangés ; ce lot ne change ni les
annotations, ni le protocole, ni le nombre d'outils, ni le déploiement.

## Lot L3 (deux couches) : lecteurs publics compatibles, langue (24/10/2026, mission m-ddc3b4c02860)

Changements reçus par les clients : source lue (`ancienne_route` ou `commun`) étiquetée dans chaque réponse (`donnees`),
paramètre `langue` (`en` par défaut, `fr`) sur les six outils, textes et erreurs en deux dictionnaires (`lib/textes.js`),
adresse du serveur `?langue=fr` et `?source=commun`, réponses sans personnel sur la référence commune, constats internes
et recommandation OPÉRER retirés des fiches modèles sur les deux formats. Tests : `test/couches.test.js`, rouges sur la L2.

Retenu, avec son test :

- « Describe every parameter » et « Tight schemas » : `langue` décrit, `enum: ["en", "fr"]`, défaut déclaré égal à la
  langue réellement appliquée (`en`, ou `fr` par `?langue=fr`) ; valeur inconnue refusée en erreur d'outil.
  Test « langue : anglais par défaut… ».
- « The description is the contract » / « says what it doesn't do » : chaque description dit ce que rend la référence
  commune (pas d'avis, d'impact, d'essai ni de version installée). Même test.
- Erreurs qui disent comment repartir : `statut` sur la référence commune → « relancer sans `statut` » ; couche commune
  illisible → « Référence commune indisponible : <fichier> : <motif> », jamais de repli silencieux sur l'ancienne route.
  Tests « référence commune : modèles… » et « couche commune illisible… ».
- « Truncate huge payloads and say so » : le résumé commun liste tous les éléments du jour, borné à 30 avec `total`,
  `affichees` et `avis`. Test « résumé commun : plus de 30 éléments… ».
- « Include IDs for follow-up calls » : chaque élément du résumé commun porte `id` et `kb_refs` (pour `fiche_reference`).
  Test « résumé commun : éléments factuels du jour… ».

Écarté, avec la raison :

- Descriptions qui disent quoi faire (« À appeler AVANT… ») : même raison que la grille du 11/10 (critère d'annuaire,
  connecteur non soumis, consigne voulue).
- `outputSchema` : toujours facultatif ; deux sources et deux langues rendraient douze formes à maintenir sans client
  qui s'en serve.
- Paramètre `couche`/`source` par appel : la source se choisit pour la session (adresse du serveur ou `DELTA_SOURCE`) ;
  un mélange par appel rendrait une même conversation incohérente (fiche commune, résumé mixte) pour aucun usage observé.
- Plusieurs outils par couche : refusé par la conception (§4.1) ; les six noms restent.

## Lot L4 (deux couches) : accès personnel local (24/10/2026, mission m-7ca497536e5d)

Changements reçus par les clients : un serveur stdio local (`stdio.js`) sert les mêmes six outils sur la source `local`
(miroir commun de l'instance et bloc `personnel` distinct, avec ses dates) ; le serveur HTTP public est inchangé pour ses
clients (`?source=local` n'est pas admis, aucune lecture de fichier dans `api/mcp.js`). Erreurs des fiches modèles
traduites (`modeles.*`). Tests : `test/local.test.js` (nouveau fichier : les tests de `mcp.test.js` visent le serveur
public servi par HTTP ; même écart de lieu qu'en L3, sans effet sur la preuve) et le scan étendu de `test/couches.test.js`.

Retenu, avec son test :

- « The description is the contract » : en local, chaque description ajoute ce que rend la couche personnelle de cette
  instance (`personnel`, `trouve_dans`, `constats_instance`, version installée), et `initialize` dit que le serveur est
  local, en lecture seule. Test « MCP stdio : protocole ligne à ligne… ».
- « Tight schemas » : schémas inchangés ; `statut` accepté en local, où il filtre sur l'usage de cette instance (refusé
  seulement sur la référence commune publique). Test « une requête retrouve la syntaxe commune et l'avis personnel… ».
- Erreurs qui disent comment repartir : racines non désignées → passer `--instance`, lancer dans l'instance ou demander
  `--historique` ; miroir absent → « synchroniser ou importer d'abord » ; fichier altéré → erreur de couche, jamais de repli.
  Tests « MCP stdio… », « avis périmé… ».
- Erreurs hors dictionnaire (relecture L3, À NOTER 1) : `lib/modeles.js` lève des erreurs à clé (`modeles.format`,
  `modeles.absent`), traduites par le MCP et par le site ; le scan des chaînes en dur couvre désormais `lib/modeles.js`,
  `lib/local.js`, `stdio.js` et `bureau.js`. Test « dictionnaires… » et `site-modeles.test.js`.

Écarté, avec la raison :

- Nouvel outil d'écriture (essai, adoption) : refusé par la conception (§4.1) ; les écritures restent `kb-essais.yaml` et
  `operer essai`.
- `outputSchema` : même raison qu'en L3 ; la source `local` ajouterait d'autres formes sans client qui s'en serve.
- Journal par requête en local : le serveur stdio n'écrit rien sur stdout hors JSON-RPC et n'envoie aucune télémétrie
  (conception §4.1) ; le compteur D66/D100 reste celui du serveur public.

Corrections de relecture du lot L4 (spécification JSON-RPC, reprises dans le même test « MCP stdio… ») : une requête dont
`params` est absent, nul ou n'est pas un objet reçoit une erreur `-32602` au lieu d'arrêter le serveur ; toute erreur de
traitement d'une requête rend `-32603` à cette requête seule, le serveur stdio continue avec les suivantes.

## Lot 2 : commun / personnel raccordés, « Utile pour mon ORQYRA », consultation courte (24/10/2026, mission m-0aa17aa21d59)

Changements reçus par les clients : `chercher_reference` prend `forme` (`liste` par défaut, réponse inchangée ;
`consultation`, forme courte) ; en local, `fiche_reference` ajoute `utile_pour_instance`. Toujours six outils, schémas
fermés, mêmes annotations. Tests : `test/local.test.js` (« lot 2 — … ») et `test/mcp.test.js` (« consultation courte sur
l'ancienne route… »).

Retenu, avec son test :

- « How many tools? » (coût de chaque schéma à chaque tour) et « Disambiguate siblings » : la consultation est une forme
  de `chercher_reference` plutôt qu'un septième outil ; sa description dit quand s'en servir (question du moment, pas à
  chaque mission) et renvoie à `fiche_reference` pour le détail et à la forme `liste` pour une liste plus longue
  (`suite`). Test « lot 2 — consultation courte… ».
- « Tight schemas » : `forme` déclarée en `enum` avec son `default` ; valeur inconnue → erreur de paramètre qui liste les
  valeurs admises. `limite` garde son schéma (1 à 20) ; en consultation, 3 par défaut et 5 au plus, dit dans la
  description du paramètre. Tests « grille de relecture… » (existant) et « lot 2 — consultation courte… ».
- « Truncate huge payloads and say so » : la consultation rend `total` et `affichees`, des résumés coupés à 280 caractères
  et trois références au plus (environ 3 Ko pour trois fiches sur l'instance réelle).
- « Include IDs Claude will need for follow-up calls » : chaque résumé porte `id`, `identite` et `know_world`
  (`fichier` relatif à la racine du monde KNOW, `id`) ; la réponse porte `catalogue.version` (génération commune) et
  `cache.cle`.

Écarté, avec la raison :

- Septième outil `consulter_reference` : même contrat qu'une forme de `chercher_reference`, avec un schéma de plus à
  chaque tour pour tous les clients ; l'aide du site, qui décrit les six outils, aurait dû changer (gel esthétique).
- Cache sur l'ancienne route : elle n'a pas de version de catalogue ; la réponse le dit (`cache.statut: sans_version`)
  plutôt que de garder un résultat qu'aucune version n'invaliderait. Les lectures HTTP restent celles du cache de
  10 minutes de `lib/couches.js`.
- `outputSchema` : même raison qu'en L3 et L4.

## P15 : noms par service, surface de référence et signal (28/10/2026)

Source relue : `tool-design.md` au chemin de la section Source, sans installation. Le repérage Delta-IA
(`claude-code-plugins-mcp-server-dev`) a été recoupé avec ce fichier local ; les tests portent sur le serveur du dépôt.

Retenu, avec des témoins rouges sur l'archive de main `78030f81` et verts sur la branche :

- Noms de 64 caractères au plus, descriptions qui distinguent les usages : `?surface=service` expose six noms
  `orqyra_ai_*` avec les mêmes schémas et annotations ; les noms historiques restent appelables. Test
  « P15 R172 : six noms de service, mêmes schémas, anciens appels et erreurs compatibles ».
- Coût du catalogue : `?surface=reference` expose recherche, fiche et versions pour la consultation de faits.
  Les douze recherches et leurs fiches, ainsi que les versions, gardent leurs réponses. Test
  « P15 R176 : trois outils de référence, corpus inchangé et anciens outils encore appelables ».
- Réponses courtes avec identifiants de suivi : couper une consultation conserve le préfixe de la liste par
  défaut, sans remplacer une cible documentaire par un modèle du fait du quota de diversité. Test
  « P15 R178 : la consultation conserve les premières cibles de liste8 avant de raccourcir » ; mesure réelle
  sur le corpus scellé dans `mesures/2026-10-28-surface.json` (octets, syntaxes et sources conservées).
- Erreurs contrôlées et série statistique compatible : alias résolus avant journalisation, sans arguments.
  Test « P15 R172 : les alias alimentent les compteurs canoniques sans arguments » ; les tests existants
  continuent à vérifier les annotations, les erreurs JSON-RPC et `isError`.

Écarté, avec la raison :

- Supprimer les trois outils absents de la surface de référence : ils portent la veille et les essais, hors de
  ce profil ; cette surface réduit la découverte, pas les autorisations. R176 reste partiel sur l'usage installé.
- Déduire un minimum en jetons des octets : aucun tokenizer de modèle ni rendu natif du client mesuré.
  Les six variantes bornent seulement le minimum en octets sur douze questions (R178 partiel).
- `outputSchema` ou changement de protocole : aucune anomalie liée à P15 ne le justifie ; hors de ce contrat.

Recette complète : `mesures/2026-10-28-p15.md`, par le verrou dev au premier plan. Ni déploiement ni pose cliente.

## P15b : corrections après la relecture de 5675a43e (28/10/2026)

Même référence locale `tool-design.md`, relue sans installation après repérage Delta-IA (donnée secondaire).
Remarques applicables : « The description is the contract », « Disambiguate siblings » et « Describe every
parameter » : descriptions et paramètres adaptés à la surface en fr/en, et renvoi au catalogue complet pour
les outils absents ; tests « P15b R172 : descriptions et paramètres préfixés en fr/en », avec mutation qui
retire l'adaptation des descriptions. « Errors » : erreurs et suite de consultation citent le nom de la surface,
les ids interpolés restent intacts ; test « P15b R172 : erreurs et suite… ». L'avis d'indisponibilité des ajouts
sur la référence commune suit aussi ce contrat (`couches.test.js` et `local.test.js`). « Tight schemas » :
le Bureau rend 3 fiches par défaut et accepte `--limite` de 1 à 5 ; test « P15b R178 : Bureau consulter… ».

R172 reste PARTIEL : défaut historique conservé, surfaces optionnelles sans déploiement ni client qualifié.
La mesure de signal reste descriptive ; ses chiffres ne sont pas un garde-fou de régression. Recette actuelle :
`preuve-p15c.sh <copie-neuve-absolue>` sous verrou dev au premier plan ; archives, mutations, journaux et mesure
restent dans la copie, sans écriture dans `rapports/` du worktree. L'instantané suivi est rafraîchi explicitement
après succès. P15c compare aussi le texte complet des paramètres en fr/en ; une dérive sans nom d'outil est
détectée. Les erreurs d'essais de `reference` renvoient à un outil de son catalogue et à `?surface=service`.
Le défaut du Bureau suit la constante importée de l'API : mutation à 4 verte, réintroduction d'un 3 local rouge.

## P15d : défaut de consultation et textes publics (28/10/2026)

`lib/consultation.js` porte le défaut partagé par l'API et les dictionnaires, sans import circulaire ;
l'API le réexporte pour préserver les imports du Bureau. Descriptions de l'outil et du paramètre,
ainsi que l'aide du Bureau en fr/en, suivent cette constante. Les témoins `textes.test.js` la passent
à 4 dans une copie isolée : ils sont rouges sur P15c et verts sur P15d. La comparaison R172 porte
aussi sur les descriptions complètes de niveau outil, avec la seule adaptation d'origine prévue
pour fiche_reference sur la surface reference ; les noms sont tirés du catalogue historique.

`preuve-p15d.sh <copie-neuve-absolue>` sous verrou dev au premier plan rejoue les témoins, la suite
MCP, l'identité octet par octet des textes et réponses de découverte à 3, et une mutation de
description sans nom d'outil. L'instantané historique suivi reste inchangé. R172 reste PARTIEL :
aucun déploiement ni client installé qualifié.
