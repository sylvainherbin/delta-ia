## En-tête

- état : livré
- tests : commandes : `python3 -B outils/tests/verifier.py` : succès (code 0, reçu 22d5203e9ce2) ; `python3 -B outils/tests/verifier.py` : succès (code 0, reçu abeb94767a18) ; `/home/herbin/.local/bin/verrou-tests --depot . --nom lot2-mcp -- /home/herbin/.nvm/current/bin/node --test mcp/test/couches.test.js mcp/test/local.test.js mcp/test/mcp.test.js mcp/test/site-modeles.test.js` : succès (code 0, reçu 4d2c270a2b70) ; `/home/herbin/.local/bin/verrou-tests --depot . --nom lot2-mcp -- /home/herbin/.nvm/current/bin/node --test mcp/test/couches.test.js mcp/test/local.test.js mcp/test/mcp.test.js mcp/test/site-modeles.test.js` : succès (code 0, reçu 98056d9bad49)
- hash : 31fc2aefd3f098b7a733e292142d4acea5348b01
- reçus : abeb94767a18, 98056d9bad49; écartés : 22d5203e9ce2 (reçu 22d5203e9ce2 (« vérification du dépôt réussie : python3 -B outils/tests/verifier.py ») : worktree non propre au moment du reçu (fichier suivi modifié, indexé ou non suivi non ignoré) ; commiter ou ignorer, puis relancer `operer preuve m-0aa17aa21d59 --affirme "vérification du dépôt réussie : python3 -B outils/tests/verifier.py" -- <commande>` / reçu 22d5203e9ce2 (« vérification du dépôt réussie : python3 -B outils/tests/verifier.py ») : le reçu porte sur 5a6fe73f3be3, pas sur la version livrée 31fc2aefd3f0 : l'arbre a changé hors `rapports/` depuis ; relancer `operer preuve m-0aa17aa21d59 --affirme "vérification du dépôt réussie : python3 -B outils/tests/verifier.py" -- <commande>` sur la version livrée) ; 4d2c270a2b70 (reçu 4d2c270a2b70 (« tests 86 ») : le nombre 86 ne figure pas dans la sortie conservée ; corriger l'affirmation (pas de date ni de numéro qui n'en vient pas) ou relancer `operer preuve m-0aa17aa21d59 --affirme "tests 86" -- <commande>`)
- réserves : aucune

# Delta-IA lot 2 — commun / personnel raccordés, « Utile pour mon ORQYRA », consultation courte (mission m-0aa17aa21d59)

- Date : 24/10/2026 18:35 CEST (lue par `date`)
- Agent : `dev-delta`, Claude Code (Opus 5.5, effort high), exécutant nommé par OPÉRER (le brief proposait Codex)
- Tâche : lot 2 du plan « Delta-IA dans ORQYRA » (décision de Sylvain du 23/10, `DECISIONS.md:697`), après P1 (m-69fa1108bbf6, discipline) et la chaîne deux couches L2-L4
- Branche : `operer/m-0aa17aa21d59`, partie d'`origin/main` `5a6fe73` (L4 fusionnée), linéaire
- Commits produits : `63b09c3d84389248e83f9d8d07388bf6d742c558` (livraison), puis le commit de ce rapport (`git add -f`, `rapports/*` étant ignoré, comme L2-L4)
- `contexte_empreinte` : non concernée (CONTEXTE.md ni lu pour une personnalisation ni modifié)

## Compte et quotas

Relevés de `rapports/usage.json` (relevé du 24/10 à 18:34, heure de Paris) :
- Claude session 5 h : 6 % (remise à zéro à 20:09).
- **Claude semaine : 92 %** (remise à zéro le 25/10 à 17:59). **Seuil D71 (80 %) atteint : vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser.**
- ChatGPT semaine : 45 % (remise à zéro le 30/10 à 18:41).

Aucun appel de modèle hors de cette session.

## Ce qui a été fait

### 1. Raccordement à la séparation commun / personnel (site, MCP local, ORQYRA)

Constat vérifié avant tout travail : **les deux lecteurs de delta-ia refusaient le profil d'instance de P1.** P1 (discipline `portabilite/instance.py:18-19`, `:43-52`) a ajouté `delta.instance` v2 avec `hote` (profil d'hôte `delta.hote`) et `installation`. `racines.py` et `lib/local.js` n'admettaient que la v1 et ces clés étaient « inconnues » : une instance installée par P1 n'aurait ouvert ni le MCP local, ni le Bureau, ni `couches.py`.

- **Racines** : v2 acceptée avec les mêmes refus que `ContexteInstance` (v1 avec `hote`/`installation` refusée, v2 sans profil d'hôte refusée). Le profil lu est retenu (`Racines.profil`, `racines.profil`) : option `--instance`, ou `OPERER_INSTANCE_PROFIL` d'une instance lancée par K1 (posée par `neuf.py:718`). L'installation historique n'en a pas. `scripts/deltalib/couches/racines.py:83-123`, `mcp/lib/local.js:40-75`.
- **MCP local et Bureau** : chaque réponse porte déjà `donnees.commun` et `donnees.personnel` (L4). S'y ajoute `donnees.personnel.instance` : profil d'hôte et réglages lus, avec la date de leur instantané (`local.js:331`).
- **Lecteur Python** aligné sur le lecteur local : un avis à revoir passe en `avis_precedent`, avec `avis: null`. Avant, `couches.py fiche` le rendait comme avis courant (`lecteur.py:153-158`, écart relevé par l'inventaire).
- **Site** : il sait déjà quelle couche il lit depuis L3. `chemin()` lit `data/` ou `commun/v1/<génération>/`, et le pied de page affiche la couche lue (`docs/assets/app.js:43-45`, `:452-465`). Il n'a aucun chemin vers la couche personnelle. Le site n'est pas modifié (gel esthétique). Une garde le vérifie : aucune référence au magasin personnel, à l'instantané d'instance ni à la vue (`tests/test_couches_lot2.py`, dernier test).
- **ORQYRA** : `mcp/bureau.js` est le point d'entrée du Bureau (L4). Il ajoute trois commandes : `utile <id>`, `consulter <texte>` et `a-tester` (`bureau.js:22-60`). Le branchement côté delta-desktop est une mission à ouvrir (voir « Suites »).
- **Le personnel n'est jamais publié** : `api/mcp.js` n'ouvre toujours aucun fichier. La vue n'est construite qu'avec un lecteur local (`estLocal`). L'instantané vit dans `personnel/` en 0600 et n'entre dans aucune génération commune.

### 2. Vue « Utile pour mon ORQYRA »

Source des faits de l'instance : `couches.py personnel rafraichir` range en plus `personnel/instance.json` (`scripts/deltalib/couches/instance.py`), sous le même verrou que le bilan, à chaque rafraîchissement. Ce n'est pas un nouveau collecteur : aucune commande en plus n'est lancée, deux fichiers sont relus.
- **Profil** (`instance.py:43-87`) :
  - recopié : identité, version, mode, profil d'hôte (id, socle, couches personnelles avec `id` et `libelle`), noms des exécutables ;
  - non recopié : chemins, ressources, migrations, lectures SSH.
- **Réglages courants** (`instance.py:90-139`) : table `operer.reglage_missions` de la politique de l'instance.
  - Résolution, dans l'ordre d'OPÉRER (discipline `shared/configuration.py:46-53`) : `--politique`, `OPERER_POLICY_FILE`, `OPERER_CONFIG_DIR/politique.json`, `<configuration>/politique.json` (instance K1), puis `config/instance-policy.json` du dépôt de la commande `operer` (historique).
  - Chaque case est rattachée au couple commun par `bilan.rattacher`, la règle déjà utilisée pour le bilan. Une case sans fiche ou sans effort reste non rattachée, avec son motif. L'effort de famille n'est jamais supposé.
  - Politique absente : `absent`. Politique illisible : `echecs`, et le dernier instantané reste.

Vue (`local.js:347-385`, exposée par `fiche_reference` en local, `mcp.js:467-479`, et par `bureau.js utile`) :
- `raisons[]`, chacune avec sa `source` :
  - `version_installee` : version relevée du produit de la fiche, comparée au même fait commun ;
  - `executable_declare` : exécutable du profil ;
  - `reglage_courant` : cases de la table qui désignent ce couple, `a_revoir` si la fiche commune a changé depuis ;
  - `constats_operer` : groupes et missions du bilan ;
  - `essais`.
- `recommandation` : l'avis courant, ou `null`. Dans ce cas, `sans_recommandation` dit pourquoi (`aucun_avis`, `avis_a_revoir` avec `statut_avis`/`motif_avis`, ou `magasin_absent`). Un texte EN/FR le dit tel quel.
- `concerne: false` avec `raisons: []` est une réponse valable, dite « Rien ne relie cette fiche à cette instance ».
- `effet: "aucun"` et un texte : la vue n'ouvre aucune mission et ne change ni politique ni réglage. Elle n'écrit rien (test : empreinte du dossier personnel inchangée).

Sur une copie du magasin réel (scratchpad, jamais le vrai magasin) :
- **Réglages** : les 24 cases de la table sont rattachées (13 à `claude-sonnet-5-5-high`, 8 à `claude-opus-5-5-high`, 3 à `claude-sonnet-5-5-medium`).
- **`utile modele-claude-sonnet-5-5-high`** rend Claude Code 2.1.310 à jour, 13 cases de réglage (code, mecanique…), 25 groupes et 68 missions observés, et l'avis `utiliser`.
- **`utile claude-code-commandes-add-dir`** rend la version installée et l'avis `tester` du 13/10.
- **Profil** : `absent`, motif `aucun_profil`. L'installation historique n'a pas de profil installé (`~/.config/delta/instance.json` absent, inventaire).

### 3. Consultation courte à la demande d'un agent

Contrat : `chercher_reference` avec `forme: "consultation"` (`mcp.js:250-465`). Exposé aussi par `bureau.js consulter <texte>`.
- **Entrée** : `requete`, filtres `produit` et `categorie` inchangés (et `statut` en local), `limite` (3 par défaut, 5 au plus), `langue`.
- **Sortie** :
  - en-tête des couches `donnees`, recalculé à chaque appel ;
  - `forme: consultation` ;
  - `catalogue {source, version, publie_le}` : `version` est la génération commune ;
  - `cache {cle, statut: calcule | reutilise | sans_version}` ;
  - `total`, `affichees` et `resultats[]`. Chaque résultat porte `id`, `identite`, `nom`, `produit`, `categorie`, `syntaxe` (200 caractères au plus), `resume` (280 caractères au plus, texte de l'éditeur dans la langue demandée avec repli signalé, jamais le commentaire personnel de l'ancienne route), `validite`, `perimee`, `verifie_le` et `references` (trois au plus : url, libellé, officielle). Il porte aussi `know_world {fichier, id}`, l'emplacement de la fiche sous la racine `know_world` de JUGER (`docs/data/kb`, discipline `neuf.py:483`). En local, il ajoute `trouve_dans` et `personnel {statut, verdict}` ;
  - `suite` : `fiche_reference` pour le détail.
- **Cache** : en mémoire, 64 entrées, les plus anciennes sortent d'abord.
  - La clé est le SHA-256 de : source, génération, fraîcheur (dont dépend le statut des avis), signature des fichiers du magasin personnel en local, langue, requête normalisée, filtres et limite. Une autre génération ou un magasin modifié donne donc une autre clé, et jamais un résultat d'un autre catalogue.
  - L'ancienne route n'a pas de version de catalogue : rien n'est gardé, et la réponse le dit.
- **À la demande** : la description dit « pour une question du moment, pas à lancer à chaque mission ». Aucun hook, aucun appel systématique.
- **Mesure réelle** : une consultation de trois fiches pèse environ 3 Ko, contre une liste complète de huit fiches.

### 4. Cases « fait » de « À tester »

**Partagées là où le contrat le permet** : les marques « fait » partageables sont les essais déclarés (D119, `kb-essais.yaml`) et les essais OPÉRER (`operer essai`), dans la couche personnelle. `bureau.js a-tester` rend la page locale d'`a_tester` et `faits {total, entrees}` : id, nombre d'essais, dernière date et sources (`local.js:388-412`). Une fiche « faite » n'est plus proposée.

**La case cochée dans le navigateur ne peut pas être partagée**, pour deux raisons. Le site public est statique (GitHub Pages) et sans écriture. Et une marque « fait » est une donnée personnelle, que le contrat de couches interdit de publier ou de stocker sur l'infrastructure publique. La case reste donc dans `localStorage` (`app.js:35`, `:140-147`). Le chemin partagé reste la déclaration d'essai, que le passage suivant coche (D119).

## Relecture MCP (`mcp/RELECTURE.md`)

`mcp/api/mcp.js` est modifié : la section « Lot 2 » est ajoutée à `mcp/RELECTURE.md`, avec les règles de `tool-design.md` retenues et chacune son test. Résumé :
- **Retenues** :
  - forme de `chercher_reference` plutôt qu'un septième outil (« How many tools? », « Disambiguate siblings ») ;
  - `forme` en `enum` avec `default` ;
  - troncature annoncée ;
  - identifiants pour la suite (`id`, `identite`, `know_world`, `catalogue.version`, `cache.cle`).
- **Écartées** :
  - septième outil `consulter_reference` : même contrat, un schéma de plus à chaque tour pour tous les clients, et l'aide du site, qui décrit six outils, à changer malgré le gel ;
  - cache sur l'ancienne route : pas de version de catalogue ;
  - `outputSchema` : même raison qu'en L3 et L4.

## Tests

- `tests/test_couches_lot2.py` (nouveau, 8 tests) : profil v2 et `OPERER_INSTANCE_PROFIL`, résumé du profil sans ressource ni chemin, politique résolue comme OPÉRER, cases rattachées ou non rattachées avec motif, politique absente ou illisible, CLI `--politique` et `racines`, avis à revoir du lecteur Python, garde du site.
- `mcp/test/local.test.js` : quatre tests « lot 2 — … » (profil v2, vue utile, consultation et cache, Bureau), plus le test des racines L4 mis à jour (champ `profil`).
- `mcp/test/mcp.test.js` : consultation courte sur l'ancienne route.
- Sorties sur le hash livré `63b09c3` :
  - `python3 -B outils/tests/verifier.py` (contrôle ciblé du diff, sous verrou) : `VERIFY ciblé OK en 101.3 s`, 1837/1837 (reçu `abeb94767a18`) ;
  - suite Node du MCP sous `verrou-tests` (`couches`, `local`, `mcp`, `site-modeles`) : `tests 82`, `pass 82`, `fail 0` (reçu `98056d9bad49`). Un premier reçu de la même suite (`4d2c270a2b70`, vert) portait une affirmation fausse (« tests 86 ») : il est écarté et remplacé par celui-ci.
- `git ls-files` du diff (15 fichiers suivis, rien de `rapports/` hors ce rapport, aucun chemin personnel ni jeton : contrôle `git diff --cached | grep` fait avant le commit) : `SPEC.md mcp/RELECTURE.md mcp/api/mcp.js mcp/bureau.js mcp/lib/local.js mcp/lib/textes.js mcp/test/local.test.js mcp/test/mcp.test.js scripts/couches.py scripts/deltalib/couches/bilan.py scripts/deltalib/couches/instance.py scripts/deltalib/couches/lecteur.py scripts/deltalib/couches/racines.py scripts/deltalib/couches/schemas.py tests/test_couches_lot2.py`.

## Points fragiles ou à décider

- **Profil absent sur l'installation historique** : sur la machine actuelle, la vue n'a ni profil d'hôte ni exécutable déclaré. Elle repose sur les versions, les réglages, les constats et les essais. Elle prendra le profil dès qu'une instance P1 sera installée (`OPERER_INSTANCE_PROFIL`).
- **Fraîcheur de l'instantané** : réglages et profil datent du dernier `personnel rafraichir` (pont hebdomadaire, ou ouverture de l'orbe avec `--si-ancien 24`, L4). Une politique changée entre deux rafraîchissements n'apparaît qu'au suivant. `lu_le` est rendu.
- **Correspondance produit → versions et exécutables** : c'est une petite table dans `local.js:30-33` (`VERSIONS_PRODUIT`, `EXECUTABLES_PRODUIT`). Un nouvel outil commun demande d'y ajouter une ligne. Sans ligne, aucune raison n'est inventée.
- **Monde KNOW** : `know_world.fichier` est l'emplacement attendu. Le filtre factuel de discipline (`monde_know.py`) peut écarter une fiche qui nomme encore la machine de Sylvain ; il n'est pas reproduit ici.
- **Python `Lecteur`** : il n'a ni la vue « Utile » ni la consultation. Ce sont des lecteurs JS, comme les six outils (choix de L4). `couches.py fiche` reste le contrôle de bas niveau.

## Suites (missions à ouvrir, non faites ici)

- **delta-desktop** : brancher l'orbe Delta-IA sur `bureau.js utile <id>` (encart « Utile pour mon ORQYRA » d'une fiche), `bureau.js a-tester` (`faits`) et `bureau.js consulter`. Les commandes et leurs codes de sortie sont ceux de L4 (0, 1, 2).
- **discipline (JUGER, optionnel)** : citer `know_world` d'une consultation (`node mcp/bureau.js … consulter <texte>`) au lieu de relire tout le monde KNOW ; rien n'est branché côté discipline.

## Preuves

vérification du dépôt réussie : python3 -B outils/tests/verifier.py | reçu abeb94767a18
tests 82 | reçu 98056d9bad49
