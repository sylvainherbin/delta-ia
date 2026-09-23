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
- **Site public, choix assumé.** Seules les restrictions de `REGLES.md` s'appliquent.

## 3. Répartition des agents

| Agent | Périmètres | Produits | Écrit dans |
|---|---|---|---|
| Claude Code | `claude`, `actu` | `claude`, `claude-code`, `actu` (actualité IA générale) | `docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `state/claude.json`, `state/actu.json` |
| Codex | `openai` | `chatgpt`, `codex` | `docs/data/openai/`, `docs/data/kb/openai/`, `state/openai.json` |

Vocabulaire (D6) : un **périmètre** (`claude` | `openai` | `actu`) est l'unité de récupération, d'état, de dossier de données, du champ `perimetre` du fichier quotidien et du commit. Un **produit** (`claude` | `claude-code` | `chatgpt` | `codex` | `actu`) qualifie chaque élément.

Le lancement est manuel, une fois par jour :
- côté Claude Code, par la commande `/delta` ;
- côté Codex, par le prompt `prompts/codex-delta.md`.

## 4. Arborescence

```
delta-ia/
├── CLAUDE.md              # conventions Claude Code, importe SPEC.md et REGLES.md
├── AGENTS.md              # conventions Codex, renvoie à SPEC.md et REGLES.md
├── SPEC.md
├── REGLES.md
├── CONTEXTE.md            # généré par la session herbin-mint — lecture seule pour les agents
├── README.md
├── requirements.txt
├── sources.yaml           # sources et leur statut
├── scripts/
│   ├── fetch.py           # récupération + détection des nouveautés
│   └── valider.py         # validation du schéma des JSON avant commit (phase 2)
├── tests/
├── state/
│   ├── claude.json
│   ├── openai.json
│   └── actu.json
├── raw/                   # cache de récupération, ignoré par git
├── .claude/commands/delta.md
├── prompts/codex-delta.md
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

1. `git pull --rebase` (seulement si un dépôt distant existe, voir Git ci-dessous).
2. `python scripts/fetch.py --perimetre <p>`. Le script écrit les nouveautés dans `raw/<p>-nouveautes.json` **sans toucher à l'état**.
3. L'agent lit les nouveautés, `CONTEXTE.md` et la base de référence existante.
4. L'agent écrit `docs/data/<dossier>/AAAA-MM-JJ.json`, met à jour son `index.json`, puis la base de référence si une nouveauté la touche.
5. `python scripts/valider.py` vérifie les JSON produits.
6. `python scripts/fetch.py --perimetre <p> --valider`. **L'état n'avance que maintenant**, une fois la synthèse écrite et validée. Si l'agent échoue en cours de route, aucune nouveauté n'est perdue. Règle (D5) : `--valider` n'inscrit dans l'état que les identifiants présents dans `docs/data/<dossier>/<date>.json` ; les identifiants absents restent en attente et sont listés ; les éléments ignorés (`ignores`) sont inscrits directement. Mise en œuvre avec `valider.py` en phase 2.
7. Commit sur les seuls chemins de l'agent, puis push selon les règles Git ci-dessous.

