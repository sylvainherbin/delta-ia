## En-tête

- état : livré
- tests : commandes : `python3 -B outils/tests/verifier.py --fusion` : échec (code 1, reçu e4c23c561a51) ; `python3 -B outils/tests/verifier.py --fusion` : succès (code 0, reçu 3ea60f5219be) ; `/home/herbin/.local/bin/verrou-tests --depot /home/herbin/projets/.worktrees/delta-ia/m-7ca497536e5d --nom mcp-l4 -- node --test mcp/test/couches.test.js mcp/test/local.test.js mcp/test/mcp.test.js mcp/test/site-modeles.test.js` : succès (code 0, reçu 54d1d62cdf5d) ; `python3 -B outils/tests/verifier.py` : succès (code 0, reçu 09e09011a6a2) ; `python3 -B outils/tests/verifier.py --fusion` : succès (code 0, reçu 32186733ecba) ; `verrou-tests --depot . --nom mcp-l4 -- node --test mcp/test/couches.test.js mcp/test/local.test.js mcp/test/mcp.test.js mcp/test/site-modeles.test.js` : succès (code 0, reçu f33e59ff27a5) ; `verrou-tests --depot . --nom mcp-l4 -- node --test mcp/test/couches.test.js mcp/test/local.test.js mcp/test/mcp.test.js mcp/test/site-modeles.test.js` : succès (code 0, reçu bfee71dd01c1) ; `python3 -B outils/tests/verifier.py` : succès (code 0, reçu 2e1b53a46f80)
- hash : c08a1bc6a2211fa7f5194a5d40c4bbc2c1a25731
- reçus : 32186733ecba, bfee71dd01c1, 2e1b53a46f80; écartés : e4c23c561a51 (reçu e4c23c561a51 (« VERIFY OK ») : commande en code 1 ; relancer `operer preuve m-7ca497536e5d --affirme "VERIFY OK" -- <commande>` une fois la commande réussie / reçu e4c23c561a51 (« VERIFY OK ») : le reçu porte sur 6c1650e58e6f, pas sur la version livrée c08a1bc6a221 : l'arbre a changé hors `rapports/` depuis ; relancer `operer preuve m-7ca497536e5d --affirme "VERIFY OK" -- <commande>` sur la version livrée) ; 3ea60f5219be (reçu 3ea60f5219be (« VERIFY OK ») : le reçu porte sur 520847551fc8, pas sur la version livrée c08a1bc6a221 : l'arbre a changé hors `rapports/` depuis ; relancer `operer preuve m-7ca497536e5d --affirme "VERIFY OK" -- <commande>` sur la version livrée) ; 54d1d62cdf5d (reçu 54d1d62cdf5d (« tests 74 ») : le reçu porte sur 520847551fc8, pas sur la version livrée c08a1bc6a221 : l'arbre a changé hors `rapports/` depuis ; relancer `operer preuve m-7ca497536e5d --affirme "tests 74" -- <commande>` sur la version livrée) ; 09e09011a6a2 (reçu 09e09011a6a2 (« vérification du dépôt réussie : python3 -B outils/tests/verifier.py ») : le reçu porte sur 64676391abe1, pas sur la version livrée c08a1bc6a221 : l'arbre a changé hors `rapports/` depuis ; relancer `operer preuve m-7ca497536e5d --affirme "vérification du dépôt réussie : python3 -B outils/tests/verifier.py" -- <commande>` sur la version livrée) ; f33e59ff27a5 (reçu f33e59ff27a5 (« tests 77 ») : le nombre 77 ne figure pas dans la sortie conservée ; corriger l'affirmation (pas de date ni de numéro qui n'en vient pas) ou relancer `operer preuve m-7ca497536e5d --affirme "tests 77" -- <commande>`)
- réserves : reçus sur `7eb1d3b` (suite complète 1829/1829, MCP 76/76) après les corrections de relecture ; le commit suivant n'ajoute que ce rapport ; delta-desktop et le pilote des réserves (discipline) ne sont pas modifiés ; les changements à y faire sont décrits plus bas

