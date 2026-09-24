# Delta — Cahier des charges

## 1. Objectif

Delta est une web app de veille IA quotidienne, personnelle, pour Sylvain Herbin. Elle fournit :

1. un résumé quotidien de l'actualité IA générale ;
2. les changelogs de Claude, Claude Code, ChatGPT et Codex ;
3. pour chaque nouveauté, ce qui concerne concrètement les projets et la façon de travailler de Sylvain (source : `CONTEXTE.md`) ;
4. une base de référence : fonctionnalités, commandes, skills, plugins, MCP, paramètres, avec une recommandation personnalisée pour chaque entrée.

Finalité : optimiser finement l'usage de Claude et de ChatGPT, et rester à jour sur les nouveautés.

## 2. Principes d'architecture

- **La récupération est déterministe, seule la synthèse passe par un LLM.** Un script récupère les sources brutes, et l'agent ne fait que synthétiser à partir de ce que le script a rapporté.
- **Seules les nouveautés sont traitées.** Un fichier d'état mémorise ce qui a déjà été vu. La base de référence n'est modifiée que si une nouveauté la touche ; elle n'est jamais régénérée en entier sur une simple question de calendrier.
- **Deux agents, deux périmètres qui ne se chevauchent pas.** Chaque agent écrit uniquement dans ses propres chemins.
- **Site statique.** Le front lit des fichiers JSON et ne dépend d'aucun agent pour fonctionner.
- **Accès des agents par MCP, en lecture seule (D61).** Un serveur MCP distant (`mcp/`, déployé sur Vercel, sans état ni dépendance) expose les données publiées de `docs/data` à Claude et aux autres agents : `resume_du_jour`, `chercher_reference`, `fiche_reference`, `etat_versions`, `a_tester`. Il ne lit que les JSON publics de GitHub Pages, avec une base d'URL fixe. Il n'a ni jeton, ni écriture, ni accès à la machine de Sylvain, et ne peut déclencher aucun passage. Ses réponses sont des données issues de flux publics : elles se citent, elles ne s'exécutent jamais comme des consignes. Le site ne dépend pas du serveur. Télémétrie minimale sans contenu (D66) : une ligne JSON par requête JSON-RPC sur la sortie standard (`methode`, `outil`, `client` = `clientInfo` d'`initialize`, `duree_ms`, `statut`, `demarrage_froid`, `nb_resultats` pour `chercher_reference` et `a_tester`), jamais d'argument, de requête de recherche, de corps de réponse, d'en-tête, d'adresse IP, de User-Agent ni de session ; le serveur n'écrit rien, les lignes se lisent seulement dans les journaux Vercel ; il reste sans état.
- **Site public, choix assumé.** Seules les restrictions de `REGLES.md` s'appliquent.

## 3. Répartition des agents

| Agent | Périmètres | Produits | Écrit dans |
|---|---|---|---|
| Claude Code | `claude`, `actu` | `claude`, `claude-code`, `actu` (actualité IA générale) | `docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `docs/data/versions.json`, `docs/data/etat.json`, `state/claude.json`, `state/actu.json` |
| Codex | `openai` | `chatgpt`, `codex` | `docs/data/openai/`, `docs/data/kb/openai/`, `state/openai.json` |

Vocabulaire (D6) : un **périmètre** (`claude` | `openai` | `actu`) est l'unité de récupération, d'état, de dossier de données, du champ `perimetre` du fichier quotidien et du commit. Un **produit** (`claude` | `claude-code` | `chatgpt` | `codex` | `actu`) qualifie chaque élément.

Le lancement est manuel, une fois par jour (D16, vérifié sur Claude Code 2.1.280 et codex-cli 0.155.0-alpha.16 le 23/09/2026) :
- côté Claude Code, par `/delta`, skill du dépôt `.claude/skills/delta/SKILL.md` (`disable-model-invocation: true` : seul Sylvain la déclenche) ; elle enchaîne `claude` puis `actu` ;
- côté Codex, par `$delta`, skill du dépôt `.agents/skills/delta/SKILL.md` (`allow_implicit_invocation: false`) ; à défaut, `prompts/codex-delta.md`, de contenu identique, est collé à la main. Les custom prompts de Codex sont dépréciés depuis le 22/01/2026.

## 4. Arborescence

```
delta-ia/
├── CLAUDE.md              # conventions Claude Code, importe SPEC.md et REGLES.md
├── AGENTS.md              # conventions Codex, renvoie à SPEC.md et REGLES.md
├── SPEC.md
├── REGLES.md
├── CONTEXTE.md            # généré par la session herbin-mint — lecture seule pour les agents
├── PROGRESSION.md         # formation de Sylvain, écrit par la seule session professeur — lecture seule pour les agents (D67)
├── README.md
├── requirements.txt
├── sources.yaml           # sources et leur statut
├── scripts/
│   ├── fetch.py           # récupération + détection des nouveautés ; --valider piloté par le fichier quotidien
│   ├── valider.py         # validation des JSON produits avant commit (D15) ; --kb pour la base (§7.4)
│   ├── catalogue.py       # base de référence : extraction, inventaire, lots, application des commentaires
│   ├── versions.py        # versions installées des outils -> docs/data/versions.json (D54)
│   ├── etat.py            # état volatil : modèles et profils, MCP et connecteurs, instructions globales -> docs/data/etat.json (D65)
│   └── deltalib/          # bibliothèque : analyseurs, état, passage, kb/ (documentation, extracteurs, catalogue)
├── tests/
├── state/
│   ├── claude.json
│   ├── openai.json
│   └── actu.json
├── raw/                   # cache de récupération, ignoré par git ; raw/kb/ : pages de documentation et empreintes
├── rapports/              # comptes rendus de fin de tâche des agents, lus par Delta-IA ; ignoré par git sauf .gitkeep (D63)
├── .claude/skills/delta/SKILL.md   # /delta pour Claude Code (les commandes sont fusionnées dans les skills depuis 2.1.x)
├── .claude/skills/delta-kb/       # /delta-kb : commentaire de la base de référence claude, par lots (D46)
├── .agents/skills/delta-kb/       # $delta-kb : idem pour openai ; prompts/codex-delta-kb.md en repli
├── .agents/skills/delta/           # $delta pour Codex : SKILL.md (même texte que prompts/codex-delta.md) + agents/openai.yaml
├── prompts/codex-delta.md          # repli : texte à coller à la main dans Codex
├── mcp/                   # connecteur MCP distant en lecture seule (D61), déployé sur Vercel
│   ├── api/mcp.js         # serveur Streamable HTTP, sans état ni dépendance
│   ├── test/              # tests node:test et serveur local
│   ├── package.json
│   └── vercel.json
└── docs/                  # racine GitHub Pages
    ├── index.html
    ├── assets/
    └── data/
        ├── claude/        # AAAA-MM-JJ.json + index.json
        ├── openai/
        ├── actu/
        └── kb/
            ├── claude/
            └── openai/
