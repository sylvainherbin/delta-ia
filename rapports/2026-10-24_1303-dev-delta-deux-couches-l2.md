# Delta-IA deux couches — lot L2 (mission m-d4055b3a5908)

- Date : 24/10/2026 13:03 CEST (lue par `date`)
- Agent : `dev-delta`, Claude Code (Opus 5.5, effort high), réaffecté de Codex par décision de Sylvain du 24/10
- Tâche : lot L2 « Référence neutre et publication versionnée additionnelle » de la conception « Delta-IA en deux couches »
- Branche : `operer/m-d4055b3a5908`, au sommet de `origin/main` (`f43fabf`), aucun rebase nécessaire (main inchangé à 13:00)
- Commits produits : `42eb634a9ffe6f511642ff85ba0604a936b340e1` (livraison), puis le commit de ce rapport (ajouté par `git add -f` à la demande de delta du 24/10, `rapports/*` étant ignoré)
- `contexte_empreinte` : `abb92beeff351d9ba4bf8891e4f210ac2bee97a6`

## Compte et quotas

Relevés de `rapports/usage.json` (console-mur) :
- Claude session 5 h : 3 % à 11:43 (remise à zéro à 15:10, heure de Paris) ; illisible (`null`) au relevé de 13:03.
- **Claude semaine : 89 % à 11:43** (remise à zéro le 25/10 à 17:00, heure d'hiver) ; illisible (`null`) à 13:03. **Seuil D71 (80 %) atteint : vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser.**
- ChatGPT semaine : 41 % à 13:02 (remise à zéro le 30/10 à 18:41).

Ce lot a consommé, en plus de cette session Opus, 49 appels `claude -p` à Haiku 5.5 pour la traduction : 219 299 jetons d'entrée, 604 465 jetons de sortie (dont une large part de réflexion du modèle), **0,345 $ au prix catalogue** (`total_cost_usd` de Claude Code, pas une facture), 33 minutes en tout. Je n'ai pas pu mesurer la part de quota hebdomadaire consommée, faute de relevé Claude lisible après la traduction.

## Cause et choix

L2 doit produire une première référence commune propre, publiée à côté des routes actuelles et générée sans le profil. Elle couvre aussi les fiches Windows et macOS que le profil de l'instance filtre, et porte des textes EN/FR (décision du 22/10 : « fiches déjà EN/FR (L2) »). Chaque instance doit pouvoir la lire hors ligne, et un échec réseau ne doit pas la lui faire perdre.

Choix structurants :
1. **Frontière physique, pas promesse de prompt.** L'étape privée (import L1) écrit l'entrée du générateur commun dans `<etat>/delta-ia/production/entree-commune/`, réduite à la liste positive. Le générateur (`generateur.py`) n'ouvre que ce dossier et le cache de traductions, par un lecteur borné : toute autre lecture est refusée, chaque lecture est relevée. L'étape privée contrôle ensuite la sortie (détecteur L1 + textes P des sources scindées) avant d'activer la génération.
2. **Extraction couvrant tous les systèmes, sans lire le profil.** Les extracteurs déterministes relisent `raw/kb/` avec une liste d'exclusion vide, puis rétablissent la liste en cours. Chaque fiche porte `systemes` : `["windows"]`, `["macos"]`, `["linux"]`, ou `null` si la documentation ne la borne à aucun système. Le commun prend toute fiche extraite absente de la base de l'instance. Une fiche retirée par le profil mais encore décrite par sa documentation, lue en entier, est remise en service (`retiree: false`). Les ajouts sont déclarés dans le manifeste (`couverture_sources.base:<p>.ajoutees`) et admis par le contrôle de fidélité.
3. **Enveloppe bilingue hors de l'empreinte factuelle.** `textes.description.en` reprend exactement `description_source` (`statut: source`). `textes.description.fr` est une traduction de cet extrait exact (`source_sha256`, `glossaire: r1`, `statut: automatique`). Une traduction ne change pas l'empreinte : aucun avis ne passe `a_revoir` à cause d'elle. Le lecteur rend la langue demandée, sinon l'anglais avec `repli: true`.
4. **Rédacteur isolé et mesuré.** `claude -p --safe-mode` (ni CLAUDE.md, ni skills, ni MCP, ni hooks), `--tools ""`, invite système neutre, dossier vide, sans session gardée, Haiku, `--effort low`. Le code entre accents graves et les URL sont masqués (`⟦n⟧`) puis rétablis ; une réponse dont un repère manque est refusée. Si les jetons d'entrée facturés dépassent la moitié des octets envoyés plus 2 500, du contexte a été ajouté, et tout le lot est refusé (`contexte_inattendu`). Mesure réelle : environ 600 jetons de cadre par appel.
5. **Cache de traduction suivi par Git** : `kb-traductions/fr.json`, clé `(sha256 du texte source, champ, langue, glossaire)`. Il ne contient que des traductions d'extraits publics. Le suivre par Git permet au producteur nocturne de le retrouver ; un cache local d'essai l'aurait perdu au premier passage du service. Il est enregistré après chaque lot accepté.
6. **Route versionnée immuable.** `docs/commun/v1/<generation>/` est une copie octet pour octet de la génération validée. `docs/commun/v1/index.json` (`delta.manifest`, vue `publication`) porte l'heure du cycle, la génération précédente (gardée pour retour), le cycle attendu et le dernier jour couvert par périmètre. Elle est servie à `https://ai.orqyra.io/commun/v1/`. `docs/data` n'est pas touché.
7. **Synchroniseur.** Requête conditionnelle sur l'index (ETag, Last-Modified). Seuls les fichiers changés sont téléchargés (les fichiers identiques sont repris de la génération active), dans une génération provisoire validée en entier avant la bascule d'un seul pointeur. En cas d'échec, la dernière génération valide est gardée et l'erreur consignée (`synchro.json`, puis `derniere_erreur_synchro` dans le lecteur). Fraîcheur : `recente`, `ancienne` (plus de 24 h) ou `tres_ancienne` (plus de 7 jours, l'avis importé passe alors `a_revoir`).
8. **Producteur.** Le service `delta-ia-commun` (`scripts/commun_auto.py`, minuteur à 06:45) suit le modèle de `selection_auto.py` : même verrou que la chaîne, main seul, arbre propre hors de sa route, import dans les racines historiques, publication, `valider_route`, commit des seuls chemins `docs/commun/v1/` et `kb-traductions/fr.json`, push sans force. Il n'entre dans aucune étape de la chaîne. Surveillance : `couches.py surveiller --url …` rend le code 1 si le cycle de 24 h est manqué de plus de 6 h ou si un périmètre n'a pas de jour depuis plus de 2 jours.

## Ce qui est livré

| Fichier | Rôle |
| --- | --- |
| `scripts/deltalib/couches/extraction.py` | Extraction tous systèmes, `systemes_de` |
| `scripts/deltalib/couches/scission.py` | Scission positive de `kb-modeles/` et `kb-methodes/`, recomposition, sentinelles P |
| `scripts/deltalib/couches/generateur.py` | Entrée du générateur, lecteur borné, enveloppe `textes`, manifeste |
| `scripts/deltalib/couches/traduction.py` | Cache, masquage, rédacteur `claude -p` isolé, bilan de coût |
| `scripts/deltalib/couches/publication.py` | `publier`, `valider_route`, `synchroniser`, `fraicheur`, `surveiller` |
| `scripts/deltalib/couches/config.py`, `bootstrap.json` | Configuration d'instance et bootstrap neutre unique (mode lecteur, URL, seuils, budget de traduction à 0) |
| `projection.py`, `schemas.py`, `lecteur.py`, `controle.py`, `classement.py`, `stockage.py` | Branchement de la frontière, schémas `textes` / publication / synchronisation, fraîcheur et langue, fidélité aux ajouts |
| `scripts/couches.py` | `importer` (`--brut`, `--traductions`, `--budget-traduction`, `--modele`), `publier`, `synchroniser`, `surveiller`, `fiche --langue` |
| `scripts/commun_auto.py`, `deploy/systemd/delta-ia-commun.{service,timer}`, `deploy/systemd/commun.md` | Service de publication quotidienne et sa notice |
| `scripts/valider.py --publication`, `.github/workflows/tests.yml`, `scripts/carte.py` | Validation de la route, en CI aussi |
| `SPEC.md` §3 | Périmètre d'écriture du service (`docs/commun/v1/`, `kb-traductions/fr.json`) |
| `tests/test_couches_l2.py` | 18 tests |
| `docs/commun/v1/` (3,9 Mo), `kb-traductions/fr.json` (776 Ko) | Première génération publiée `g-577f3bcfc94e5b8b` et ses traductions |

## Critère de fin

- **Première génération commune propre publiée à côté des routes actuelles** : `g-577f3bcfc94e5b8b`, `valider.py --publication docs/commun/v1` et `valider.py --commun` (avec les termes de l'instance) valides. Elle compte 2 296 fiches, 1 872 textes EN et 1 872 FR. `docs/data` est inchangé. Recherche dans le contenu publié, 0 occurrence pour chacun de ces motifs : nom du compte, courriels personnels, projets, `/home/`, ids de mission, `pour_toi`, `statut_usage`, `constats_internes`, `recommandation_operer`, `exclure_systemes`. « Gmail » apparaît 3 fois, comme nom de connecteur dans la documentation publique.
- **Lisible hors ligne** : sur une instance neuve, `synchroniser --url file://…/docs/commun/v1/` puis `fiche codex-parametres-windows-sandbox --langue fr` rendent `disponible`, `recente`, `systemes: ["windows"]` et le texte français, avec un personnel `non_personnalise`. Le test `test_miroir_hors_ligne_echec_reseau_et_304` passe par un vrai serveur HTTP local, arrêté avant la lecture.
- **Sentinelle absente de l'entrée du générateur C et de sa sortie** : la sentinelle est placée dans `profil.yaml`, `CONTEXTE.md`, une recommandation, une description S, `etat.json`, `kb-essais.yaml` et les `constats_internes` d'une source modèle. Elle est absente de l'entrée, des charges envoyées au rédacteur, de la génération et du cache. Les lectures du générateur se limitent à son entrée et au cache, et la part privée la conserve (`test_sentinelle_absente_de_l_entree_des_envois_et_de_la_sortie`). Un texte privé recopié dans un champ C fait refuser l'import (`test_texte_prive_d_une_source_scindee_refuse`).
- **Cache inchangé sur relance** : sur données réelles, la relance n'écrit rien (`changements: []`). En test, aucun appel au rédacteur, octets du cache identiques et même génération ; un seul extrait modifié n'envoie qu'une unité, et le budget est respecté.
- **Échec réseau conserve la dernière génération** : serveur arrêté, puis génération altérée sur le serveur ; dans les deux cas le pointeur est inchangé, la génération active reste lisible et l'erreur est consignée.
- **Fiche Windows/macOS disponible sans publier le profil Linux** : 12 fiches ajoutées sur les données réelles, 1 Claude et 11 Codex (`codex-parametres-windows-sandbox`, `codex-parametres-computer-use-macos-bundle-ids`, …). Ni `exclure_systemes` ni le profil n'apparaissent dans la génération.
- **Coût et couverture enregistrés** : voir « Compte et quotas » et le manifeste (`couverture_langues`, `couverture_sources`). Les journaux locaux de production sont `couts.jsonl` (une ligne par lot, avec jetons et coût catalogue) et `traductions-envois.jsonl` (charges envoyées, empreintes, mesures), en 0600, jamais publiés. Le coût n'est pas nul : il est mesuré et reste à la charge du producteur. Rien n'a été réestimé ni extrapolé.

## Taille du diff (+105 888 lignes)

`git diff --numstat f43fabf 42eb634` (48 fichiers) : **94 485 lignes de données générées** dans `docs/commun/v1/` (première génération `g-577f3bcfc94e5b8b` et son `index.json`, JSON indenté produit par `couches.py publier`, 3,9 Mo), **9 290 lignes** de `kb-traductions/fr.json` (cache des 1 856 traductions automatiques, 776 Ko), 438 lignes de tests et 1 675 lignes de code, de configuration et de documentation. Les deux premiers postes sont des données produites, pas du code à relire ligne à ligne : `valider.py --publication docs/commun/v1` les contrôle (en CI aussi), et le service nocturne les réécrit. À chaque publication, seuls les fichiers modifiés changent.

## Écarts au contrat proposé, justifiés

1. **`publie_le`** vit dans `index.json`, et `null` dans le manifeste de génération : la même génération garde ainsi les mêmes octets chez le producteur et dans chaque miroir. Le pointeur d'un miroir porte l'heure de publication (`origine: synchro`).
2. **Clé du cache** : empreinte du *texte source* du champ, au lieu de l'empreinte factuelle de toute la fiche. Une source ou un libellé qui change sans toucher l'extrait ne relance pas la traduction ; une traduction ne dépend que de son texte.
3. **Le cache de traduction est suivi par Git** (`kb-traductions/fr.json`) et non rangé dans `<etat>/production/` : c'est du contenu public, coûteux à refaire, que le producteur nocturne doit retrouver. Les coûts et les envois restent locaux.
4. **Textes bilingues limités aux descriptions de la base** en L2. Titres et résumés de la veille, méthodes et descriptions de modèles restent en attente : ils sont rédigés aujourd'hui avec le profil (classe S), et leur rédaction commune relève de la phase commune quotidienne (L5) et de la reprise (L6). La veille commune porte désormais ses jours couverts (`jours`, `maj_le`).
5. **Scission des sources** : elle est faite avant génération et sans perte (aller-retour exact sur les 7 fichiers réels). La part privée va au magasin personnel (`personnel/sources.json`), la part publique en production (`production/sources-publiques.json`). La génération commune des modèles reste la projection C de `docs/data/kb/modeles.json`, contrôlée par les sentinelles de la part privée. Faire régénérer `kb/modeles.json` par `fiches_modeles.py` depuis la seule part publique modifierait un producteur des passages, ce qui relève de L5. `forfaits.yaml` est entièrement privé (classe S, comme en L1).
6. **Sentinelles des sources** : seuls les rattachements P (constats et sources internes, recommandations OPÉRER, statut d'usage, jauges, exécutants) servent de sentinelles. Les parts S recoupent légitimement des champs C : 6 faux positifs au premier essai réel, car la syntaxe d'une méthode est tirée de son corps et l'unité des crédits figure dans le JSON. Corrigé, aucun refus ensuite.
7. **Pas d'étape dans la chaîne** : la publication est un service à part, après la chaîne et sous son verrou. Brancher une étape déterministe dans l'orchestrateur aurait demandé un nouveau type d'étape, alors qu'il ne lance que Claude ou Codex.
8. **Nouveaux schémas** : `delta.manifest` vue `publication`, `delta.commun` vues `entree`, `synchro`, `traductions` et `sources`, `delta.personnel` vue `sources`, `delta.config` v1 pour le bootstrap. Tous sont fermés, et leur version majeure inconnue est refusée.
9. **Classement** : `entrees[].systemes` est ajouté en C (calculé par la génération), `entrees[].historique[].avant[].revoir_le` en S (champ apparu depuis L1). `docs/data/actu/x-ids.json`, famille inconnue apparue depuis L1, reste refusé et tenu hors du commun.

## Preuves

- `tests/test_couches.py` et `tests/test_couches_l2.py` : 43 réussis, aucun sauté (route publiée comprise), sous `verrou-tests`.
- **Mutations : 8 garde-fous neutralisés un à un, 8 tués** : lecteur borné, contrôle des textes privés, `contexte_inattendu`, empreinte source du français, liste d'exclusion vide, validation de la génération synchronisée, repères manquants, arbre modifié hors de la route du service.
- Agent vérificateur, avant la publication : `verifier.py` ciblé vert (1 185 réussis, 1 sauté), plus 224 réussis sur couches, carte, vérificateur et valider. Avant commit, `scripts/verifier.py --cible` donne « VERIFY ciblé OK en 104,7 s » ; les avertissements de `valider.py` sont préexistants (R1, R4, R5, D124).
- Données réelles, instance d'essai dans le scratchpad (aucune écriture dans les vraies racines ni dans `docs/data`) : import en 3,5 s, relance sans écriture, `verifier --depot` donne `ok: true` (2 284 identités attendues, 2 296 communes, 12 ajouts, 1 861 avis, 1 718 réévaluations, 6 essais et 218 À tester, 188 rejugements).
- Traduction : 49 appels, 1 856 traductions distinctes acceptées. Il y a eu 41 refus, tous retraduits avec succès au second passage : 1 lot de 40 avec un JSON de réponse invalide, et 1 texte dont un repère s'est perdu. Contrôle du registre : 40 textes sur 1 856 vouvoient le lecteur (paragraphes narratifs longs). Statut `automatique`, à revoir en L6.
- Diff relu avant commit : chemins indexés explicitement, aucun chemin personnel (la notice systemd dit `~/projets/delta-ia`), courriel, id de mission ni projet. `rapports/` n'est pas commité.
- `mcp/` n'est pas touché : `npm test` n'était pas requis.

## Points fragiles ou à décider

- **Installation du service après fusion** (geste du pilote, notice `deploy/systemd/commun.md`) : tant que le minuteur n'est pas installé, la génération publiée vieillit, et `surveiller` signalera `cycle_manque` 30 h après 12:35.
- Budget de traduction nocturne : 0 par défaut. Pour traduire les fiches nouvelles chaque nuit, poser `production.budget_traduction` (par exemple 40) dans `~/.config/delta/delta-ia/config.json`, avec `mode: producteur`. Coût mesuré : environ 0,009 $ au prix catalogue et 50 s par lot de 40 textes.
- Un échec du service au milieu de sa course laisse `docs/commun/v1/` modifié dans l'arbre de main : la garde de la chaîne suivante le verra. C'est voulu, l'échec reste visible.
- L'isolation du rédacteur repose sur `--safe-mode` et sur la mesure des jetons d'entrée. Ce que Claude Code ajoute (environ 600 jetons de cadre) n'est pas inspectable directement ; le seuil détecte un CLAUDE.md ou une mémoire injectés, pas un ajout de quelques centaines de jetons.
- Le dépôt public grandit d'environ une génération par jour (fichiers changés seulement, Git dédoublonne les autres). La route garde la génération active et la précédente.

## Pour les lots suivants

- **L3** : lecteurs publics (MCP HTTP, site) sur la route `commun/v1`, les deux formats, URL centralisées par `bootstrap.json` ; retrait de `constats_internes` et `recommandation_operer` côté public.
- **L4** : MCP stdio et Desktop sur `Lecteur` (langue, fraîcheur et repli déjà rendus) ; l'overlay modèle × effort reste à faire.
- **L5** : régénérer `kb/modeles.json` depuis `production/sources-publiques.json` et le magasin privé ; phase commune quotidienne (titres et résumés EN/FR de la veille) ; bascule des producteurs.
- **L6** : relecture des 1 856 traductions automatiques (passage `automatique` → `revu`, les 40 vouvoiements), méthodes et modèles, interface EN/FR.