# Delta-IA deux couches — lot L4 (mission m-7ca497536e5d)

- Date : 24/10/2026 15:39 CEST (lue par `date`)
- Agent : `dev-delta`, Claude Code (Opus 5.5, effort high), reprise de m-9821de74d173 (réaffectation au compte 108, décision de Sylvain du 24/10) ; Codex n'avait rien commencé
- Tâche : lot L4 « Accès personnel local » de la conception « Delta-IA en deux couches », plus le reste À NOTER 1 de la relecture L3
- Branche : `operer/m-7ca497536e5d`, partie d'`origin/main` `3800414` (L3 fusionnée), linéaire
- Commits produits : `6c1650e` (livraison), `5208475` (test de forme du chargement de la base, rouge à la première suite complète : il cherchait la ligne exacte modifiée par la traduction des erreurs à clé), commits du rapport (`git add -f`, `rapports/*` étant ignoré), puis les corrections de relecture (voir « Corrections de relecture ») et leur rapport
- `contexte_empreinte` : `abb92beeff351d9ba4bf8891e4f210ac2bee97a6`

## Compte et quotas

Relevés de `rapports/usage.json` (relevé du 24/10 à 15:39, heure de Paris) :
- Claude session 5 h : 1 % (remise à zéro à 20:10).
- **Claude semaine : 90 %** (remise à zéro le 25/10 à 17:00, heure d'hiver). **Seuil D71 (80 %) atteint : vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser.**
- ChatGPT semaine : 43 % (remise à zéro le 30/10 à 18:41).

Appels de modèle hors de cette session : un seul, l'essai réel d'un agent sur le MCP local (`claude -p --model haiku`, 2 tours, 0,0041 $ au prix catalogue). L'import du magasin personnel a tourné avec un budget de traduction nul : aucun appel.

## Cause et choix

Après L3, les agents et le Bureau de Sylvain ne pouvaient lire que le public : l'ancienne route mixte, ou la génération commune sans aucun avis. Le magasin personnel de L1 n'avait aucun lecteur. Les constats OPÉRER d'un couple modèle × effort n'existaient que comme texte `constats_internes` dans le JSON public, que L3 retire déjà des réponses. Rien ne reliait le bilan `operer reglages bilan --json` aux fiches, ni le Bureau au pilote des réserves.

Choix structurants :
1. **Un serveur stdio local qui sert les six outils existants** (`mcp/stdio.js`), sur une troisième source, `local`. Le lecteur local (`mcp/lib/local.js`) lit sur disque la génération commune active du miroir de l'instance. Il vérifie le pointeur, l'empreinte du manifeste, puis la taille, le SHA-256 et le schéma de chaque fichier. Il lit aussi le magasin personnel. Chaque réponse porte `donnees.commun` et `donnees.personnel`, chacun avec ses dates. Chaque fiche porte un bloc `personnel` distinct : statut, `observe_le`, `evalue_le` et son origine, avis, essais. La syntaxe reste celle de la fiche commune. Les noms d'outils et les schémas sont inchangés.
2. **Le public n'ouvre jamais la racine personnelle.** `api/mcp.js` n'importe ni `node:fs` ni `lib/local.js`. Il ne reçoit la source `local` que d'un contexte construit par `stdio.js` ou `bureau.js`. `?source=local` n'est pas une source admise par l'adresse. Le serveur stdio n'envoie aucune télémétrie, et stdout ne porte que du JSON-RPC.
3. **Invalidation à la lecture.**
   - Le pointeur et les fichiers personnels sont relus dès que leur date ou leur taille change, sans redémarrage.
   - Un avis dont l'empreinte commune diffère de la fiche courante devient `a_revoir` (`motif: commun_modifie`). Il passe alors en `avis_precedent` avec `avis: null`, et n'est plus proposé par `a_tester`.
   - Mêmes règles que `Lecteur.bloc_personnel` (L1/L2) : `reference_introuvable`, et `a_revoir` sur un commun très ancien.
4. **Bilan OPÉRER : un instantané privé, une projection, une empreinte partagée** (`scripts/deltalib/couches/bilan.py`).
   - `couches.py personnel rafraichir` lance `operer reglages bilan --json [--depuis] [--nature]` et `operer essai --json liste`. Il garde leur résultat tel quel dans `personnel/reglages-bilan.json` et `personnel/essais-operer.json`, en 0600, sous le verrou des écrivains du magasin. L'instantané porte la commande, les filtres, `jusqu_au`, `lignes_ignorees`, `lu_le` et le SHA-256 du JSON canonique.
   - La projection `personnel/modeles-efforts.json` rattache chaque groupe au couple commun `kb:delta:modeles:<id-couple>` par `modele` et `effort` exacts. Nature et exécutant restent séparés, et les métriques sont recopiées sans recalcul.
   - `couches.py personnel bilan [--couple]` donne à un second lecteur l'empreinte, les filtres et les groupes d'un couple.
5. **Rattachement sans supposition.** Un alias ne vaut que s'il désigne un seul modèle commun. S'il en désigne plusieurs, la famille de l'exécutant tranche (`claude:<rôle>` → modèles d'exécutant `claude`). Exemple : `claude-opus-5-5` est à la fois un modèle Claude et un alias d'Antigravity. Un modèle ou un effort nul, un alias ambigu, un modèle ou un effort sans fiche vont dans `non_rattaches`, avec leur motif.
6. **Pas de second collecteur.**
   - Le pont hebdomadaire des réglages (`reglages_pont.py collecter`) range son export `principal` dans le même instantané : une seule lecture du journal par semaine.
   - Le lecteur MCP et le Bureau n'écrivent rien et ne relèvent rien. Les quotas restent ceux d'OBSERVATORY, que le Bureau lit déjà.
   - Les essais restent écrits par `kb-essais.yaml` (D119) et par `operer essai`. Aucun outil d'écriture n'a été ajouté.
