## En-tête

- état : livré
- tests : 1821/1821
- hash : 573a423
- reçus : cebbeea53aab
- réserves : source par défaut du MCP et du site inchangée (ancienne route) jusqu'à la bascule L5 ; voir « Points fragiles »

# Delta-IA deux couches — lot L3 (mission m-ddc3b4c02860)

- Date : 24/10/2026 14:43 CEST (lue par `date`)
- Agent : `dev-delta`, Claude Code (Opus 5.5, effort high), reprise de m-51da40781ead (réaffectation au compte 108, décision de Sylvain du 24/10)
- Tâche : lot L3 « Lecteurs publics compatibles » de la conception « Delta-IA en deux couches », avec les précisions du chef (bilingue EN à la racine, FR sous `/fr/`, connecteur EN par défaut)
- Branche : `operer/m-ddc3b4c02860`, partie de la L2 (`5e84266`), rebasée sur `origin/main` `60bad6a` (L2 fusionnée, correctif du synchroniseur `d1f032f` compris) ; rebase sans conflit
- Commits produits : `9048d2a` (livraison), `573a423` (correctif : verdict OPÉRER recopié dans `niveaux_effort_disponibles[]`, trouvé par le test de retrait), puis le commit de ce rapport (`git add -f`, `rapports/*` étant ignoré)
- `contexte_empreinte` : `abb92beeff351d9ba4bf8891e4f210ac2bee97a6`

## Compte et quotas

