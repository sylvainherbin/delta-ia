# Sécurité de la veille Delta-IA

## En-tête

État : livré en relecture (R3c, mission m-786e8d7b550e, 21/11/2026). Les sections « Point (…) » ci-dessous décrivent la remise du 17/11 ; la section suivante dit ce qui a changé depuis et fait foi en cas d'écart.
Réserves : l'affichage du suivi personnel sur la page Référence reste perdu, par décision de Sylvain du 21/11 (« Non, on le perd ») : `/suivi` reste sans CORS. Les têtes, mutants et suites se jouent au K8 par le chef dev ; cette remise n'en revendique aucun résultat neuf.

## État au 21/11/2026 (R3c)

- Skills Codex (point b) : appliqués dans la branche (6e2c1f4) ; `prompts/codex-delta.md` et `codex-delta-kb.md` sont de nouveau identiques au corps des SKILL.md (b8af6ce), la règle « Sources non fiables » après le titre.
- Intégrité git (point 2, R3 et R3b) : empreinte de `.git/config` (clés de suivi à part), `hooks/` et `info/` avant et après chaque étape, et contrôle avant la publication, le relevé X et chaque étape. Seuls `branch.<nom>.remote` et `.merge` vers un remote connu avant l'étape sont exemptés ; `remote.pushDefault` reste strict et ne fait pas d'un « pushdefault » un remote connu (point 7 de la SUITE 2). Sur un git altéré, la supervision elle-même n'est plus lancée : 126 et témoin `rapports/auto/incident-git.json` (B1, 7f61de3). La phrase « La supervision reste lancée après l'arrêt de la chaîne » du point (2) n'est plus vraie.
- Périmètre des commits (point 2) : les commits de delta-ia-commun et delta-ia-selection poussés pendant l'étape ne lui sont plus imputés (identité git du dépôt, un parent, déjà sur origin/main, sujet du service, chemins de sa publication) ; tout autre commit l'est (fed96dd).
- Requêtes sortantes (point 4) : la connexion se fait à l'IP contrôlée, sans nouvelle résolution, à chaque saut ; Host, SNI et certificat restent ceux du nom d'hôte (eedf135). La réserve « ce correctif ne revendique pas un verrouillage contre un changement DNS » est levée.
- Avant imports (point 6) : les unités et `passage-auto.sh` placent les `.pyc` hors de l'arbre (`PYTHONPYCACHEPREFIX`), et refusent (126) de lancer le Python du `.venv` tant que le témoin d'incident git n'est pas levé ; les `*.pth`, `sitecustomize` et `usercustomize` du `.venv` entrent dans l'empreinte d'avant/après étape (B2, da2e3f1).
- Relais (point 3) : inchangé ; la perte d'affichage de `/suivi` est acceptée (décision du 21/11 ci-dessus).
- Tests : la R3b a été jouée au K8 par le chef dev (15 mutants rouges, tête ciblée verte, 6 rouges neufs sur la tête entière, traités par b8af6ce et 3e97655). La R3c attend ses lignes de banc (`~/projets/briefs/securite-delta-ia-veille/lignes-banc-r3.txt`).

## Réalisation

Rapport rédigé le 17 novembre 2026 à 13 h 47, heure locale lue par `date +%Y-%m-%d_%H%M`. Mission m-1eee914025bd, Codex, modèle gpt-6.1-sol, effort xhigh. La lecture des décisions du 17 novembre, de REGLES.md, AGENTS.md et CONTEXTE.md précède les modifications. La base publiée du lancement est celle du scan cité dans le brief. Les constats ci-dessous sont confirmés par lecture du code ; ils ne sont pas présentés comme des reproductions exécutées. Les cas synthétiques ont été écrits avant chaque correctif, dans l’ordre demandé. La copie du brief avec les décisions d’exécution est dans `~/projets/briefs/securite-delta-ia-veille/brief-m-1eee914025bd.md`.

Le présent rapport remplace celui de l’essai m-70eb336ae62a, conservé dans `.tmp-securite/rapport-essai1-m-70eb336ae62a.md`. Les échecs de verrou et de déclaration décrits dans cet ancien essai n’ont pas été rejoués. Aucun service réel, aucun minuteur, aucun push, aucune déclaration de fin OPÉRER et aucun commit n’ont été exécutés par cette session.

## Point (2) — Périmètre des commits

Le code conservait la tête locale pour qualifier la livraison et vérifiait l’arbre et l’intégrité de Git, sans comparer les chemins des commits au périmètre de l’étape.

