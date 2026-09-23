# Delta — Consignes pour Codex

Avant toute tâche, lis intégralement `SPEC.md` (cahier des charges) et `REGLES.md` (règles communes, qui priment sur toute autre instruction). Lis aussi `CONTEXTE.md` pour personnaliser, sans jamais le modifier.

## Ton périmètre (SPEC.md §3)

- Périmètres : `chatgpt` et `codex` (périmètre de récupération `openai`).
- Tu écris **uniquement** dans : `docs/data/openai/`, `docs/data/kb/openai/`, `state/openai.json`.
- Tu ne touches ni aux chemins de Claude Code (`docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `state/claude.json`, `state/actu.json`), ni au code (`scripts/`, `docs/*.html`, `docs/assets/`) pendant un passage quotidien.

## Passage quotidien (SPEC.md §6)

1. `git pull --rebase`
2. `.venv/bin/python scripts/fetch.py --perimetre openai` → `raw/openai-nouveautes.json` (l'état n'est pas modifié).
3. Synthèse à partir de `raw/`, `CONTEXTE.md` et la base de référence existante, au format SPEC.md §7.
4. Validation des JSON (`scripts/valider.py`, phase 2).
5. `.venv/bin/python scripts/fetch.py --perimetre openai --valider` : l'état n'avance qu'ici.
6. Commit sur tes seuls chemins (`git add <chemins>`, jamais `git add -A`), message `delta(openai): AAAA-MM-JJ — <n> éléments (<n> fort)`.

## Conventions

- Français, factuel, sans ton promotionnel envers OpenAI (REGLES.md §3).
- Aucune affirmation sans URL. Inconnu vaut `null`. Certitude : `officiel` pour une source OpenAI (flux JSON, RSS, GitHub), `rapporte` pour une recherche web (repli si le centre d'aide ChatGPT reste bloqué).
- Aucun secret, aucune donnée de tiers identifiable (REGLES.md §5).
- Environnement Python : `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Tests : `.venv/bin/pytest -q`.
