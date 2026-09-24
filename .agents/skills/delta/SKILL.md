---
name: delta
description: Passage quotidien de la veille Delta pour Codex — périmètre openai (ChatGPT et Codex), selon SPEC.md §6. À invoquer explicitement avec $delta, une fois par jour ; ne pas déclencher implicitement.
---

# Delta — passage quotidien (Codex, périmètre `openai`)

Tu exécutes le passage quotidien de Delta pour le périmètre `openai` (produits `chatgpt` et `codex`). Lis d'abord intégralement `SPEC.md`, `REGLES.md` (qui prime sur tout le reste) et `CONTEXTE.md`. Tu n'écris que dans `docs/data/openai/`, `docs/data/kb/openai/` et `state/openai.json`. Aucun code n'est modifié pendant un passage.

## 0. Préparation

- Si `git remote -v` est vide : ni pull ni push (SPEC §6, D9). Sinon `git pull --rebase` ; en cas de conflit, arrête-toi et signale.
- Si `.git/index.lock` existe, arrête-toi et signale-le : un autre passage (Claude Code) ou une autre session tient le dépôt ; les passages ne tournent jamais en même temps (D21).
- Calcule la date du passage **une seule fois** : `J=$(date +%F)`. Toutes les commandes et tous les fichiers du passage utilisent ce `J`, même si le passage franchit minuit (D19). Python : `.venv/bin/python`.

## 1. Récupération

Si `state/openai.json` est absent ou si sa clé `vus` est vide, c'est le premier passage réel : `.venv/bin/python scripts/fetch.py --perimetre openai --depuis $(date -d '-7 days' +%F)` (D10). Sinon : `.venv/bin/python scripts/fetch.py --perimetre openai`. Le fichier `raw/openai-nouveautes.json` contient `nouveautes`, `ignores`, `sources_en_echec`, `borne`. L'état n'est pas modifié.

## 2. Notes de version ChatGPT : relais releasebot, recherche web en repli