7. **Adaptateur du Bureau** (`mcp/bureau.js`) : même lecteur, mêmes outils. `etat` rend le contrat `vue: bureau`. `versions`, `fiche <id>` et `chercher <texte>` rendent le `structuredContent` de l'outil MCP correspondant.
8. **Relecture L3, À NOTER 1.** `lib/modeles.js` (copie exacte de `docs/assets/kb-modeles.mjs`) lève des erreurs à clé, `modeles.format` et `modeles.absent`. Le MCP et le site les traduisent (EN/FR). Le scan des chaînes en dur couvre maintenant `lib/modeles.js`, `lib/local.js`, `stdio.js` et `bureau.js`.

## Critère de fin

- **Une requête retrouve syntaxe C et avis P, étiquetés et datés séparément.**
  - Test « une requête retrouve la syntaxe commune et l'avis personnel… » : `usage` commun, `verdict: null` dans la partie commune, bloc `personnel` avec `evalue_le` (réévaluation du 13/10).
  - Une requête qui ne trouve que l'avis rend `trouve_dans: ["personnel"]`.
  - Sur l'instance réelle, un agent Claude (Haiku) a appelé `fiche_reference` par le MCP stdio déclaré dans `--mcp-config`. Il a recopié `/add-dir <path>`, la génération `g-577f3bcfc94e5b8b` « recente », le statut `importe`, le verdict `tester`, `evalue_le` 2026-10-13 et `lu_le` du bilan.
