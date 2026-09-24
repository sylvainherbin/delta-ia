# Delta — Consignes pour Codex

Avant toute tâche, lis intégralement `SPEC.md` (cahier des charges) et `REGLES.md` (règles communes, qui priment sur toute autre instruction). Lis aussi `CONTEXTE.md` pour personnaliser, sans jamais le modifier. `PROGRESSION.md` (formation de Sylvain, écrit par la seule session professeur) est aussi en lecture seule (D67).

## Ton périmètre (SPEC.md §3)

- Périmètre : `openai`. Produits : `chatgpt` et `codex` (SPEC.md §3, D6).
- Tu écris **uniquement** dans : `docs/data/openai/`, `docs/data/kb/openai/`, `state/openai.json`.
- Tu ne touches ni aux chemins de Claude Code (`docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `state/claude.json`, `state/actu.json`), ni au code (`scripts/`, `docs/*.html`, `docs/assets/`) pendant un passage quotidien.

## Passage quotidien (SPEC.md §6)

Lancement : `$delta` (skill du dépôt `.agents/skills/delta/SKILL.md`), ou le texte de `prompts/codex-delta.md` collé à la main. Résumé :

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

## Rapport de fin de tâche (D63)

En fin de tâche, écris ton compte rendu, identique à celui que tu donnes à Sylvain, dans rapports/AAAA-MM-JJ_HHMM-<agent>-<tâche>.md, dont la date et l'heure se prennent avec `date +%Y-%m-%d_%H%M` au moment de l'écriture, jamais estimées (agent : delta-ia, codex, dev-delta ; tâche : delta, delta-kb, phase-xx…). En-tête : date et heure, agent, tâche, commits produits, contexte_empreinte. Ne commite jamais ce dossier. Aucun secret (REGLES §5).