Le centre d'aide ChatGPT (`chatgpt-release-notes`) est bloqué (403). Les notes arrivent par le relais `releasebot-chatgpt` (D25) : source tierce, `officielle: false`, donc `certitude: rapporte` ; l'URL officielle figure en tête du `contenu` de chaque nouveauté et peut être ajoutée à `sources` telle quelle. Ne fais une recherche web que si `releasebot-chatgpt` figure dans `sources_en_echec` du brut, ou pour confirmer un point précis. Dans ce cas, cherche les notes de version ChatGPT publiées depuis la `borne` du brut (sources OpenAI d'abord : openai.com, help.openai.com ; médias ensuite). Pour chaque nouveauté trouvée : `certitude: rapporte`, URL obligatoire, et pour identifiant `web-<sha1(url + "|" + date_publication + "|" + titre normalisé)[:12]>` (D20 ; titre normalisé = minuscules, sans accents ni ponctuation ; date inconnue = chaîne vide), calculé par `.venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from deltalib.modeles import id_web; print(id_web('<url>', '<date ou vide>', '<titre>'))"`. L'URL seule ne suffit pas : toutes les entrées d'une même page de notes de version auraient le même identifiant. Avant de créer un tel élément, vérifie que l'identifiant n'est ni dans `state/openai.json` ni dans les fichiers `docs/data/openai/*.json` des 14 derniers jours. Une rumeur n'est jamais présentée comme un fait (`non_confirme`).

## 3. Synthèse dans `docs/data/openai/J.json` (SPEC §7.1 et §7.2, `agent: "codex"`)

- **Chaque nouveauté brute est comptabilisée** (D13) : soit dans les `ids_bruts` d'un élément, soit dans `ecartes: [{id, raison}]`. `ecartes` ne sert qu'à ce qui n'a aucun rapport avec l'usage des outils IA (marketing, offres sectorielles, événements). Ce qui concerne le produit mais pas Sylvain reste un élément avec `impact: nul` et `pour_toi: null` (D14).
- **Fusion des doublons** : un même événement rapporté par plusieurs sources (release GitHub + flux JSON + OpenAI News…) donne un seul élément, tous les identifiants bruts dans `ids_bruts`, toutes les URL dans `sources`. `id` = le premier de `ids_bruts`.
- `certitude: officiel` seulement si au moins une source a `officielle: true` (flux JSON, RSS ou GitHub sur un domaine OpenAI) ; `rapporte` pour la recherche web.
- **Tri (D24)** : `ecartes` reçoit tout ce qui ne touche ni les modèles, ni les outils et agents IA, ni les conditions de leur usage (prix, quotas, sécurité des agents, disponibilité). Robots industriels, procès, politique générale, faits divers, partenariats et applications sectorielles sont écartés, pas classés `nul`. Le 23/09, 19 des 23 éléments `actu` de Claude Code étaient en `nul` : c'était trop.
- **Événement déjà couvert (D31)** : une nouveauté qui décrit un événement déjà traité dans les fichiers `docs/data/openai/*.json` des 14 derniers jours, même sous un autre identifiant (une entrée `web-*` du 23/09 reprise ensuite par `releasebot-*`, une même annonce vue par la newsroom puis par les notes de version), va dans `ecartes` avec la raison « déjà couvert le <date> (<id>) ». Relis ces fichiers avant de créer un élément.
- **URL (D25)** : chaque URL de `sources` est copiée depuis la page effectivement consultée, jamais reconstruite ni devinée. Contre-exemple du 23/09 : `6825453-chatgpt-plus` cité à la place de `6825453-chatgpt-release-notes`.
- **Pertinence (D26)** : un projet n'entre dans `projets_concernes`, et un élément ne vaut `moyen` ou plus, que si la nouveauté change quelque chose de concret sur ce projet : une commande, un réglage, un flux de travail. Contre-exemple du 23/09 : le « Centre de confidentialité » de ChatGPT classé `moyen` et rattaché à trading-sim, alors qu'il ne change rien à la façon de travailler dessus.
- **Chiffres (D28)** : une comparaison garde sa référence : « 40 % moins cher qu'Opus 5 », jamais « 40 % moins cher » seul.
- `resume` factuel, 1 à 3 phrases, sans ton promotionnel envers OpenAI (REGLES §3) ; régressions, limites, hausses de prix, baisses de quota et retraits de modèles rapportés comme les nouveautés ; un changement défavorable vaut au moins `impact: moyen`.
- `pour_toi` et `action` s'appuient sur CONTEXTE.md : projet, outil ou habitude nommés, commande ou réglage exact. Priorités : trading-sim d'abord ; ce qui débloque Codex en CLI + tmux + remote control ; ce qui allège les limites hebdomadaires ; ce qui renforce les audits croisés Claude ↔ Codex. Ne fabrique jamais de pertinence.
- `projets_concernes` : uniquement des noms de CONTEXTE.md §2 (`carnet`, `trading-sim`, `chatgpt-trading-sim`, `ceramist`, `restoration-id`).
- `date_publication`, `version` : reprises du brut, `null` si inconnues, jamais devinées. `revision: true` si le brut le dit.
- `synthese` : 2 à 4 phrases sur ce qui compte aujourd'hui pour Sylvain ; s'il n'y a rien, une phrase le dit et `elements: []`.
- `sources_en_echec` : recopiées du brut.
- **Empreinte du contexte (D58)** : le fichier porte `contexte_empreinte`, le sha1 de CONTEXTE.md au moment de la synthèse (`sha1sum CONTEXTE.md | cut -c1-40`). À la fusion avec un fichier du jour existant, si son `contexte_empreinte` diffère de l'empreinte actuelle, réévalue les `pour_toi`, `impact` et `action` de **tous** les éléments du jour, pas seulement des nouveaux, puis mets l'empreinte à jour.
- **Constats et déductions (D59)** : un `pour_toi` n'affirme sur la machine, les sessions ou les projets de Sylvain que ce que CONTEXTE.md dit explicitement ; une déduction se formule au conditionnel (« si tes campagnes saturent la mémoire… »), jamais comme un constat. Contre-exemple du 23/09 : « ta machine est souvent sous pression mémoire pendant les campagnes », alors que la campagne R4 a tourné sans swap ni protection mémoire. Relis dans CONTEXTE.md, au moment d'écrire, chaque nombre que tu en tires (sessions, versions, compteurs, pourcentages).
- **Idempotence** : si `docs/data/openai/J.json` existe déjà, fusionne : conserve ses éléments, ajoute les nouveaux sans dupliquer un identifiant brut, mets à jour `synthese` et `genere_le`.

## 4. Index, base de référence, validation, état, commit

1. Mets à jour `docs/data/openai/index.json` (SPEC §7.3) : une entrée par fichier quotidien, triées par date décroissante, compteurs exacts.
2. **Base de référence (D44).** `.venv/bin/python scripts/fetch.py --kb codex chatgpt` relit les pages de référence (empreinte par page), ré-extrait et met à jour `docs/data/kb/openai/` ; il écrit `raw/kb/openai-modifications.json` (`ajoutees`, `usage_modifie`, `retirees`, `echecs`). Commente les entrées de `ajoutees` et `usage_modifie` selon les règles de la skill `$delta-kb` (`.agents/skills/delta-kb/SKILL.md`, section « Règles de commentaire ») et applique-les avec `scripts/catalogue.py appliquer`. Les entrées `retirees` et un `usage` modifié défavorablement sont des éléments du jour (`type: depreciation` ou `changement_rupture`). Renseigne `kb_refs` des éléments du jour qui touchent une entrée de la base. Le stock d'entrées jamais commentées relève de `$delta-kb`, pas du passage quotidien. Puis `.venv/bin/python scripts/valider.py --perimetre openai --kb` doit rendre 0.
3. `.venv/bin/python scripts/valider.py --perimetre openai --date $J --brut raw/openai-nouveautes.json`. Corrige jusqu'à ce qu'il rende 0. Ne commite pas s'il échoue.
4. `.venv/bin/python scripts/fetch.py --perimetre openai --valider --date $J`. Code 4 = des nouveautés brutes restent en attente : traite-les, revalide, relance. Code 0 attendu.
5. `git add docs/data/openai state/openai.json docs/data/kb/openai` (jamais `git add -A`), message `delta(openai): J — <n> éléments (<n> fort)`. Push seulement si un dépôt distant existe (D9).

## 5. Fin de passage

Relis les fichiers produits : aucun secret, aucune donnée de tiers identifiable (REGLES §5). Puis **confrontation à CONTEXTE.md (D29)** : pour chaque élément `fort` ou `moyen`, compare explicitement ce qu'il annonce (modèle, version, profil, outil, réglage) à ce que CONTEXTE.md décrit de l'usage de Sylvain, et note chaque écart : version installée dépassée, modèle par défaut remplacé, profil pointant sur un modèle retiré, outil abandonné. Contre-exemple du 23/09 : GPT-6 Sol remplaçait GPT-5.6 Sol, décrit dans CONTEXTE comme le modèle principal de Sylvain, et l'écart n'a pas été signalé. « Aucun point » n'est permis qu'après cette vérification, élément par élément. Une version **installée** ne se lit que dans `docs/data/versions.json`, jamais dans un changelog ni dans CONTEXTE.md. Contre-exemple du 23/09 : « version locale 0.155.1 » déclarée pour Codex, alors que 0.155.1 est une release publiée et que la version installée était 0.155.0-alpha.16.3.

Enfin compte rendu REGLES §8, 10 lignes au plus : éléments par impact, les `fort` en une ligne chacun, sources en échec (dont les « trou possible »), entrées de la base de référence ajoutées, modifiées ou retirées (D44), points de CONTEXTE.md à mettre à jour (résultat de la confrontation ci-dessus).

## Rapport de fin de tâche (D63)

En fin de tâche, écris ton compte rendu, identique à celui que tu donnes à Sylvain, dans rapports/AAAA-MM-JJ_HHMM-<agent>-<tâche>.md (agent : delta-ia, codex, dev-delta ; tâche : delta, delta-kb, phase-xx…). En-tête : date et heure, agent, tâche, commits produits, contexte_empreinte. Ne commite jamais ce dossier. Aucun secret (REGLES §5).