- **Avis périmé signalé après un changement commun** : test « avis périmé… ». Une nouvelle génération change l'empreinte de `advisor` (verdict `utiliser`, sans essai), et le pointeur bascule pendant que le lecteur tourne. L'avis passe `a_revoir` avec `avis_precedent`. La fiche était proposée par `a_tester` avant le changement ; elle ne l'est plus après. Même chose quand le commun vieillit pendant la vie du serveur (test « fraîcheur recalculée à chaque lecture »). Un fichier altéré du miroir donne une erreur explicite, sans repli.
- **Sans profil, aucun conseil de Sylvain** : test « sans profil personnel… ». Les six outils rendent `personnel.statut: absent`. Il n'y a ni avis ni version installée, `a_tester` est vide, les constats valent `indisponible` / `bilan_absent`, et la sentinelle d'avis n'apparaît nulle part.
- **Le MCP public ne lit jamais la racine P** : test « MCP public… ». Pas de lecture de fichier ni d'import du lecteur local dans `api/mcp.js`, `SOURCES` réduit aux deux sources publiques, `?source=local` sans effet. Les constats d'instance sont absents de la réponse publique (test « couple modèle × effort… »).
- **Lecture réelle Desktop/agent sur l'instance, sans banc** : magasin réel peuplé par `couches.py --historique importer` et `personnel rafraichir` (voir « Vérifications hors reçu »). `bureau.js --historique etat` et `stdio.js --historique` ont lu ce magasin, et l'agent Haiku ci-dessus aussi. Empreinte globale des fichiers du magasin personnel (SHA-256 des `sha256sum` de `personnel/*.json`) : `88bb0e0747ae06f6` avant et après les lectures du Bureau, du MCP et de l'agent. Aucun fichier modifié après le rafraîchissement de 15:28.
- **Ni double collecteur ni perte d'un essai.**
  - Test « collecte du pont… sans second collecteur » : une seule commande lancée, l'export du pont inchangé, et l'instantané rangé.
  - Test « veille, versions et essais… » : la fiche porte ses essais `kb-essais.yaml` et OPÉRER (`lecon_apprendre` de l'essai clos), chacun avec sa source. Une fiche essayée n'est plus proposée.
  - Sur les données réelles, les 6 essais de `kb-essais.yaml` sont présents sur leurs 4 fiches (contrôle `couches.py verifier --depot` de L1).
- **Même instantané pour le Desktop, le MCP local et le pilote des réserves.**
  - Sur l'instance réelle, `bureau.js etat`, `fiche_reference` du MCP stdio et `couches.py personnel bilan --couple modele-gpt-6-1-sol-high` rendent la même empreinte `216c90bb62f1…` et les mêmes filtres (aucun). Ils rendent aussi les mêmes 6 groupes du couple : missions, premier tour, corrections et consommation.
  - Test « rafraichir… le second lecteur retrouve le même » : même commande et mêmes filtres donnent la même empreinte. Des filtres différents sont exposés et changent l'empreinte.
- **Chaque groupe nature/exécutant comparé à la source.**
  - Réel : 104 groupes projetés, chacun égal à son groupe source pour les neuf champs, `jetons` et `quota`. 58 groupes non rattachés, tous `modele_ou_effort_inconnu`. 104 + 58 = 162 groupes source.
  - Tests : « chaque groupe projeté égal à la source sans détails », « rattachement par modèle, effort et famille… » (alias unique, alias partagé départagé, exécutant hors famille, ambigu, sans fiche, effort sans fiche), « null et absences restent inconnus », « couple sans observation : `aucune_observation`, aucun groupe à zéro ».
- **Aucune fuite dans la réponse publique** : voir le point « MCP public ». La projection ne garde ni `details` ni identifiant de mission (tests Python).

## Écarts au contrat proposé, justifiés

1. **Lecteur local en JavaScript, à côté du `Lecteur` Python.** Les six outils, leur classement et leurs formats vivent dans `api/mcp.js`. Les servir depuis Python aurait dupliqué la recherche ; les appeler par un processus Python à chaque requête aurait coûté des secondes, car la génération est validée en entier. Les règles communes (racines, fraîcheur, `a_revoir`, `reference_introuvable`) sont donc écrites deux fois, avec les mêmes cas de test des deux côtés. C'est le point le plus fragile du lot (voir plus bas).
2. **Source par serveur, pas par appel** : le serveur stdio est `local`, le serveur HTTP reste `ancienne_route` ou `commun`. Même raison qu'en L3 : pas de paramètre `couche` par outil.
3. **Essais OPÉRER** : instantané `essais-operer.json` en plus du bilan. Le « flux d'essai vers APPRENDRE » se lit par fiche : essais OPÉRER rattachés par l'id de fiche de leur protocole, avec statut, issue et leçon APPRENDRE. L'écriture reste à `operer essai` et `kb-essais.yaml`. Aucun essai OPÉRER n'existe encore sur l'instance (liste vide, lue).
4. **`evalue_le`** : l'import L1 le laisse nul. Le bloc personnel prend alors la date de la dernière réévaluation et le dit (`evalue_le_origine: reevaluation`) ; sinon `null`.
5. **Rafraîchissement du bilan.** Le lecteur n'écrit jamais, donc pas de rafraîchissement « au démarrage » du MCP. Il se fait par la collecte hebdomadaire du pont, ou à la demande : `couches.py personnel rafraichir --si-ancien H` garde un instantané de moins de H heures aux mêmes filtres. Le Bureau peut l'appeler à son ouverture (voir delta-desktop).
6. **Pas de bloc quotas dans `resume_du_jour` local** : le Bureau lit déjà les quotas d'OBSERVATORY. Un relevé de plus serait le collecteur concurrent que la conception écarte.
7. **`nouveautes_base` local** : même réponse que le commun, car les dates d'ajout ne sont pas publiées (L3, écart 4). Les avis se lisent par `fiche_reference`.
8. **Synthèse du jour** : `null` en local aussi. La synthèse rédigée est classée S (en attente) depuis L1. Les éléments portent leur avis du jour (impact, `pour_toi`, action), et la sélection fort/moyen s'applique s'il y en a.
9. **Premier peuplement du magasin réel.** Le magasin personnel n'existait pas sur l'installation historique (le service `delta-ia-commun` n'est pas installé). Il a été créé par `couches.py --historique importer --depot ~/projets/delta-ia`, avec un budget de traduction nul et le cache de traductions copié hors du dépôt. Résultat : la génération `g-577f3bcfc94e5b8b`, identique à la publiée. Le SHA-256 global de `docs/data` vaut `46554d3f06d12626` avant et après, et `git status --porcelain docs/data` est vide.

## Changement à faire dans delta-desktop (mission à ouvrir, non modifié ici)

État constaté :
- `desktop/savoir-flux.cjs:11-14` lit `passages.log` et `versions-evenements.jsonl` dans `DELTA_IA_RAPPORTS`.
- Les quotas viennent d'OBSERVATORY (`desktop/observatory/adaptateur/instantane.py:1402-1405`, `usage.json`).
- La note d'architecture `docs/architecture/2026-10-21-m-e0a21175c65b-versions-mises-a-jour.md:45` prévoit un instantané versionné du moteur via `desktop/portable/transport.cjs`.

Changement :
1. **Pont d'instance** : `desktop/portable/transport.cjs` (transport vers le moteur) et `desktop/portable/preload.cjs` (API `window.bureau` de la fenêtre principale). Le flux de l'orbe est assemblé par `desktop/flux-bureau.cjs` à partir de `desktop/savoir-flux.cjs` : c'est là que se branche une commande moteur `delta-ia`, qui lance `node <dépôt delta-ia>/mcp/bureau.js <racines> <commande>`.
   - `<racines>` vaut `--historique` sur l'installation historique et rien dans une instance K1 (`DELTA_INSTANCE` posée). On peut aussi passer `--instance <profil>`.
   - `node` est celui de `~/.nvm/current/bin`.
   - Sortie : une ligne JSON. Code 0 pour une réponse, 1 pour un outil en erreur (`{erreur}`), 2 pour un usage invalide ou des racines absentes (message sur stderr).
2. **Orbe Delta-IA** : `bureau.js etat` → contrat `{schema: "delta.personnel", schema_version: 1, vue: "bureau", lu_le, langue, commun, personnel, site_public_url, outils}`.
   - Bandeau « Référence commune » : `commun.generation`, `publie_le` ou `donnees_du`, `verifie_le`, `fraicheur` (`recente` / `ancienne` / `tres_ancienne`), `derniere_erreur_synchro`. Si `statut: indisponible`, afficher `motif_texte`.
   - Bandeau « Pour cette instance » : `personnel.statut` (`absent` sur une instance neuve : aucun avis), `objets`, `essais_base`, `couples_observes`, `bilan_operer.lu_le`.
   - Le lien « site public » vient de `site_public_url`, sans rien de personnel dans l'URL.
3. **Fiche** : `bureau.js --langue fr fiche <id>` rend la fiche commune et le bloc `personnel`. Pour un couple, il rend aussi `constats_instance` : `statut`, `groupes[]` par nature et exécutant, `observe_le`, `jusqu_au`, `filtres`, `bilan_empreinte`. Un statut `a_revoir` s'affiche comme tel ; `avis_precedent` n'est jamais un conseil courant.
4. **Versions** : `bureau.js versions` → `outils[]` avec `derniere_publiee` (commun), `installee`, `releve_le` et `methode` (couche personnelle) et `statut`. L'historique reste dans `versions-evenements.jsonl`.
5. **Quotas** : inchangés (OBSERVATORY). À côté des réserves, afficher `personnel.bilan_operer.sha256` (12 caractères) et `lu_le` : c'est l'instantané que lit le pilote des réserves.
6. **Fraîcheur du bilan** : à l'ouverture de l'orbe, `scripts/couches.py --historique personnel rafraichir --si-ancien 24`. C'est la seule écriture, déjà sous verrou ; le code 75 signale un magasin occupé, à réessayer plus tard.

## Changement à faire pour le pilote des réserves (discipline, m-5b1a151d5fc8, livré)

Son brief (`docs/briefs/m-5b1a151d5fc8.md:60-71`) lance `operer reglages bilan --json` lui-même. C'est une suite de ce lot, pas une partie de la livraison : le critère est tenu côté delta-ia (même empreinte pour le Bureau, le MCP local et `couches.py personnel bilan`), et le branchement du pilote revient à une mission discipline ou à la L5. Pour lire le même instantané que Desktop et le MCP local, il doit lire `<etat>/delta-ia/personnel/reglages-bilan.json` :
- `bilan` = sortie brute de la commande ;
- `sha256` = empreinte du JSON canonique ;
- `filtres`, `jusqu_au`, `lu_le`.

À défaut, il peut lire `scripts/couches.py --historique personnel bilan [--couple <id>]`, et rafraîchir par `personnel rafraichir --si-ancien H` plutôt que par un appel direct. Sa décision doit citer l'empreinte et les filtres ; si ses filtres diffèrent, il les expose. Une mission discipline est à ouvrir : ce lot ne touche pas discipline.

## Corrections de relecture (24/10, verdict de delta : 1 BLOQUANT, 8 À NOTER)

Trois relectures concordantes, une relecture Codex. Chaque correctif a son test, rouge sur `3de9cce` (rejoué dans une copie détachée : 4 tests de `mcp/test/local.test.js` en échec, 7 succès) et vert après.

1. **BLOQUANT, corrigé** : `a_tester` proposait encore un avis périmé. `LecteurLocal.aTester(fiches)` ne garde plus que les fiches dont le bloc personnel, recalculé sur la fiche commune courante, est `importe`. Le test vise maintenant `advisor` (sans essai, `utiliser`), proposée avant le changement commun et retirée après. L'ancien test visait `/add-dir`, déjà exclue par son essai : il ne prouvait rien.
2. **Corrigé** : `tools/call` avec `params: null` arrêtait le serveur stdio. `traiter` prend `{}` pour des paramètres absents ou non objets (réponse `-32602`), et `stdio.js` rattrape toute erreur par requête (`-32603`) sans s'arrêter. Test : `params: null` puis `ping` reçoivent chacun leur réponse.
3. **Corrigé** : avec `--si-ancien`, les essais OPÉRER n'étaient pas relus quand le bilan était gardé. Ils sont relus à chaque rafraîchissement ; seul le bilan, coûteux, peut être gardé. Test : bilan `garde`, essai ouvert entre-temps présent, une seule commande lancée (`operer essai --json liste`).
4. **Corrigé** : `bureau.js` écrivait ses erreurs de démarrage en anglais. `stdio.js` et `bureau.js` prennent la langue de `--langue`, avant même la validation des options. Test : `bureau.js --langue fr etat` sans racines → `delta-bureau: racines non désignées…`.
5. **Corrigé (rapport)** : en-tête sans chemin absolu ; empreintes du critère c chiffrées (`docs/data` `46554d3f06d12626`, magasin `88bb0e0747ae06f6`) ; fichiers delta-desktop désignés par leur chemin (`desktop/portable/preload.cjs`, `desktop/flux-bureau.cjs`) ; référence du brief du pilote corrigée (`:60-71`).
6. **Prouvé puis corrigé (Codex)** : la fraîcheur était calculée au chargement de la génération, puis figée tant que le pointeur et `synchro.json` ne changeaient pas. Un serveur stdio vit toute une session : il aurait annoncé `recente` après une semaine sans synchronisation. La fraîcheur est maintenant recalculée à chaque lecture. Test : même lecteur, horloge avancée de 2 jours → `ancienne`, de 8 jours → `tres_ancienne`, avis `a_revoir` / `commun_tres_ancien`, retiré de `a_tester`.
7. **Corrigé** : sans miroir commun valide, plus rien n'était consultable, alors que la conception §2.3 dit que « le personnel indépendant reste consultable ».
   - `fiche_reference` rend maintenant les blocs personnels de l'id (`fiches_personnelles`, fiche commune `null`), avec l'indisponibilité du commun dans `donnees.commun` et un `avis` qui le dit.
   - `etat_versions` rend les versions relevées sur l'instance, sans rien comparer.
   - Les avis y sont `a_revoir` / `commun_indisponible` : aucune compatibilité actuelle n'est établie.
   - `chercher_reference` liste ses catégories non lues ; les outils qui ne vivent que du commun (`resume_du_jour`, `a_tester`) répondent par une erreur explicite qui dit de synchroniser ou d'importer.
   - Le `Lecteur` Python suit les mêmes règles, avec les mêmes motifs : `commun_indisponible`, `commun_modifie`, `fiche_absente`, `commun_tres_ancien` (test `test_lecteur_python_memes_regles_que_le_lecteur_local`).
8. **Pris acte, suite** : le pilote des réserves ne lit pas encore l'instantané partagé (voir plus haut) ; mission discipline ou L5.
9. **Pris acte, L5** : les alias historiques (`opus`, `sonnet` du journal) sont rattachés par l'alias courant de la génération active. La règle « alias historique sans équivalence prouvée » relève de l'historique, donc de la L5.

Correctif ajouté pendant la reprise : la fixture des tests MCP datait sa publication de celle de la génération commitée. Les tests de fraîcheur (`recente`) seraient devenus rouges un jour après, sans changement de code. Elle date maintenant la publication et la vérification de l'exécution du test.

## Points fragiles ou à décider

- **Deux implémentations des règles du bloc personnel** (Python `Lecteur`, JS `LecteurLocal`). Une règle changée d'un côté seulement divergerait. Les tests portent les mêmes cas des deux côtés, mais aucun test ne fait tourner les deux langages ensemble : la CI les exécute dans deux tâches séparées.
- **Magasin réel = import du 24/10 à 15:25.** Tant que L5 n'a pas basculé les producteurs, les avis, impacts et versions installées du magasin ne bougent qu'à un nouvel `importer`. Le service `delta-ia-commun` le ferait chaque matin une fois installé (geste du pilote, notice L2). D'ici là, le MCP local donne des avis datés de l'import ; c'est visible dans `donnees.personnel.commun_generation`.
- **Déclarer le MCP local chez Sylvain** est un geste de configuration, non fait ici : `claude mcp add delta-local -- ~/.nvm/current/bin/node ~/projets/delta-ia/mcp/stdio.js --historique --langue fr`. Il complète le connecteur public, qui ne change pas.
- Le pont des réglages range maintenant l'instantané partagé à chaque collecte hebdomadaire. S'il tourne pendant un `importer`, il reçoit `MagasinOccupe` ; le refus est noté dans `instantane`, et l'export du pont reste.
- `lireCommun` garde en mémoire un fichier vérifié tant que le pointeur ne change pas. Un fichier modifié à la main dans le miroir sans changer le pointeur n'est revu qu'au redémarrage du serveur.

## Pour les lots suivants

- **L5** : faire écrire les avis, impacts, versions installées et essais directement dans le magasin personnel par leurs producteurs. Le MCP local lit déjà ce magasin, et il suffira de cesser de le remplir par import. Retirer `constats_internes`, `recommandation_operer` et `sources_internes` du public ; le pont des réglages pourra alors lire l'instantané au lieu d'écrire des constats YAML.
- **I1** : la commande `bureau.js` et le serveur `stdio.js` sont les points d'entrée du composant lecteur de l'installable ; `couches.py racines` imprime les racines résolues.
- **S1** : l'index par sens pourra résoudre ses résultats par `LecteurLocal`, avec `a_revoir` déjà calculé.

## Vérifications hors reçu

Toutes sur l'instance réelle, le 24/10 entre 15:25 et 15:38 :
- **Import** : `couches.py --historique importer --depot ~/projets/delta-ia --budget-traduction 0` → génération `g-577f3bcfc94e5b8b`, 2 403 objets personnels, 1 refus (`fichier_inconnu`, `actu/x-ids.json`, déjà connu de L2). SHA-256 global de `docs/data` : `46554d3f06d12626` avant et après.
- **Rafraîchissement** : `couches.py --historique personnel rafraichir` → 1 109 missions, 162 groupes, 15 couples rattachés, 58 groupes non rattachés (`modele_ou_effort_inconnu`), 0 échec, 17 s. `couches.py --historique verifier` → `ok`.
- **Comparaison à la source et même empreinte** pour le Bureau, le MCP stdio et le résumé pilote : voir « Critère de fin ».
- **Agent réel** : `claude -p --model haiku --strict-mcp-config --mcp-config <stdio --historique --langue fr>` → réponse exacte sur les deux couches, 0,0041 $.
- **Tests ciblés sous `verrou-tests`** (première livraison) : `pytest tests/test_couches_l4.py tests/test_couches.py tests/test_couches_l2.py tests/test_reglages_pont.py tests/test_kb_morceaux.py tests/test_site_l3.py` → verts. Première suite complète sur `6c1650e` : 1 échec (`test_kb_morceaux.py:60`, forme de ligne), corrigé par `5208475`.
- `scripts/urls.py --verifier` et `scripts/site_langues.py --verifier` → code 0.

## Preuves

VERIFY OK | reçu 32186733ecba
tests 76 | reçu bfee71dd01c1
vérification du dépôt réussie : python3 -B outils/tests/verifier.py | reçu 2e1b53a46f80