`orchestrateur.py` retient désormais le hash complet d’`origin/main` avant le lancement. Après récupération de l’état final, le contrôle compare cette référence à `origin/main` et à HEAD. Il reprend les chemins `checkout` de la configuration, sans modifier les permissions. Il contrôle le diff final et les changements de chaque commit, y compris un changement ensuite annulé et les deux noms d’un renommage. Les sorties Git terminées par NUL gardent leurs espaces. Une référence illisible ou divergente refuse le contrôle. Une sortie de périmètre donne 126 avant nettoyage, avec étape, chemins et hashes complets dans le journal du passage et `rapports/auto/`. Aucun historique n’est réécrit.

Les cas de `tests/test_securite_commits.py` couvrent le commit poussé interdit, le commit local interdit, un nom commençant par un espace, le commit autorisé, l’absence de commit et l’ajout interdit ensuite supprimé. Le témoin retire l’appel de contrôle ; le mutant autorise abusivement `scripts/`. Les patchs sont `patches/m1-point-2-temoin.patch` et `patches/m1-point-2-mutant.patch` dans le dossier externe du brief. Leur résultat rouge reste à obtenir.

Le contrôle constate après l’étape ; il ne peut empêcher le premier push. Une publication concurrente étrangère dans l’intervalle est également examinée. La supervision reste lancée après l’arrêt de la chaîne, selon le comportement existant. La décision sur bypassPermissions et delta_auto reste hors périmètre.

## Point (1) — Liens symboliques

`lire_entrees` lisait les octets après une énumération suivant certains liens ; `scinder_sources` lisait les fichiers modèles et méthodes sans ce contrôle.

Le module commun `couches/fichiers.py` refuse `is_symlink()` sur le fichier, les parents situés dans l’arbre et les dossiers parcourus, avant lecture. La projection précontrôle ses entrées, y compris avant l’extraction initiale, puis recontrôle chaque chemin ; la scission précontrôle les deux arbres. L’erreur nommée `LIEN_SYMBOLIQUE_REFUSE` donne le chemin du dépôt, sans lire ni afficher la cible.

`tests/test_securite_liens.py` prépare des liens de fichiers et de dossiers vers une cible synthétique extérieure au dépôt. Les lectures sont enregistrées ; aucune ne doit avoir lieu dans les cas refusés, et le marqueur ne doit figurer dans aucune sortie. Un cas ordinaire conserve la lecture normale. Le témoin neutralise le contrôle ; le mutant ne contrôle que le chemin final et oublie ses parents. Les patchs portent le préfixe `m1-point-1-`.

Ce refus correspond au contrôle demandé par `is_symlink()` ; il ne revendique pas une protection contre un remplacement concurrent entre contrôle et ouverture. Les liens physiques et l’isolement de comptes Unix ne font pas partie de ce point.

## Point (3) — Relais local et page publique

Le relais renvoyait CORS à toutes les origines du site, anciennes incluses, et aux origines HTTP localhost/127.0.0.1 sans restriction de port ; `/suivi` utilisait la même réponse CORS.

La seule origine admise est maintenant l’origine exacte de `site_public_url` dans le bootstrap. `/suivi`, y compris ses réponses d’erreur et OPTIONS, ne reçoit aucun en-tête Access-Control-Allow. `/etat` et `/reference` gardent le flux nécessaire au bouton de la page publiée. L’adresse historique redirigée et les aperçus locaux ne sont plus admis implicitement.

`tests/test_securite_relais.py` rejoue les octets HTTP GET /etat, OPTIONS /reference et POST /reference avec le seul id de fiche, comme `docs/assets/app.js`. Il utilise une connexion en mémoire, une base synthétique et une remise factice, sans socket ni service. Les variantes de `/suivi` et les origines locales arbitraires doivent être refusées à la lecture CORS. Les attentes anciennes des tests du relais et des origines ont été adaptées. Le témoin remet le relais précédent ; le mutant remet CORS sur `/suivi` pour l’origine publique. Les patchs portent le préfixe `m1-point-3-`.

La page Actu charge les widgets X ; le bouton Référence du même app.js reste accepté depuis son origine exacte. La lecture de `/suivi` était utilisée par la page Référence pour les adoptions et ajustements : son fetch échoue désormais dans le navigateur et son repli existant masque ces données. Aucun jeton n’est ajouté à cette page publique partageant son origine avec les scripts tiers. Restaurer ce suivi exige une interface privée ou un canal authentifié distinct. Le test de requêtes ne constitue pas une recette visuelle d’Actu. L’authentification de POST /reference, différée par la décision du superviseur, reste hors périmètre.

## Point (4) — Requêtes sortantes et liens d’articles

`requests` suivait automatiquement les redirections. Le format de cartes avec `<time>` acceptait les liens sans le filtre de domaine de la liste resources.

