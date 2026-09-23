---
name: delta
description: Passage quotidien de la veille Delta pour Claude Code — périmètres claude puis actu, selon SPEC.md §6. À lancer à la main, une fois par jour.
disable-model-invocation: true
---

# /delta — passage quotidien (Claude Code)

Tu exécutes le passage quotidien de Delta pour les périmètres `claude` puis `actu`, dans cet ordre. SPEC.md et REGLES.md sont déjà chargés par CLAUDE.md ; relis CONTEXTE.md en entier avant de synthétiser. REGLES.md prime sur tout le reste. Tu n'écris que dans `docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `state/claude.json`, `state/actu.json`. Aucun code n'est modifié pendant un passage.

## 0. Préparation

- Si `git remote -v` est vide : ni pull ni push (SPEC §6, D9). Sinon `git pull --rebase` ; en cas de conflit, arrête-toi et signale.
- Si `.git/index.lock` existe, arrête-toi et signale-le : un autre passage (Codex) ou une autre session tient le dépôt ; les passages ne tournent jamais en même temps (D21).
- Calcule la date du passage **une seule fois** : `J=$(date +%F)`. Toutes les commandes et tous les fichiers du passage utilisent ce `J`, même si le passage franchit minuit (D19). Python : `.venv/bin/python`.

## 1. Pour chaque périmètre `p` dans `claude`, `actu`

1. **Récupération.** Si `state/p.json` est absent ou si sa clé `vus` est vide, c'est le premier passage réel : `.venv/bin/python scripts/fetch.py --perimetre p --depuis $(date -d '-7 days' +%F)` (D10). Sinon : `.venv/bin/python scripts/fetch.py --perimetre p`. Le fichier `raw/p-nouveautes.json` contient `nouveautes`, `ignores`, `sources_en_echec`, `borne`. L'état n'est pas modifié.
2. **Lecture.** `raw/p-nouveautes.json`, CONTEXTE.md, et la base de référence `docs/data/kb/claude/*.json` si elle existe.
3. **Synthèse** dans `docs/data/p/J.json`, au format SPEC §7.1 et §7.2 (`agent: "claude-code"`). Règles :
   - **Chaque nouveauté brute est comptabilisée** (D13) : soit dans les `ids_bruts` d'un élément, soit dans `ecartes: [{id, raison}]`. `ecartes` ne sert qu'à ce qui n'a aucun rapport avec l'usage des outils IA (marketing, offres sectorielles, événements). Ce qui concerne le produit mais pas Sylvain reste un élément avec `impact: nul` et `pour_toi: null` (D14).
   - **Fusion des doublons** : un même événement rapporté par plusieurs sources (changelog + newsroom + notes de la plateforme…) donne un seul élément, tous les identifiants bruts dans `ids_bruts`, toutes les URL dans `sources`. `id` = le premier de `ids_bruts`.
   - `certitude: officiel` si au moins une source a `officielle: true` (le champ vient du brut). Un élément de recherche web a `certitude: rapporte` et pour identifiant `web-<sha1(url + "|" + date_publication + "|" + titre normalisé)[:12]>` (D20 ; titre normalisé = minuscules, sans accents ni ponctuation ; date inconnue = chaîne vide), calculé par `.venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from deltalib.modeles import id_web; print(id_web('<url>', '<date ou vide>', '<titre>'))"`. Il n'est créé qu'après avoir vérifié que cet identifiant n'est ni dans `state/p.json` ni dans les fichiers `docs/data/p/*.json` des 14 derniers jours.
   - **Tri (D24)** : `ecartes` reçoit tout ce qui ne touche ni les modèles, ni les outils et agents IA, ni les conditions de leur usage (prix, quotas, sécurité des agents, disponibilité). Robots industriels, procès, politique générale, faits divers, partenariats et applications sectorielles sont écartés, pas classés `nul`. Le 23/09, 19 des 23 éléments `actu` étaient en `nul` : c'était trop.
   - **Événement déjà couvert (D31)** : une nouveauté qui décrit un événement déjà traité dans les fichiers `docs/data/p/*.json` des 14 derniers jours, même sous un autre identifiant (une entrée `web-*` du 23/09 reprise ensuite par `releasebot-*`, une même annonce vue par la newsroom puis par les notes de version), va dans `ecartes` avec la raison « déjà couvert le <date> (<id>) ». Relis ces fichiers avant de créer un élément.
   - **URL (D25)** : chaque URL de `sources` est copiée depuis la page effectivement consultée, jamais reconstruite ni devinée.
   - **Pertinence (D26)** : un projet n'entre dans `projets_concernes`, et un élément ne vaut `moyen` ou plus, que si la nouveauté change quelque chose de concret sur ce projet : une commande, un réglage, un flux de travail. Contre-exemple du 23/09 : le « Centre de confidentialité » de ChatGPT classé `moyen` et rattaché à trading-sim, alors qu'il ne change rien à la façon de travailler dessus.
   - **Chiffres (D28)** : une comparaison garde sa référence : « 40 % moins cher qu'Opus 5 », jamais « 40 % moins cher » seul.
   - `resume` factuel, 1 à 3 phrases ; régressions, limites, hausses de prix et baisses de quota rapportées comme les nouveautés (REGLES §3) ; un changement défavorable vaut au moins `impact: moyen`.
   - `pour_toi` et `action` s'appuient sur CONTEXTE.md : projet, outil ou habitude nommés, commande ou réglage exact. Priorités : trading-sim d'abord ; ce qui débloque Codex en CLI + tmux + remote control ; ce qui allège les limites hebdomadaires ; ce qui renforce les audits croisés Claude ↔ Codex. Ne fabrique jamais de pertinence.
   - `projets_concernes` : uniquement des noms de CONTEXTE.md §2 (`carnet`, `trading-sim`, `chatgpt-trading-sim`, `ceramist`, `restoration-id`).
   - `date_publication`, `version` : reprises du brut, `null` si inconnues, jamais devinées. `revision: true` si le brut le dit.
   - `synthese` : 2 à 4 phrases sur ce qui compte aujourd'hui pour Sylvain ; s'il n'y a rien, une phrase le dit et `elements: []`.
   - `sources_en_echec` : recopiées du brut.
   - **Idempotence** : si `docs/data/p/J.json` existe déjà, fusionne : conserve ses éléments, ajoute les nouveaux sans dupliquer un identifiant brut, mets à jour `synthese` et `genere_le`.