```

Chaque agent tient son propre `index.json` ; le front fusionne les index. Aucun fichier n'est partagé en écriture entre les deux agents.

## 5. Sources

Les sources sont déclarées dans `sources.yaml`, avec les champs suivants : `id`, `perimetre`, `produit`, `type` (`github_changelog` | `github_releases` | `html` | `rss` | `json`), `url`, `statut`, `officielle` (booléen : source de l'éditeur), `note`, et `options` (facultatif, propre au type : `inclure_prereleases`, `categories`, `format`, `suivre_revisions`, `produit_par_entree`, `releases_url`, `url_latest`…).

Statuts (D7) :
- `ok` : source fiable ;
- `a_valider` : source active, en observation ; elle passe à `ok` après 7 passages réels sans échec ni bruit anormal, avec une mention dans `note` ;
- `desactive` : conservée dans le fichier, non traitée ;
- `bloque` : testée, en échec.

`fetch.py` ne traite que `ok` et `a_valider`. Un endpoint non documenté publiquement n'est accepté que testé, et sa `note` indique qu'il peut changer sans préavis.

Candidates (URL exactes à identifier et tester en phase 1, **aucune URL ne doit être inscrite sans avoir été testée**) :

| Produit | Source | Fiabilité attendue |
|---|---|---|
| Claude Code | `CHANGELOG.md` du dépôt `anthropics/claude-code` | Élevée |
| Codex CLI | Releases du dépôt `openai/codex` (API GitHub) | Élevée |
| Claude (apps) | Release notes officielles Anthropic | À vérifier |
| Claude (API / plateforme) | Release notes de la documentation Anthropic | À vérifier |
| ChatGPT | Release notes du centre d'aide OpenAI | Scraping possiblement bloqué |
| Codex (hors CLI) | Changelog de la documentation développeurs OpenAI | À vérifier |
| Actu IA | Blogs officiels des principaux labos + une sélection de médias spécialisés, en RSS | Liste à valider par Sylvain |

**Solution de repli** : si une source est bloquée, l'agent utilise sa recherche web. L'URL est alors obligatoire et l'élément est marqué `certitude: rapporte`.

## 6. Passage quotidien

0. Si `.git/index.lock` existe, s'arrêter et le signaler : les passages Claude Code et Codex ne tournent jamais en même temps (D21). Calculer la date du passage `J` une seule fois et la passer explicitement à `valider.py` et à `fetch.py --valider` (D19), sinon un passage qui franchit minuit vise le mauvais fichier.
1. `git pull --rebase` (seulement si un dépôt distant existe, voir Git ci-dessous).
2. `python scripts/fetch.py --perimetre <p>`. Le script écrit les nouveautés dans `raw/<p>-nouveautes.json` **sans toucher à l'état**.
3. L'agent lit les nouveautés, `CONTEXTE.md` et la base de référence existante.
4. L'agent écrit `docs/data/<dossier>/AAAA-MM-JJ.json`, met à jour son `index.json`, puis la base de référence si une nouveauté la touche.
5. `python scripts/valider.py --perimetre <p> --date J --brut raw/<p>-nouveautes.json` vérifie les JSON produits (schéma §7, cohérences, couverture des nouveautés brutes, secrets, `index.json`). Ne pas pousser s'il échoue.
6. `python scripts/fetch.py --perimetre <p> --valider --date J`. **L'état n'avance que maintenant**, une fois la synthèse écrite et validée. Si l'agent échoue en cours de route, aucune nouveauté n'est perdue. Règle (D5, D13) : `--valider` lit `docs/data/<dossier>/<date>.json` (option `--date`, défaut aujourd'hui) et inscrit dans l'état les `ids_bruts` de chaque élément, les `ecartes`, les `ignores` du fichier brut et les identifiants `web-*`. Les nouveautés brutes absentes du fichier quotidien restent en attente, sont listées, et la commande rend un code de sortie non nul.
7. Commit sur les seuls chemins de l'agent, puis push selon les règles Git ci-dessous.

État volatil (D65) : dans le passage de Claude Code, juste après `versions.py`, `scripts/etat.py` écrit `docs/data/etat.json` : modèle, effort et profils par défaut de Claude Code et de Codex (fichiers de configuration), serveurs MCP et connecteurs visibles (`claude mcp list` dans ~/projets, ~/projets/delta-ia et ~/projets/trading-sim, `mcp_servers` de `config.toml`), présence et date des `CLAUDE.md` et `AGENTS.md` globaux, `releve_le`. Chaque relevé porte `{valeur, source, raison}`, `raison` étant obligatoire quand la valeur est `null`. Aucun secret (ni `env`, ni arguments, ni paramètres d'URL) et aucun quota (`rapports/usage.json`, local). `valider.py` le contrôle ; pour ces valeurs, il prime sur CONTEXTE.md, dont herbin-mint retire les lignes devenues redondantes.

Base de référence (D44) : dans chaque passage, l'agent lance `fetch.py --kb` (avec `--dry-run`, rien n'est écrit, ni catalogue ni cache `raw/kb/`, D47) sur les produits de son périmètre (`claude-code claude` pour Claude Code, `codex chatgpt` pour Codex). Le script relit uniquement les pages de référence de `sources.yaml` (copie et empreinte par page dans `raw/kb/`), ré-extrait les entrées et met à jour `docs/data/kb/<p>/` ; les entrées ajoutées ou dont `usage` a changé repassent en `commentee: false` et sont listées dans `raw/kb/<p>-modifications.json`. L'agent les commente pendant le passage, renseigne `kb_refs` et valide avec `valider.py --kb`.

Comportement de `fetch.py` :
- **Identifiants (D1)** : la clé native de la source, jamais le titre. Flux JSON OpenAI : `oa-<id>` (commun aux flux `general`, `codex-app` et `ios`, donc dédoublonnage) ; RSS : `guid`, sinon `link` ; Atom : `<id>` ; releases GitHub : le tag ; changelog Claude Code : `claude-code-<version>` ; newsroom : l'URL de l'article ; notes datées : `<source>-<date>`. Avec l'option `suivre_revisions: true`, une empreinte du contenu est stockée dans l'état ; si l'identifiant est connu mais l'empreinte a changé, l'élément revient en nouveauté avec `revision: true`.
- **Produit par entrée (D2bis)** : `general.json` est le changelog Codex, produit `codex` par défaut ; `chatgpt` seulement si « chatgpt » apparaît dans le titre ou les sujets (insensible à la casse) et que « codex » n'y apparaît pas.
- **Non datés (D3)** : un élément sans date n'est jamais ignoré à cause d'une fenêtre, c'est une nouveauté. Seule exception, le changelog Claude Code : une version non datée inférieure à la plus haute version datée par l'API est de l'historique, donc ignorée (D27) ; seule une version non datée plus récente que toutes les versions datées est une nouveauté.
- **Détection de trou (D4)** : chaque analyseur reçoit une borne (date du dernier `--valider`, sinon le début de la fenêtre) et renvoie la date la plus ancienne qu'il a vue. Si elle est postérieure à la borne, la source passe en `partiel` avec le message « trou possible entre <borne> et <date> ». Pour les releases GitHub, pagination adaptative : page suivante tant que la plus ancienne release est postérieure à la borne, 4 pages au plus, puis `partiel` ; `releases/latest` garantit la dernière version stable. Pour un flux RSS filtré par catégorie, la date la plus ancienne est celle du flux entier, avant filtrage (D12).
- **Premier passage sans état** : fenêtre de 30 jours, ou `--depuis`. Les éléments datés avant la fenêtre vont dans `ignores` et sont inscrits dans l'état par `--valider`. Le premier passage réel de la phase 2 se fait avec `--depuis` J-7 (D10).

Git (D9) :
- Tant qu'il n'y a pas de dépôt distant (phase 2) : ni pull ni push, commit local seulement.
- Une fois le distant créé : lancer `/delta` ou le prompt Codex vaut accord de push, sur les seuls chemins de l'agent.
- En session de développement : push seulement sur accord explicite de Sylvain.

Le passage est **idempotent** : relancer le même jour fusionne avec le fichier existant au lieu de créer un doublon.

S'il n'y a aucune nouveauté, le fichier du jour est quand même écrit, avec `elements: []`, pour que le site montre que le passage a bien eu lieu.

## 7. Format des données

### 7.1 Fichier quotidien — `docs/data/<dossier>/AAAA-MM-JJ.json`

```json
{
  "date": "AAAA-MM-JJ",
  "perimetre": "claude",
  "agent": "claude-code",
  "genere_le": "ISO 8601",
  "synthese": "2 à 4 phrases : ce qui compte aujourd'hui pour Sylvain.",
  "sources_en_echec": [],
  "elements": [],
  "ecartes": [],
  "contexte_empreinte": "sha1 de CONTEXTE.md au moment de la synthèse"
}
```

`contexte_empreinte` (D58) : sha1 de CONTEXTE.md (`sha1sum CONTEXTE.md`), obligatoire pour les fichiers datés après le 23/09/2026. À la fusion avec un fichier du jour existant, si l'empreinte a changé, l'agent réévalue les `pour_toi`, `impact` et `action` de tous les éléments du jour. Un `pour_toi` n'affirme sur la machine, les sessions ou les projets de Sylvain que ce que CONTEXTE.md dit explicitement ; une déduction se formule au conditionnel (D59).

`sources_en_echec` reprend celles du fichier brut (`[{id, url, erreur, partiel}]`). `ecartes` (D13) liste, sous la forme `[{id, raison}]`, les nouveautés brutes sans aucun rapport avec l'usage des outils IA (marketing, offres sectorielles…). Chaque nouveauté brute du passage se retrouve soit dans les `ids_bruts` d'un élément, soit dans `ecartes`. `ecartes` et `impact: nul` sont distincts (D14) : un élément `nul` est pertinent pour le produit mais pas pour Sylvain, il est affiché.

### 7.2 Élément

| Champ | Type | Règle |
|---|---|---|
| `id` | string | Le premier de `ids_bruts`. Élément issu de la recherche web (repli, certitude `rapporte`) : `web-<sha1(url + "\|" + date_publication + "\|" + titre normalisé)[:12]>` (D20 ; titre normalisé = minuscules, sans accents ni ponctuation ; date inconnue = chaîne vide ; fonction `id_web` de `deltalib.modeles`), après vérification qu'il n'est ni dans l'état ni dans les fichiers quotidiens des 14 derniers jours |
| `ids_bruts` | array | Au moins un identifiant brut (D1, D13). Plusieurs si un même événement vient de plusieurs sources : un seul élément, toutes les URL dans `sources` |
| `revision` | bool | Facultatif ; `true` si l'élément reprend une entrée déjà vue dont le contenu a changé |
| `produit` | enum | `claude` \| `claude-code` \| `chatgpt` \| `codex` \| `actu` |
| `titre` | string | |
| `version` | string \| null | |
| `date_publication` | string \| null | `null` si inconnue, **jamais devinée** |
| `type` | enum | `nouveaute` \| `amelioration` \| `correction` \| `changement_rupture` \| `depreciation` \| `actu` |
| `resume` | string | Factuel, sans ton promotionnel |
| `sources` | array | `[{url, libelle, officielle: bool}]`, au moins une |
| `certitude` | enum | `officiel` \| `rapporte` \| `non_confirme` |
| `impact` | enum | `fort` \| `moyen` \| `faible` \| `nul` (définitions dans REGLES.md) |
| `pour_toi` | string \| null | Recommandation personnalisée ; `null` si l'impact est `nul` |
| `projets_concernes` | array | Noms de projets tirés de CONTEXTE.md |
| `action` | object \| null | `{description, etapes, effort: "5min" \| "30min" \| "plus"}` |
| `kb_refs` | array | Identifiants des entrées de la base de référence touchées ; `valider.py` vérifie qu'ils existent |
| `contexte_sections` | object | D64-bis : `{ctx-id: {sha1, pourquoi}}` des sections de CONTEXTE.md sur lesquelles reposent `pour_toi`, `impact` et `action` (gabarit par `scripts/contexte.py --sections`), `pourquoi` en une ligne de 160 caractères au plus, `{}` si aucune ; obligatoire pour les fichiers datés après le 24/09/2026 ; `valider.py` refuse un ctx-id inconnu et un pourquoi vide |

### 7.3 Index — `docs/data/<dossier>/index.json`

La liste des dates disponibles, avec pour chacune le nombre d'éléments par niveau d'impact et l'horodatage du dernier passage :

```json
{
  "perimetre": "claude",
  "agent": "claude-code",
  "maj_le": "ISO 8601",
  "jours": [
    {"date": "AAAA-MM-JJ", "genere_le": "ISO 8601", "elements": 0,
     "impact": {"fort": 0, "moyen": 0, "faible": 0, "nul": 0}, "ecartes": 0}
  ]
}
```

`jours` est trié par date décroissante et correspond exactement aux fichiers `AAAA-MM-JJ.json` du dossier ; `valider.py` le vérifie.

### 7.4 Base de référence — `docs/data/kb/<claude|openai>/<categorie>.json`

Catégories : `fonctionnalites`, `commandes`, `skills`, `plugins`, `mcp`, `parametres`, `raccourcis`. Les sept fichiers sont toujours écrits, même vides : `{perimetre, categorie, maj_le, total, commentees, entrees}`.

Chaque entrée naît en deux étapes (D40) :
1. **Extraction** par `scripts/catalogue.py` (appelé par `fetch.py --kb`), sans aucun modèle, depuis les pages de référence déclarées dans `sources.yaml` (section `documentation`) : `id`, `nom`, `usage`, `description_source`, `sources`, `commentee: false`.
2. **Commentaire** par l'agent du périmètre (skill `/delta-kb` ou `$delta-kb`, puis passages quotidiens) : `description` en français, `statut_usage`, `recommandation`, éventuellement `exemple` et `disponibilite`, puis `commentee: true`. L'agent ne modifie jamais `usage` ; `scripts/catalogue.py appliquer` le refuse.

| Champ | Règle |
|---|---|
| `id` | `<produit>-<categorie>-<slug>`, stable ; pour une page de fonctionnalité, le slug suit le chemin de la page, pas son titre |
| `produit`, `categorie`, `nom` | Extraits |
| `gabarit` | `complet` (fonctionnalités, commandes, skills, plugins, MCP) ou `court` (paramètres, variables d'environnement, options CLI, clés `config.toml`, raccourcis) (D41) |
| `usage` | Syntaxe exacte recopiée de la documentation (bloc de code, clé, commande, raccourci, liste d'étapes), jamais reformulée |
| `usage_nature` | `syntaxe` (commande, clé, bloc de code) ou `etapes` (chemin d'accès ou étapes recopiés d'une page narrative), fixée par l'extraction ; la page Référence affiche « Syntaxe » ou « Accès » (D49) |
| `description_source` | Description d'origine, en anglais, conservée |
| `description` | `null` tant que l'entrée n'est pas commentée ; ensuite, en français : 2 ou 3 phrases (complet), 1 phrase (court) |
| `exemple` | Gabarit complet : exemple recopié de la documentation, ou `null` |
| `disponibilite` | Plan ou plateforme si la documentation le dit, sinon `null` |
| `statut_usage` | `utilise` \| `non_utilise` \| `inconnu`, d'après CONTEXTE.md ; `inconnu` avant commentaire ; `utilise` aussi pour un id cité dans la section « Adoptions » de PROGRESSION.md (`catalogue.py adoptions`, historique « adoption déclarée, PROGRESSION.md », D67) |
| `recommandation` | `{verdict: "utiliser" \| "tester" \| "ignorer", pourquoi}` ; `pourquoi` en 1 ou 2 phrases (complet), 1 phrase (court), justifié par un projet ou une habitude de CONTEXTE.md (D26) ; `utiliser` exige un usage actuel d'après CONTEXTE ou un lien direct avec un objectif déclaré, un rattachement générique donne au plus `tester` (D57) ; `null` avant commentaire |
| `sources` | `[{url, libelle, officielle}]`, au moins une ; la première est la page d'extraction |
| `commentee` | `false` à l'extraction, et de nouveau `false` quand `usage` ou `description_source` change dans la documentation (D44, D48) |
| `contexte_empreinte` | sha1 de CONTEXTE.md au moment du commentaire, inscrit par `catalogue.py appliquer` ; `null` avant commentaire. Chaque fichier porte aussi l'empreinte du CONTEXTE.md courant : historique : la péremption suit `contexte_sections` (D64-bis, qui remplace D60) |
| `contexte_sections` | D64-bis : `{ctx-id: {sha1, pourquoi}}`. La clé est le ctx-id de la section (commentaire `<!-- ctx-id: … -->` sous chaque titre `#`, `##`, `###` de CONTEXTE.md, obligatoire et unique ; `scripts/contexte.py` le vérifie), jamais son numéro ni son titre. Le sha1 porte sur le corps propre de la section, du titre jusqu'au titre suivant quel que soit son niveau, sans la ligne de titre ni la ligne ctx-id : renommer une section ne périme rien. L'agent fournit `{ctx-id: pourquoi}`, en citant le ctx-id le plus précis ; une section au corps vide (titre seul, sha1 de la chaîne vide) ne se cite pas, on cite sa sous-section, et `valider.py` le refuse ; `catalogue.py appliquer` calcule les sha1. `{}` si le jugement ne dépend d'aucune section. Une entrée est périmée si l'une de ses sections a changé, disparu ou est dépréciée (`<!-- ctx-id-deprecie: X -->`). `null` pour les commentaires antérieurs à D64 (les formats de ae895e6 aussi : aucune correspondance rétroactive), affichés « antérieur à D64 ». Lot `perimees`, 30 entrées par lancement de `/delta-kb` ou `$delta-kb`, avant les lots, dans cet ordre : a) section citée modifiée ou dépréciée, tout verdict ; puis, motif `adoption`, les entrées `ignorer` passées en `utilise` par une adoption déclarée (D67) et pas recommentées depuis ; b) entrées `null` en `utiliser` ou `tester` ; c) filet par âge : toute entrée commentée, `ignorer` et `null` compris, dont le dernier commentaire date de plus de 90 + (sha1(id) mod 90) jours, le décalage étalant la vague initiale sur 90 jours (environ 8 entrées par jour et par base, absorbées par un lancement quotidien). Journal : `docs/data/kb/<p>/reevaluations.jsonl`, une ligne `{date, id, verdict_avant, verdict_apres, motif}` par réévaluation (`section:<ctx-id>`, `adoption`, `age`, `nouveau-projet:<ctx-id>`, `legacy`) ; chaque rapport de `/delta-kb` et `$delta-kb` donne le taux de verdicts changés (`catalogue.py reevaluations`). Échange assumé : la péremption est silencieuse si l'agent omet une section dont dépend son commentaire ; les mitigations sont le pourquoi par section, le journal et le filet par âge. Un nouveau projet (ctx-id `projet.*` absent de `projets_connus`) fait relire une fois, en gabarit court, les « ignorer » des fonctionnalités et commandes (lot `nouveau-projet:<ctx-id>`) ; les anciennes clés numérotées de `projets_connus` migrent vers les ctx-id sans ouvrir de lot |
| `retiree` | `true` quand l'entrée a disparu d'une page extraite avec succès ; jamais supprimée |
| `origine`, `groupe` | Documentation de `sources.yaml` et section de la page d'où vient l'entrée |
| `maj_le` | AAAA-MM-JJ du dernier changement |
| `historique` | `[{date, changement}]` : ajout, usage modifié, commentée, retirée, réapparue |