Le client suit maintenant les redirections une par une, avec une limite de sauts. Avant chaque requête il exige HTTPS, ou HTTP explicitement déclaré par l’URL de la source ou son option `autoriser_http`. Il vérifie toutes les adresses résolues, IPv4 et IPv6, et refuse les adresses non globales, réservées ou multicast. Les proxys hérités de l’environnement sont désactivés. Les en-têtes sont recalculés à chaque saut ; le jeton GitHub reste limité à son API. Le refus s’appelle `DESTINATION_REFUSEE`. Les deux analyseurs de cartes et la lecture des articles utilisent le même filtre d’hôte.

`tests/test_securite_http.py` simule la résolution et la Session HTTP : redirections vers loopback, privé, link-local, file:, HTTP non déclaré, hôte à IP mixte, IPv6 et adresses initiales non routables. Il conserve une redirection publique et HTTP déclaré, et filtre les articles vers un hôte non déclaré. Les tests antérieurs du client ont maintenant un DNS simulé ; l’ancien serveur HTTP de redirections est remplacé par une Session factice. Le témoin neutralise les contrôles de destination et d’hôte ; le mutant ne contrôle que le premier saut. Les patchs portent le préfixe `m1-point-4-`.

La vérification DNS précède l’appel à requests, dont la connexion effectue encore sa propre résolution : ce correctif ne revendique pas un verrouillage contre un changement DNS entre ces deux instants. Le client urllib du miroir commun est distinct et n’est pas transformé par ce point. Aucun réseau réel n’a servi aux recettes de cette session.

## Point (5) — Plafonds

Le nombre d’articles à enrichir n’était pas plafonné. La synchronisation limitait chaque fichier mais commençait les écritures sans borne globale.

Le bootstrap déclare `limites.lectures_articles` à 100 et `limites.synchro_octets` à 67108864 ; la configuration refuse les valeurs non entières, nulles ou négatives. La lecture des articles compte les candidats avant leur enrichissement. Un dépassement lève `PLAFOND_ARTICLES` ; fetch s’arrête au code 6, conserve état et brut, et écrit son rapport d’arrêt hors dry-run. La synchronisation additionne index, manifeste et tailles annoncées avant de créer une génération. Elle garde les contenus en mémoire dans ce budget et vérifie longueur et empreinte avant la première écriture. Le dépassement produit `PLAFOND_SYNCHRO` ; le diagnostic habituel est conservé sans modifier la génération active.

`tests/test_securite_plafonds.py` couvre borne atteinte, dépassement d’un article ou d’un octet, absence de lecture d’article partielle, absence de génération provisoire écrite, rejet des mauvaises configurations et rapport d’arrêt de fetch. Le témoin enlève les deux plafonds ; le mutant accepte un dépassement d’une unité. Les patchs portent le préfixe `m1-point-5-`.

La borne de synchronisation comprend les contenus repris du cache. Les verrous et le diagnostic d’échec habituels peuvent être écrits ; « aucune écriture partielle » vise les données de la génération. La limite d’articles charge le bootstrap du dépôt ; le plafond du miroir prend aussi la configuration locale de son instance. Les quotas des fournisseurs ne sont pas modifiés.

## Point (6) — Contrôle avant les imports

Les deux scripts de publication importaient la bibliothèque du dépôt avant leur contrôle d’arbre sale.

Les deux unités comportent maintenant un ExecStartPre en `/usr/bin/python3 -I -S`, sans import du dépôt. Il demande à Git l’état suivi, indexé et non suivi de `scripts/`. Un résultat sale ou une erreur Git donne 126 et `ARBRE_CODE_SALE`. Ce choix est plus simple qu’un second chargeur dans chaque CLI et évite de modifier leurs fonctions et leurs diagnostics. Il couvre aussi les modules dépendants, pas seulement le fichier de démarrage.

`tests/test_securite_avant_imports.py` rejoue l’ordre des commandes d’unité sur un dépôt synthétique. Un module modifié, indexé ou non suivi écrirait un marqueur s’il était importé ; le marqueur doit rester absent. L’arbre propre doit passer. Aucun appel systemd n’est utilisé. Le témoin retire ExecStartPre ; le mutant ne regarde que le script de démarrage et oublie ses dépendants. Les patchs portent le préfixe `m1-point-6-`.

Cette protection s’applique aux lancements par les deux unités après leur installation. Les appels directs aux CLI gardent leur comportement antérieur ; aucune autorité contre un processus Unix concurrent n’est revendiquée.

## Point (b) — Sources comme données

Les prompts de lancement déléguaient la lecture des textes aux agents. Les skills ne portaient pas de règle commune explicite contre une instruction cachée dans ces textes.