4. **Index.** Mets à jour `docs/data/p/index.json` (SPEC §7.3) : une entrée par fichier quotidien, triées par date décroissante, compteurs exacts.
5. **Base de référence (D44), périmètre `claude` seulement.** `.venv/bin/python scripts/fetch.py --kb claude-code claude` relit les pages de référence (empreinte par page), ré-extrait et met à jour `docs/data/kb/claude/` ; il écrit `raw/kb/claude-modifications.json` (`ajoutees`, `usage_modifie`, `retirees`, `echecs`). Commente les entrées de `ajoutees` et `usage_modifie` selon les règles de la skill `/delta-kb` (`.claude/skills/delta-kb/SKILL.md`, section « Règles de commentaire ») et applique-les avec `scripts/catalogue.py appliquer`. Les entrées `retirees` et un `usage` modifié défavorablement sont des éléments du jour (`type: depreciation` ou `changement_rupture`). Renseigne `kb_refs` des éléments du jour qui touchent une entrée de la base. Le stock d'entrées jamais commentées relève de `/delta-kb`, pas du passage quotidien. Puis `.venv/bin/python scripts/valider.py --perimetre claude --kb` doit rendre 0.
6. **Validation.** `.venv/bin/python scripts/valider.py --perimetre p --date $J --brut raw/p-nouveautes.json`. Corrige jusqu'à ce qu'il rende 0. Ne commite pas s'il échoue.
7. **Avancement de l'état.** `.venv/bin/python scripts/fetch.py --perimetre p --valider --date $J`. Code 4 = des nouveautés brutes restent en attente : traite-les (élément ou écarté), revalide, relance. Code 0 attendu.
8. **Commit** sur les seuls chemins du périmètre : `git add docs/data/p state/p.json` (plus `docs/data/kb/claude` pour le périmètre `claude`), message `delta(p): J — <n> éléments (<n> fort)`. Push seulement si un dépôt distant existe (D9).

## 2. Fin de passage

Relis les fichiers produits : aucun secret, aucune donnée de tiers identifiable (REGLES §5). Puis **confrontation à CONTEXTE.md (D29)** : pour chaque élément `fort` ou `moyen`, compare explicitement ce qu'il annonce (modèle, version, profil, outil, réglage) à ce que CONTEXTE.md décrit de l'usage de Sylvain, et note chaque écart : version installée dépassée, modèle par défaut remplacé, profil pointant sur un modèle retiré, outil abandonné. Contre-exemple du 23/09 : GPT-6 Sol remplaçait GPT-5.6 Sol, décrit dans CONTEXTE comme le modèle principal de Sylvain, et l'écart n'a pas été signalé. « Aucun point » n'est permis qu'après cette vérification, élément par élément.

Enfin compte rendu REGLES §8, 10 lignes au plus : éléments par impact, les `fort` en une ligne chacun, sources en échec (dont les « trou possible »), entrées de la base de référence ajoutées, modifiées ou retirées (D44), points de CONTEXTE.md à mettre à jour (résultat de la confrontation ci-dessus).
