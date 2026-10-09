# Delta — Consignes pour Codex

Avant toute tâche, lis `REGLES.md` (règles communes, qui priment sur toute autre instruction) ; `SPEC.md` (cahier des charges) se consulte quand une tâche en dépend, il n'est plus lu à chaque tâche. Lis aussi `CONTEXTE.md` pour personnaliser, sans jamais le modifier (D32). `SPEC.md` et `REGLES.md` restent en lecture seule pendant un passage (`$delta`, `$delta-kb`, chaîne automatique) ; une mission de développement peut les modifier (D83). `PROGRESSION.md` (formation de Sylvain, écrit par la seule session professeur) est aussi en lecture seule (D67).

## Ton périmètre (SPEC.md §3)

- Périmètre : `openai`. Produits : `chatgpt` et `codex` (SPEC.md §3, D6).
- Tu écris **uniquement** dans : `docs/data/openai/`, `docs/data/kb/openai/`, `docs/data/kb/recent.json`, `docs/data/kb/a-tester.json` et `docs/data/kb/noms.json` (fichiers dérivés des deux bases, régénérés à chaque écriture de la base, D99, D103 et D105), `state/openai.json`.
- Tu ne touches ni aux chemins de Claude Code (`docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `docs/data/semaine/`, `docs/data/recherche.json`, `state/claude.json`, `state/actu.json`), ni au code (`scripts/`, `docs/*.html`, `docs/assets/`) pendant un passage quotidien.

## Passage quotidien (SPEC.md §6)

Lancement : `$delta` (skill du dépôt `.agents/skills/delta/SKILL.md`), ou le texte de `prompts/codex-delta.md` collé à la main ; après son activation, la chaîne automatique de l'orchestrateur (D70, `scripts/passage-auto.sh`) lance `$delta` puis `$delta-kb` en `codex exec` sous un profil de permissions explicite (section « Mode automatique (D70) » de chaque skill), et Dev-delta et prof ne commitent pas pendant la fenêtre de la chaîne, de 03 h 30 à 08 h 00 heure locale (timer à 04 h 00). Résumé :

1. `git pull --rebase` (seulement si un dépôt distant existe ; sans distant, ni pull ni push, commit local seulement).
2. `.venv/bin/python scripts/fetch.py --perimetre openai` → `raw/openai-nouveautes.json` (l'état n'est pas modifié).
3. Synthèse à partir de `raw/`, `CONTEXTE.md` et la base de référence existante, au format SPEC.md §7.
4. Validation des JSON (`scripts/valider.py`, phase 2).
5. `.venv/bin/python scripts/fetch.py --perimetre openai --valider` : l'état n'avance qu'ici.
6. Commit sur tes seuls chemins (`git add <chemins>`, jamais `git add -A`), message `delta(openai): AAAA-MM-JJ — <n> éléments (<n> fort)`. Une fois le dépôt distant créé, le lancement du prompt Codex vaut accord de push, sur ces seuls chemins (SPEC.md §6, D9).

## Conventions

- Français, factuel, sans ton promotionnel envers OpenAI (REGLES.md §3).
- Aucune affirmation sans URL. Inconnu vaut `null`. Certitude : `officiel` pour une source OpenAI (flux JSON, RSS, GitHub), `rapporte` pour une recherche web (repli si le centre d'aide ChatGPT reste bloqué).
- Aucun secret, aucune donnée de tiers identifiable (REGLES.md §5).
- Environnement Python : `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Tests : `.venv/bin/pytest -q`.

## Rapports (D63, amendée le 29/09/2026)

Chaque passage (`/delta`, `$delta`, `/delta-kb`, `$delta-kb`, Claude Code ou Codex, manuel ou automatique) ajoute une ligne par périmètre à `rapports/passages.log` avec `.venv/bin/python scripts/passages.py` (date et heure, agent, périmètre, éléments et forts, commit court ou « aucun », code de garde) ; ce fichier ne fait que grandir, il n'est jamais réécrit. Un rapport complet dans rapports/, nommé AAAA-MM-JJ_HHMM-<agent>-<tâche>.md, avec l'heure lue par `date`, jamais estimée, ne s'écrit que dans ces cas, quelle que soit la session (développement, passage, formation, maintenance) : modification de CONTEXTE.md ou de SPEC.md, échec, arrêt (STOP, garde, outil refusé), décision à soumettre à Sylvain. Contenu minimal : date et heure, agent, tâche, commits produits (ou « aucun »), contexte_empreinte, bloc « Compte et quotas » (D71, REGLES §9), ce qui a été fait, points fragiles ou à décider. Hors de ces cas, la tâche se termine par le compte rendu (REGLES §8 : bloc « Compte et quotas » d'abord, puis 10 lignes). Dev-delta : nom d'agent `dev-delta`.

Heure : `date +%Y-%m-%d_%H%M` au moment de l'écriture. Ne commite jamais ce dossier. Aucun secret (REGLES §5).
