---
name: verify
description: Contrôle avant tout commit de code du dépôt delta-ia (pytest puis valider.py sur les trois périmètres) ; ne fait rien pendant un passage ni pour un commit de données (docs/data, state, rapports).
---

# verify — contrôle avant commit de code

Claude lance cette skill juste avant un commit. Commence par le tri ci-dessous : dans le cas « hors champ », ne lance **rien** (ni pytest, ni valider.py, ni autre commande) et laisse le commit se faire.

## 1. Hors champ : rien à faire, commit autorisé tout de suite

- Un passage est en cours : `/delta`, `/delta-kb`, `$delta`, `$delta-kb`, ou la chaîne automatique (`scripts/passage-auto.sh`). Un passage commite des données avec une liste `allow` stricte ; pytest y serait refusé et allongerait la chaîne.
- Les chemins indexés (`git diff --cached --name-only`) sont tous dans `docs/data/`, `state/`, `rapports/` ou `PROGRESSION.md`, ou se réduisent à `CONTEXTE.md`.

## 2. Code : contrôle obligatoire

Dès qu'un chemin indexé est dans `scripts/`, `tests/`, `docs/*.html`, `docs/assets/`, `prompts/`, `.claude/`, `.agents/`, `deploy/`, `sources.yaml`, `requirements.txt`, `SPEC.md`, `REGLES.md`, `CLAUDE.md` ou `AGENTS.md`, lance dans l'ordre :

```
.venv/bin/pytest -q
.venv/bin/python scripts/valider.py --perimetre claude
.venv/bin/python scripts/valider.py --perimetre openai
.venv/bin/python scripts/valider.py --perimetre actu
```

Dans un worktree sans `.venv`, utilise celui du dépôt principal (`../delta-ia/.venv/bin/...`) ; ne crée pas de venv.

Un test en échec ou un code de sortie non nul **interdit le commit** : corriger d'abord, ou s'arrêter et le signaler. Un seul échec connu est toléré : `test_raw_historique_est_ignore_par_git`, hors dépôt git, s'il est le seul et qu'on est hors du dépôt principal (worktree).

## 3. Fenêtre de la chaîne

De 03:30 à 08:00 (heure locale), aucun commit de développement, quel que soit le résultat des tests (CLAUDE.md, chaîne D70).