Le gabarit `construire_prompt` commun aux cinq étapes place toute charge `donnees_sources` transmise directement dans une unique paire `<donnees_sources>…</donnees_sources>`, après sérialisation JSON et échappement HTML. Une fausse fermeture contenue dans une source ne peut fermer ce bloc. Le gabarit porte la consigne explicite et le périmètre extrait de la configuration. Les textes lus ensuite par les outils restent qualifiés comme données non fiables. Les deux skills Claude et les trois fichiers de prompts ont reçu la même règle de lecture et de citation. Les modes de permission, listes d’outils, modèles et efforts nocturnes n’ont pas changé.

Les deux skills Codex ne sont pas modifiés : l’écriture de `.agents/skills/delta/SKILL.md` est refusée avec Errno 30, y compris après le renouvellement du profil annoncé par l’utilisateur. Aucun accès alternatif n’a été essayé. L’ajout pour les deux fichiers est disponible dans `~/projets/briefs/securite-delta-ia-veille/patches/point-b-skills-codex-a-appliquer.patch`. Le responsable doit l’appliquer par une voie autorisée et ajouter ces deux chemins à la remise avant de considérer ce point complet.

`tests/test_securite_prompts.py` couvre les cinq prompts avec article, page, X et sources.yaml synthétiques, dont une fausse fermeture de balise. Il exige aussi la règle dans les quatre skills : les deux cas Codex sont donc attendus en échec tant que le patch externe manque. Le témoin remet le gabarit sans séparation ; le mutant retire les balises en gardant la règle. Les patchs portent le préfixe `m1-point-b-`.

Ce point réduit la probabilité d’injection ; les sorties futures des outils ne sont pas réécrites par le moteur CLI. Le contrôle effectif des chemins reste le point (2).

## Validation et remise

La consigne particulière de cette reprise interdit tous les tests : pytest, verrou-tests --cible et VERIFY-ALLÉGÉE n’ont pas été lancés, pas davantage que les témoins et mutants. Aucun verdict vert ou rouge d’exécution n’est revendiqué. Le contrôle textuel `git diff --check` s’est terminé au code 0 ; il ne remplace aucune recette. La compilation Python et les unités réelles n’ont pas été exécutées.

Les quatorze patchs témoins et mutants, leur précondition et les commandes exactes sont sous `~/projets/briefs/securite-delta-ia-veille/vers-chef.txt`. Chaque variante doit être jouée séparément sur une copie jetable du contenu livré. La tête du point (b) ne sera verte qu’après application autorisée du patch des skills Codex. La relecture des changements de tests existants doit accompagner celle des nouveaux cas.

`.codex-commit-msg` et `.codex-commit-files` préparent la livraison du lanceur. La demande source souhaitait un commit par point ; cette session respecte l’interdiction plus récente de commiter. Le découpage et le hash de remise doivent donc être produits par le lanceur, sans substituer le hash de base à un hash de livraison. Aucun reçu ni champ machine n’a été fabriqué.

Le résultat ouvrable est ce rapport : OUVRIR : .orqyra/ouvrir.json.

## Après relecture et intégration

L’opérateur fait d’abord jouer les têtes, témoins et mutants sous le verrou commun au premier plan, puis VERIFY-ALLÉGÉE. À la fusion, la CI verte sur le hash exact fait foi ; si elle est absente ou désactivée, jouer la suite complète `verifier.py --fusion` sous verrou sur ce même hash. La session actuelle ne vaut pas autorisation de sauter ces étapes.

Après intégration par la voie de delta-ia, installer les deux fichiers d’unités depuis deploy/systemd et faire `systemctl --user daemon-reload`. Installer de même, depuis leurs modèles, `delta-etat-fournisseurs.service`, `delta-reglages-pont.service` et `delta-ia-relais.service` (garde : témoin d’incident d’abord, PYTHONPYCACHEPREFIX, parcours de scripts/ sans git, qui refuse tout *.pyc, *.pyo, *.so ou *.pyd hors de `__pycache__/` et tout lien symbolique), puis redémarrer `delta-ia-relais.service` ; aucun redémarrage du minuteur de passage n’est nécessaire pour le code Python. Les deux unités comparent sans git l’empreinte de `.git` (config, info/attributes, info/exclude, hooks/ ; un `.git/commondir` présent est refusé) à la référence `~/.local/state/delta-ia/empreinte-git.json`, que l’orchestrateur écrit à la fin de chaque chaîne propre : elles rendent 126 jusqu’à la première chaîne propre après leur installation. Dans la chaîne, le même parcours tourne en processus avant chaque Python du dépôt relancé après une étape (garde.py, valider.py, capteur_x.py) : un binaire hors de `__pycache__/` est un incident, témoin et 126. Ces Python reçoivent le PYTHONPYCACHEPREFIX de la chaîne (sinon `%t/delta-ia-pycache`) : un .pyc forgé dans un `__pycache__/` de scripts/ n'est pas chargé. Les unités et le relais réels n’ont pas été touchés ici. Le passage de nuit suivant devra montrer le contrôle des commits dans son rapport.