Relevés de `rapports/usage.json` (console-mur, relevé du 24/10 à 14:43, heure de Paris) :
- Claude session 5 h : 7 % (remise à zéro à 15:10).
- **Claude semaine : 90 %** (remise à zéro le 25/10 à 17:00, heure d'hiver). **Seuil D71 (80 %) atteint : vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser.**
- ChatGPT semaine : 42 % (remise à zéro le 30/10 à 18:41).

Ce lot n'a lancé aucun appel de modèle hors de cette session et de ses sous-agents (un fork Opus pour le site, un vérificateur pour la suite) : ni traduction, ni rédaction automatique.

## Cause et choix

Avant L3, le MCP public et le site ne lisaient que l'ancienne route `docs/data`, au format mixte. La génération commune publiée par L2 (`docs/commun/v1/`) n'avait aucun lecteur public. Sur une vue compatible aux champs personnels nuls, telle que la prévoit la bascule L5, `resume_du_jour` rendait une liste vide (filtre sur `fort`/`moyen`). La fiche modèle publique rendait `constats_internes` et `recommandation_operer`, et leur texte était recopié dans `description`. Enfin, l'interface du site et du connecteur n'existait qu'en français.

Choix structurants :
1. **Deux sources, une étiquette par réponse.** Le MCP lit `ancienne_route` ou `commun` (`mcp/lib/couches.js`). La source de la session se choisit par `?source=commun` sur l'adresse du serveur, ou par `DELTA_SOURCE=commun` côté Vercel ; le défaut reste l'ancienne route. Chaque réponse porte `donnees` : source, génération, `publie_le`, fraîcheur, langue, `personnel` (`absent` en commun, `non_separe` sur l'ancienne route). L'ancienne route n'est jamais étiquetée « commun ».
2. **Aucun repli de la couche commune.** Le lecteur vérifie l'index (`delta.manifest` v1, vue publication), l'empreinte du manifeste contre `manifest_sha256`, puis la taille et le SHA-256 de chaque fichier contre le manifeste, et le schéma `delta.commun` v1. Une couche illisible donne « Common reference unavailable: index.json: HTTP 404 » (ou l'équivalent français), jamais une lecture de `docs/data`. Une version majeure inconnue est refusée.
3. **Sans personnel, mais lisible.** Référence commune :
   - `resume_du_jour` liste les éléments factuels du jour à partir des publications (id, `kb_refs`, sources), avec impact `null`, synthèse `null` annoncée, au plus 30 éléments avec `total` et `affichees` ;
   - `etat_versions` rend `installee: null`, statut `inconnu`, sans comparaison ;
   - `fiche_reference` et `chercher_reference` rendent le texte `textes.description.<langue>`, avec repli anglais signalé (`description_repli`), les `systemes` et `avis_personnel` indisponible ; le filtre `statut` est refusé avec la marche à suivre ;
   - `a_tester` répond vide et le dit ;
   - `nouveautes_base` dit que les dates d'ajout ne sont pas publiées (`disponible: false`, `total: null`), sans liste vide présentée comme complète.

   Ancienne route en vue compatible : une journée sans aucun impact personnel liste tous ses éléments (`tri: publication`, `compte.inconnu`, avis), et une installée nulle donne `inconnu`.
4. **Retrait des champs privés des modèles, partagé site et MCP** (`docs/assets/kb-modeles.mjs`, copie exacte `mcp/lib/modeles.js`). Retirés : `constats_internes`, `recommandation_operer`, la section « Constats internes datés » et la ligne « Recommandation OPÉRER » des descriptions, `recommandation` du couple et le `verdict_operer` recopié dans chaque niveau d'effort. Cette dernière n'est que la recommandation OPÉRER (`verdict_operer`, natures, même `pourquoi`) : la garder aurait rendu le retrait cosmétique. Le verdict d'une fiche modèle vaut donc `null` sur le site comme dans le MCP.
5. **Bilingue.**
   - Site : `/` en anglais (x-default), `/fr/` même application en français. 401 clés EN/FR dans `docs/assets/textes.js`. Sélecteur EN/FR vers la même vue (même ancre et même requête) ; le choix est mémorisé sous try/catch, sans aucune redirection. `hreflang`, canonical, og:locale et sitemap avec alternates. Pages, manifestes, sitemap et robots sont générés par `scripts/site_langues.py` depuis un gabarit, les dictionnaires et `site_public_url`.
   - Connecteur : anglais par défaut, français par `?langue=fr` ou `langue` à chaque appel (`enum` et défaut déclarés). Mêmes données dans les deux langues. 80 clés dans `mcp/lib/textes.js`.
   - Les données de l'ancienne route (en français) ne sont pas traduites : sur la page anglaise, elles portent `lang="fr"`.
6. **Adresses centralisées.** Seule source : `scripts/deltalib/couches/bootstrap.json`, qui reçoit `donnees_compat_url` et `site_anciennes_urls`. Le site (Pages) et le MCP (Vercel) ne voient pas `scripts/` : `scripts/urls.py` écrit leurs copies `docs/assets/config.js` et `mcp/lib/config.js`, contrôlées en test et en CI (`--verifier`). Le relais (origines admises), l'agent HTTP du synchroniseur, l'aide du site (`{mcp_url}`, `{site_url}`) et le serveur lisent ce réglage ; un test refuse tout hôte de Delta en dur dans le code.
7. **Site consultable sans état privé.**
   - Sans `etat.json`, Aujourd'hui s'affiche.
   - Mode commun : `?couche=commun`, ou de lui-même si aucun index de `data/` n'est lisible. Il ne lit ni `etat.json`, ni `a-tester.json`, ni `recent.json`, ni `semaine/`, ni `recherche.json`, et chaque onglet concerné dit l'absence de couche personnelle.
   - Une ligne de pied indique la couche lue.
   - Les anciennes ancres restent valides : `#reference?id=`, `?q=`, `?recent=`, `#archives/…`, `#semaine/…`, `#console=`.

## Critère de fin

- **Six appels lisibles sur une génération commune et sur l'ancien format** : tests « génération commune réelle : les six appels… » (génération `g-577f3bcfc94e5b8b` réelle) et « ancienne route mixte : mêmes six appels lisibles… » ; site : `tests/test_site_l3.py` exécute les lecteurs de format d'`app.js` sur l'ancienne route réelle, une vue compatible, la génération réelle et un schéma majeur inconnu.
- **Impacts nuls ne rendent pas la synthèse faussement vide** : « ancienne route en vue compatible… » (tous les éléments, `compte.inconnu`, avis) et « résumé commun : éléments factuels du jour… ».
- **Version installée inconnue, aucun avis personnel de repli** : mêmes tests (`installee: null`, `statut: inconnu`, verdict « en attente de commentaire » sans `pourquoi`, `avis_personnel` en commun, jamais d'avis repris de l'ancienne route).
- **Réponse publique modèle sans `constats_internes` ni `recommandation_operer`, même si la fixture d'ancien format les contient** : test « modèles × efforts… » sur `docs/data/kb/modeles.json` réel, dont la fixture contient bien les constats du Qwen3.5-4B. Champs, textes, section, ligne OPÉRER et `verdict_operer` sont absents ; même contrôle sur la génération commune et dans `site-modeles.test.js`.
- **Site consultable sans `etat` privé, erreurs de couche explicites, anciennes URL fonctionnelles** : `tests/test_site_l3.py`. Côté MCP : « couche commune illisible… » (404, schéma v2, empreinte du fichier, empreinte du manifeste).
- **`mcp/RELECTURE.md` appliqué** : section « Lot L3 ». Retenus avec test : paramètre `langue` décrit, borné et au défaut déclaré ; descriptions qui disent ce que rend la référence commune ; erreurs qui disent comment repartir ; troncature annoncée ; identifiants de suivi. Écartés, avec leur raison : consignes « À appeler », `outputSchema`, source par appel, outils par couche.
- **Tests rouges avant correctif** : les 11 tests de `mcp/test/couches.test.js` et le test « modèles × efforts » échouent sur le code de la L2 (`5e84266`, rejoué dans une copie hors dépôt) : 13 échecs, 48 succès. Ils passent tous après le correctif.

## Écarts au contrat proposé, justifiés

1. **Défaut inchangé : ancienne route.** §6 étape 2 demande des lecteurs compatibles déployés *avant* de changer le contenu servi. Basculer le défaut retirerait verdicts, impacts et versions installées aux agents de Sylvain avant que L4 (MCP local) ne les leur rende. La bascule appartient à L5 : `DELTA_SOURCE=commun` sur Vercel, ou des vues compatibles dans `docs/data`, que les lecteurs savent déjà lire.
2. **Textes bilingues de fiche sur la page dans la langue de la page** : visibles en mode commun et sur toute vue compatible qui porte `textes`. Sur l'ancienne route mixte, les commentaires restent les textes français existants.
3. **Source par session, pas par appel** (voir RELECTURE.md). Le paramètre `couche` de la conception est porté par l'adresse du serveur (`?source=`) plutôt que par chaque outil.
4. **`nouveautes_base` en commun** : la génération L2 ne publie pas de date d'ajout. Réponse explicite plutôt qu'un calcul inventé. À fournir par la phase commune (L5) ou la reprise (L6).
5. **Titres de veille en commun** : la génération L2 n'a ni titre ni résumé (classe S, en attente). Le MCP rend `titre: null` ; le site affiche produit + version ou le libellé de la première source, sans rédaction.
6. **`sources_internes` des modèles** reste dans l'ancienne route : hors du périmètre de L3, qui ne nomme que les deux champs. À retirer avec L5.
7. **Fichiers en plus du brief** : `docs/robots.txt` (pour annoncer le sitemap) et `docs/fr/manifest.webmanifest`, pour que l'app installée depuis `/fr/` démarre en français.
8. Version du serveur : `0.3.0`.

## Points fragiles ou à décider

- **Connecteur de Sylvain en anglais par défaut** : il est relié à `https://delta-mcp-ruddy.vercel.app/mcp` sans paramètre. Descriptions, avis et erreurs y passent en anglais ; les données restent les mêmes. Pour le garder en français : `claude mcp add --transport http delta-ia https://delta-mcp-ruddy.vercel.app/mcp?langue=fr` (geste de configuration, non fait ici).
- Le verdict des fiches modèles disparaît du site et du MCP publics dès la fusion (choix 4). Le choix d'un couple par les agents s'appuie désormais sur les faits publics et sur la règle OPÉRER locale, pas sur ce verdict.
- Le contrôle des chaînes en dur du site est un analyseur lexical avec une liste blanche courte. Il exclut le message « idée » envoyé à Delta, gardé en français car c'est la même phrase que `texte_idee()` du relais.
- `docs/assets/textes.js` est la source éditée à la main ; `scripts/site_langues.py` doit être relancé après toute modification des textes de page (test et CI le signalent).
- Vercel : `mcp/lib/config.js` est un module ES dans `mcp/`, sans lecture hors de la racine du projet. Le déploiement suivant la fusion est à constater (outil par outil, sur l'ancienne et la nouvelle adresse).

## Pour les lots suivants

- **L4** : MCP stdio et Desktop sur le même `lib/couches.js` et le même `blocDonnees`, avec un bloc personnel distinct ; `?source=` deviendra la composition C + P locale.
- **L5** : basculer `DELTA_SOURCE` ou publier les vues compatibles. Ajouter titres, résumés et dates d'ajout communs. Retirer `sources_internes`, `constats_internes` et `recommandation_operer` des données et des sources publiques.
- **L6** : relecture des traductions automatiques, textes de méthodes et de modèles.

## Vérifications hors reçu

Lancés dans la session sur `573a423` : `cd mcp && npm test` : 65 tests, 65 succès ; `scripts/valider.py --perimetre claude|openai|actu` et `--publication docs/commun/v1` : valides ; `scripts/urls.py --verifier` et `scripts/site_langues.py --verifier` : code 0. Tests L3 du MCP rejoués sur le code de la L2 (`5e84266`, copie hors dépôt) : 13 échecs, 48 succès.

## Preuves

`python3 -B outils/tests/verifier.py --fusion` : code 0, « VERIFY OK en 106.313 s : 58b1baee48c72bd1273 » | reçu cebbeea53aab