Périmètre (D42) : sont exclus l'entreprise et l'administration, les fournisseurs cloud (Bedrock, Vertex, Foundry), Windows et macOS (Linux, iOS et le web sont gardés) et l'API de la plateforme Claude.

Génération initiale (D46, D50, D51) : par lots (`scripts/catalogue.py lots`), dans l'ordre de valeur décroissante commandes, fonctionnalités, skills, plugins et MCP, raccourcis, paramètres ; une catégorie du gabarit complet de plus de 60 entrées est coupée en deux, les paramètres en quarts, et skills, plugins et MCP forment un seul lot pour openai ; deux lots au plus par lancement de `/delta-kb` ou `$delta-kb`, avec validation (`valider.py --kb`) et commit après chaque lot, jamais en même temps qu'un passage quotidien (D21).

## 8. Site

Pages ou onglets :
- **Aujourd'hui** : le bloc « Tes outils » (versions installées de Claude Code, du Codex de l'app ChatGPT, de la Codex CLI autonome, de ChatGPT Desktop et de Claude Desktop, dernière version publiée connue de Delta, à jour, en retard ou inconnu ; le Codex de l'app suit le canal de l'app et vaut `embarque`, non comparé ; la CLI autonome, installée mais non utilisée, vaut `non_utilise`, sans alerte de retard ; `docs/data/versions.json`, D54 à D56), les synthèses du jour par périmètre, puis les éléments triés par impact, avec un filtre par produit.
- **Changelogs** : par produit, en ordre chronologique.
- Sur Aujourd'hui, Changelogs et Actu, les éléments d'impact `nul` sont masqués par défaut, avec une bascule « afficher les éléments sans impact (n) » mémorisée dans le localStorage.
- **Actu IA**.
- **Référence** : la base de référence, avec une recherche plein texte et des filtres (produit, catégorie, verdict, statut d'usage).
- **À tester** : toutes les actions ouvertes. Une case « fait » est stockée dans le localStorage, donc propre à chaque navigateur.
- **Archives** : navigation par date.

Contraintes :
- mobile d'abord ;
- thème clair ou sombre automatique ;
- HTML/CSS/JS sans framework, sans étape de build ;
- aucune dépendance externe obligatoire ;
- la date du dernier passage de chaque agent est affichée, pour voir tout de suite si un agent n'a pas tourné.

## 9. Phases

Pour chaque phase, un plan est validé par Sylvain avant d'écrire le code, et des critères d'acceptation sont fixés.

1. **Fondations et récupération** : structure du dépôt, `sources.yaml` testé, `fetch.py`, fichiers d'état, tests. Complétée par la phase 1b (identifiants natifs, non datés, détection de trou, révisions).
2. **Synthèse** : `/delta`, prompt Codex, `valider.py`, premier passage réel pour chaque agent.
3. **Site.**
4. **Base de référence** : génération initiale complète, une seule fois, puis mise à jour pilotée par les nouveautés.
5. **Finitions** : recherche, archives, contrôle qualité.

## 10. Hors périmètre v1

Notifications, retour utile/inutile, hébergement privé, automatisation par cron. Pour le connecteur MCP (D61) : toute écriture, toute authentification et tout déclenchement de passage à distance restent hors périmètre ; un outil qui en aurait besoin exige une nouvelle décision.

## 11. Points ouverts

- URL exactes des sources : fixées en phase 1 (`sources.yaml`) ; le centre d'aide ChatGPT reste bloqué (403), repli par recherche web.
- Accès réseau de Codex : son sandbox peut bloquer le réseau par défaut. Configuration à vérifier avant la phase 2.
- Mécanisme de prompts personnalisés de Codex : à vérifier. À défaut, le contenu de `prompts/codex-delta.md` est collé à la main.

## 12. Décisions (23/09/2026)

Prises par la session Delta-IA (relecteur) par délégation de Sylvain, après relecture du commit `781b418` (phase 1).

| # | Décision | Reportée dans |
|---|---|---|
| D1 | Identifiants par clé native, sans le titre ; option `suivre_revisions` avec empreinte du contenu et `revision: true` | §6, §7.2 |
| D2 | `general.json` : produit déterminé par entrée. Remplacée par D2bis | §6 |
| D3 | Un élément non daté est une nouveauté ; exception : historique du changelog Claude Code sous la plus ancienne version datée | §6 |
| D4 | Détection de trou par borne et date la plus ancienne vue ; pagination adaptative des releases GitHub (4 pages max) ; Atom GitHub écarté | §6 |
| D5 | `--valider` n'inscrit que les identifiants présents dans le fichier quotidien ; mise en œuvre en phase 2 avec `valider.py` | §6 |
| D6 | Vocabulaire : périmètre (`claude` \| `openai` \| `actu`) distinct de produit (`claude` \| `claude-code` \| `chatgpt` \| `codex` \| `actu`) | §3 |
| D7 | Statuts `ok`, `a_valider` (observation, 7 passages), `desactive`, `bloque` | §5 |
| D8 | OpenAI News : filtre `Product, Release, ChatGPT, API` inchangé, catégorie `API` en produit `chatgpt` ; chiffres recomptés dans `sources.yaml` | `sources.yaml` |
| D9 | Git : pas de pull ni push sans distant ; `/delta` ou le prompt Codex vaut accord de push sur les chemins de l'agent ; en développement, push sur accord de Sylvain | §6, `CLAUDE.md`, `AGENTS.md` |
| D10 | Premier passage réel de la phase 2 avec `--depuis` J-7, jamais avant D3 | §6 |
| D11 | Type `json`, statut `desactive`, champs `officielle` et `options` ajoutés à SPEC.md ; REGLES.md inchangé | §5 |
| D2bis | `general.json` est le changelog Codex : `codex` par défaut, `chatgpt` seulement si « chatgpt » apparaît sans « codex » | §6 |
| D12 | Flux RSS filtré : `plus_ancienne` calculée sur le flux entier, avant filtrage | §6 |
| D13 | Chaque nouveauté brute est comptabilisée : `ids_bruts` sur l'élément, `ecartes` dans le fichier quotidien, id `web-*` pour la recherche web, `--valider` piloté par le fichier quotidien | §6, §7.1, §7.2 |
| D14 | `ecartes` (hors sujet) distinct de `impact: nul` (pertinent pour le produit, affiché) | §7.1 |
| D15 | `scripts/valider.py` : schéma §7, cohérences, projets de CONTEXTE.md §2, couverture du brut, secrets, `index.json` | §6 |
| D16 | Lancement : `/delta` selon le mécanisme de la version installée de Claude Code ; Codex par skill de dépôt si la documentation le permet, sinon `prompts/codex-delta.md` collé à la main | §3, phase 2a |
| D18 | `CONTEXTE.md` commité à part (`contexte: mise à jour herbin-mint du 23/09`) | — |
| D19 | La date du passage `J` est calculée une fois à l'étape 0 et passée à `valider.py --date J` et `fetch.py --valider --date J` | §6, skills |
| D20 | Identifiant web : `web-<sha1(url + "\|" + date_publication + "\|" + titre normalisé)[:12]>`, l'URL seule fait entrer en collision les entrées d'une même page | §7.2, skills |
| D21 | Étape 0 : si `.git/index.lock` existe, arrêt et signalement ; les passages Claude Code et Codex ne tournent jamais en même temps | §6, skills |
| D27 | Changelog Claude Code : une version non datée inférieure à la plus haute version datée est de l'historique (cas de la 2.1.243) | §6 |
| D40 | Base de référence en deux étapes : extraction par script sans modèle (`commentee: false`), puis commentaire de toutes les entrées par l'agent (`commentee: true`) ; `usage` jamais modifié par l'agent | §7.4 |
| D41 | Gabarits complet et court | §7.4 |
| D42 | Exclusions : entreprise et administration, fournisseurs cloud, Windows et macOS, API de la plateforme Claude | §7.4, `sources.yaml` |
| D44 | `fetch.py --kb` dans chaque passage quotidien ; entrées ajoutées ou à `usage` modifié recommentées pendant le passage | §6, skills |
| D45 | Arrêt avant toute génération, sur inventaire réel et estimation | phase 4 |
| D46 | Deux lots au plus par lancement de `/delta-kb` ou `$delta-kb`, étalés sur plusieurs jours | §7.4, skills |
| D47 | `fetch.py --kb --dry-run` n'écrit rien, cache `raw/kb/` compris | §6 |
| D48 | Un changement de `description_source` repasse aussi l'entrée en `commentee: false` | §7.4 |
| D49 | Champ `usage_nature` (`syntaxe` ou `etapes`) ; « Syntaxe » ou « Accès » sur la page Référence | §7.4 |
| D50 | Paramètres en quarts ; skills, plugins et MCP regroupés pour openai ; Android exclu | §7.4, `sources.yaml` |
| D51 | Ordre des lots : commandes, fonctionnalités, skills/plugins/MCP, raccourcis, paramètres | §7.4, skills |
| D53 | Nouveau design : thème selon le système, fond à halo et quadrillage, en-tête translucide avec logo « Prisme », pilules, cartes à liseré dégradé ; aucune dépendance externe ; contraste AA | §8 |
| D54 | `scripts/versions.py` : versions installées (commande, paquet), dernière version publiée seulement si une source de Delta la fournit | §4, §8 |
| D55 | `docs/data/versions.json` dans les chemins de Claude Code et contrôlé par `valider.py` | §3 |
| D56 | `versions.py` à l'étape 0 de `/delta` ; bloc « Tes outils » sur la page Aujourd'hui | §8, skill |
| D57 | Calibrage : `utiliser` exige un usage actuel ou un lien direct avec un objectif déclaré ; recalibrage ponctuel des 26 `utiliser` openai | §7.4, skills |
| D58 | `contexte_empreinte` dans chaque fichier quotidien ; réévaluation de tous les éléments du jour si CONTEXTE.md a changé | §7.1, skills |
| D59 | Un `pour_toi` n'affirme que ce que CONTEXTE.md dit ; les déductions au conditionnel | §7.1, skills |
| D60 | `contexte_empreinte` sur chaque entrée commentée ; signal sur la page Référence ; réévaluation prioritaire des `utiliser` et `tester` périmés. Remplacée par D64-bis | §7.4, skills |
| D61 | Connecteur MCP distant en lecture seule (`mcp/`, Vercel) : cinq outils de consultation, données publiques uniquement, sans jeton, écriture ni déclenchement | §2, §4, §10 |
| D63 | Comptes rendus de fin de tâche écrits par chaque agent dans `rapports/AAAA-MM-JJ_HHMM-<agent>-<tâche>.md` (en-tête : date et heure, agent, tâche, commits, contexte_empreinte), jamais commités | §4, skills, `CLAUDE.md`, `AGENTS.md` |
| D64 | Péremption par section de CONTEXTE.md (`scripts/contexte.py`, `contexte_sections` sur les entrées commentées et les éléments quotidiens) ; migration sans invention (`null`, « antérieur à D64 ») ; repasse des « ignorer » pour un nouveau projet. Remplacée par D64-bis | §7.2, §7.4, skills |
| D64-bis | Remplace D60 et D64 : péremption par ctx-id de CONTEXTE.md, `contexte_sections` `{ctx-id: {sha1, pourquoi}}`, sections dépréciées, lot `perimees` a/b/c avec filet par âge, journal `reevaluations.jsonl` et taux de verdicts changés ; échange assumé : une section omise ne périme rien | §7.2, §7.4, skills |
| D65 | État volatil hors de CONTEXTE.md : `scripts/etat.py` -> `docs/data/etat.json` (modèles et profils, MCP et connecteurs, instructions globales), relevé à chaque `/delta`, contrôlé par `valider.py`, lisible par les passages pour `pour_toi` | §3, §4, §6 |
| D66 | Journal minimal du serveur MCP pour mesurer l'usage (baseline d'une semaine avant la V1.1) : une ligne JSON par requête, sans contenu, lue seulement dans les journaux Vercel ; serveur toujours sans état. Conservation : plan Hobby maintenu (une heure de journaux ; Pro, drain et compteur côté serveur refusés), mesure par 5 ou 6 sondages ponctuels où Sylvain filtre `tools/call` dans Vercel → Logs dans l'heure suivant une séance réelle avec Work ou Codex et transmet les lignes à Delta-IA, qui les cumule, avant de concevoir la V1.1a ; signal prioritaire : `chercher_reference` avec `nb_resultats` = 0 | §2 |
| D67 | Formation : `PROGRESSION.md`, tenu par la seule session professeur, en lecture seule pour les agents et commité à part (`formation: …`) ; `/delta` et `$delta` le lisent pour doser la profondeur de `pour_toi` et `action` (acquis : pas de réexplication ; à travailler : plus détaillé), sans effet sur l'impact, le choix ni le tri des éléments, et sans empreinte ; `/delta-kb` et `$delta-kb` passent en `utilise` les id de sa section « Adoptions » (`catalogue.py adoptions`), consignés dans `historique` ; rien d'autre dans ce fichier n'agit sur la base | §4, §7.4, REGLES §1, skills |
