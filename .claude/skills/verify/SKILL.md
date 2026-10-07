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

Les quatre commandes passent par `scripts/verifier.py` (D87), qui les lance dans cet ordre sous le verrou machine (deux places, `nice 10`) et **ne relance rien sur un arbre déjà vérifié avec succès** :

```
.venv/bin/python scripts/verifier.py            # suite complète, ou « résultat réutilisé » en moins d'une seconde
.venv/bin/python scripts/verifier.py --sans-cache   # forcer une nouvelle exécution
.venv/bin/python scripts/verifier.py tests/test_x.py   # tests ciblés (pytest seul, jamais enregistré)
```

La clé du cache est `HEAD^{tree}` plus le contenu non commité (fichiers suivis modifiés, fichiers non suivis non ignorés) plus l'environnement (Python, paquets installés, `requirements.txt`) ; un rebase sans changement de contenu garde donc le résultat. Le registre est `~/.local/state/delta/verify-resultats.json`, hors du dépôt. Un échec n'est jamais enregistré.

Quand la CI GitHub Actions est verte sur le commit à contrôler (`gh run list --branch <branche> --json conclusion,headSha`, conclusion `success` **et** `headSha` égal au commit), le verify local se limite aux tests ciblés (fichiers touchés).

Dans un worktree sans `.venv`, utilise celui du dépôt principal (`../delta-ia/.venv/bin/...`) ; ne crée pas de venv.

Un test en échec ou un code de sortie non nul **interdit le commit** : corriger d'abord, ou s'arrêter et le signaler. Un seul échec connu est toléré : `test_raw_historique_est_ignore_par_git`, hors dépôt git, s'il est le seul et qu'on est hors du dépôt principal (worktree).

## 3. Fusion dans main

La fusion lit le statut de la CI au lieu de relancer la suite : `gh run list --branch <branche> --json conclusion,headSha`, puis fusion seulement si une ligne a `conclusion` égal à `success` et `headSha` égal au commit fusionné (pas seulement le dernier run). Sans run vert sur ce commit exact, ou si l'arbre fusionné diffère du commit testé (rebase avec changement de contenu), `scripts/verifier.py` reste la preuve : il réutilise un résultat pour un arbre identique et relance sinon.

## 4. Fenêtre de la chaîne

De 03:30 à 08:00 (heure locale), aucun commit de développement, quel que soit le résultat des tests (CLAUDE.md, chaîne D70).