Comportement de `fetch.py` :
- **Identifiants (D1)** : la clé native de la source, jamais le titre. Flux JSON OpenAI : `oa-<id>` (commun aux flux `general`, `codex-app` et `ios`, donc dédoublonnage) ; RSS : `guid`, sinon `link` ; Atom : `<id>` ; releases GitHub : le tag ; changelog Claude Code : `claude-code-<version>` ; newsroom : l'URL de l'article ; notes datées : `<source>-<date>`. Avec l'option `suivre_revisions: true`, une empreinte du contenu est stockée dans l'état ; si l'identifiant est connu mais l'empreinte a changé, l'élément revient en nouveauté avec `revision: true`.
- **Produit par entrée (D2)** : pour `general.json`, « codex » dans le titre ou les sujets (insensible à la casse) donne `codex`, sinon `chatgpt`.
- **Non datés (D3)** : un élément sans date n'est jamais ignoré à cause d'une fenêtre, c'est une nouveauté. Seule exception, le changelog Claude Code : les versions strictement inférieures à la plus ancienne version datée par l'API sont de l'historique, donc ignorées.
- **Détection de trou (D4)** : chaque analyseur reçoit une borne (date du dernier `--valider`, sinon le début de la fenêtre) et renvoie la date la plus ancienne qu'il a vue. Si elle est postérieure à la borne, la source passe en `partiel` avec le message « trou possible entre <borne> et <date> ». Pour les releases GitHub, pagination adaptative : page suivante tant que la plus ancienne release est postérieure à la borne, 4 pages au plus, puis `partiel` ; `releases/latest` garantit la dernière version stable.
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
  "elements": []
}
```

### 7.2 Élément

| Champ | Type | Règle |
|---|---|---|
| `id` | string | Clé native de la source (D1, voir §6) : tag, `oa-<id>`, guid, URL, `claude-code-<version>`, `<source>-<date>` |
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
| `kb_refs` | array | Identifiants des entrées de la base de référence touchées |

### 7.3 Index — `docs/data/<dossier>/index.json`

La liste des dates disponibles, avec pour chacune le nombre d'éléments par niveau d'impact et l'horodatage du dernier passage.

### 7.4 Base de référence — `docs/data/kb/<claude|openai>/<categorie>.json`

Catégories : `fonctionnalites`, `commandes`, `skills`, `plugins`, `mcp`, `parametres`, `raccourcis`.

Champs d'une entrée : `id`, `produit`, `categorie`, `nom`, `description`, `usage` (syntaxe et exemple), `disponibilite` (plan ou plateforme, `null` si inconnue), `statut_usage` (`utilise` | `non_utilise` | `inconnu`, d'après CONTEXTE.md), `recommandation` (`{verdict: "utiliser" | "tester" | "ignorer", pourquoi}`), `sources`, `maj_le`, `historique` (`[{date, changement}]`).

## 8. Site

Pages ou onglets :
- **Aujourd'hui** : les synthèses du jour par périmètre, puis les éléments triés par impact, avec un filtre par produit.
- **Changelogs** : par produit, en ordre chronologique.
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

Notifications, retour utile/inutile, hébergement privé, automatisation par cron.

## 11. Points ouverts

- URL exactes des sources : fixées en phase 1 (`sources.yaml`) ; le centre d'aide ChatGPT reste bloqué (403), repli par recherche web.
- Accès réseau de Codex : son sandbox peut bloquer le réseau par défaut. Configuration à vérifier avant la phase 2.
- Mécanisme de prompts personnalisés de Codex : à vérifier. À défaut, le contenu de `prompts/codex-delta.md` est collé à la main.

## 12. Décisions (23/09/2026)

Prises par la session Delta-IA (relecteur) par délégation de Sylvain, après relecture du commit `781b418` (phase 1).

| # | Décision | Reportée dans |
|---|---|---|
| D1 | Identifiants par clé native, sans le titre ; option `suivre_revisions` avec empreinte du contenu et `revision: true` | §6, §7.2 |
| D2 | `general.json` : produit déterminé par entrée (« codex » dans le titre ou les sujets → `codex`, sinon `chatgpt`) | §6 |
| D3 | Un élément non daté est une nouveauté ; exception : historique du changelog Claude Code sous la plus ancienne version datée | §6 |
| D4 | Détection de trou par borne et date la plus ancienne vue ; pagination adaptative des releases GitHub (4 pages max) ; Atom GitHub écarté | §6 |
| D5 | `--valider` n'inscrit que les identifiants présents dans le fichier quotidien ; mise en œuvre en phase 2 avec `valider.py` | §6 |
| D6 | Vocabulaire : périmètre (`claude` \| `openai` \| `actu`) distinct de produit (`claude` \| `claude-code` \| `chatgpt` \| `codex` \| `actu`) | §3 |
| D7 | Statuts `ok`, `a_valider` (observation, 7 passages), `desactive`, `bloque` | §5 |
| D8 | OpenAI News : filtre `Product, Release, ChatGPT, API` inchangé, catégorie `API` en produit `chatgpt` ; chiffres recomptés dans `sources.yaml` | `sources.yaml` |
| D9 | Git : pas de pull ni push sans distant ; `/delta` ou le prompt Codex vaut accord de push sur les chemins de l'agent ; en développement, push sur accord de Sylvain | §6, `CLAUDE.md`, `AGENTS.md` |
| D10 | Premier passage réel de la phase 2 avec `--depuis` J-7, jamais avant D3 | §6 |
| D11 | Type `json`, statut `desactive`, champs `officielle` et `options` ajoutés à SPEC.md ; REGLES.md inchangé | §5 |

