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

## 2. Repli par recherche web pour ChatGPT

Le centre d'aide ChatGPT (`chatgpt-release-notes`) est bloqué (403). Fais toi-même une recherche web sur les notes de version ChatGPT publiées depuis la `borne` du brut (sources OpenAI d'abord : openai.com, help.openai.com ; médias ensuite). Pour chaque nouveauté trouvée : `certitude: rapporte`, URL obligatoire, et pour identifiant `web-<sha1(url + "|" + date_publication + "|" + titre normalisé)[:12]>` (D20 ; titre normalisé = minuscules, sans accents ni ponctuation ; date inconnue = chaîne vide), calculé par `.venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from deltalib.modeles import id_web; print(id_web('<url>', '<date ou vide>', '<titre>'))"`. L'URL seule ne suffit pas : toutes les entrées d'une même page de notes de version auraient le même identifiant. Avant de créer un tel élément, vérifie que l'identifiant n'est ni dans `state/openai.json` ni dans les fichiers `docs/data/openai/*.json` des 14 derniers jours. Une rumeur n'est jamais présentée comme un fait (`non_confirme`).

## 3. Synthèse dans `docs/data/openai/J.json` (SPEC §7.1 et §7.2, `agent: "codex"`)

- **Chaque nouveauté brute est comptabilisée** (D13) : soit dans les `ids_bruts` d'un élément, soit dans `ecartes: [{id, raison}]`. `ecartes` ne sert qu'à ce qui n'a aucun rapport avec l'usage des outils IA (marketing, offres sectorielles, événements). Ce qui concerne le produit mais pas Sylvain reste un élément avec `impact: nul` et `pour_toi: null` (D14).
- **Fusion des doublons** : un même événement rapporté par plusieurs sources (release GitHub + flux JSON + OpenAI News…) donne un seul élément, tous les identifiants bruts dans `ids_bruts`, toutes les URL dans `sources`. `id` = le premier de `ids_bruts`.
- `certitude: officiel` seulement si au moins une source a `officielle: true` (flux JSON, RSS ou GitHub sur un domaine OpenAI) ; `rapporte` pour la recherche web.
- `resume` factuel, 1 à 3 phrases, sans ton promotionnel envers OpenAI (REGLES §3) ; régressions, limites, hausses de prix, baisses de quota et retraits de modèles rapportés comme les nouveautés ; un changement défavorable vaut au moins `impact: moyen`.
- `pour_toi` et `action` s'appuient sur CONTEXTE.md : projet, outil ou habitude nommés, commande ou réglage exact. Priorités : trading-sim d'abord ; ce qui débloque Codex en CLI + tmux + remote control ; ce qui allège les limites hebdomadaires ; ce qui renforce les audits croisés Claude ↔ Codex. Ne fabrique jamais de pertinence.
- `projets_concernes` : uniquement des noms de CONTEXTE.md §2 (`carnet`, `trading-sim`, `chatgpt-trading-sim`, `ceramist`, `restoration-id`).
- `date_publication`, `version` : reprises du brut, `null` si inconnues, jamais devinées. `revision: true` si le brut le dit.
- `synthese` : 2 à 4 phrases sur ce qui compte aujourd'hui pour Sylvain ; s'il n'y a rien, une phrase le dit et `elements: []`.
- `sources_en_echec` : recopiées du brut.
- **Idempotence** : si `docs/data/openai/J.json` existe déjà, fusionne : conserve ses éléments, ajoute les nouveaux sans dupliquer un identifiant brut, mets à jour `synthese` et `genere_le`.

## 4. Index, base de référence, validation, état, commit

1. Mets à jour `docs/data/openai/index.json` (SPEC §7.3) : une entrée par fichier quotidien, triées par date décroissante, compteurs exacts.
2. Base de référence `docs/data/kb/openai/` : ne la modifie que si une nouveauté touche une entrée existante ; tant qu'elle n'existe pas (phase 4), ne crée rien.
3. `.venv/bin/python scripts/valider.py --perimetre openai --date $J --brut raw/openai-nouveautes.json`. Corrige jusqu'à ce qu'il rende 0. Ne commite pas s'il échoue.
4. `.venv/bin/python scripts/fetch.py --perimetre openai --valider --date $J`. Code 4 = des nouveautés brutes restent en attente : traite-les, revalide, relance. Code 0 attendu.
5. `git add docs/data/openai state/openai.json` (jamais `git add -A`), message `delta(openai): J — <n> éléments (<n> fort)`. Push seulement si un dépôt distant existe (D9).

## 5. Fin de passage

Relis les fichiers produits : aucun secret, aucune donnée de tiers identifiable (REGLES §5). Puis compte rendu REGLES §8, 10 lignes au plus : éléments par impact, les `fort` en une ligne chacun, sources en échec (dont les « trou possible »), entrées de la base de référence modifiées, points de CONTEXTE.md à mettre à jour.
