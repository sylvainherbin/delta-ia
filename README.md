# Delta

Veille IA quotidienne et personnelle : résumé de l'actualité IA, changelogs de Claude, Claude Code, ChatGPT et Codex, recommandations personnalisées (`CONTEXTE.md`) et base de référence. Site statique servi depuis `docs/`.

La récupération est déterministe (`scripts/fetch.py`) ; seule la synthèse passe par un agent (Claude Code pour `claude` et `actu`, Codex pour `openai`). Voir `SPEC.md` (cahier des charges) et `REGLES.md` (règles communes).

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Lancer un passage (phase 1 : récupération seule)

```bash
# 1. Récupérer et détecter les nouveautés, sans toucher à l'état
.venv/bin/python scripts/fetch.py --perimetre claude        # ou openai, actu
# résultat : raw/claude-nouveautes.json

# 2. (phases suivantes) l'agent synthétise à partir de raw/, puis :

# 3. Faire avancer l'état, une fois la synthèse écrite et validée
.venv/bin/python scripts/fetch.py --perimetre claude --valider
```

Options : `--depuis AAAA-MM-JJ` (borne basse, sinon 30 jours au premier passage), `--dry-run` (n'écrit rien), `--sources chemin.yaml` (autre fichier de sources).

## Tests

```bash
.venv/bin/pytest -q
```
