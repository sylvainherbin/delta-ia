---
name: verify
description: Contrôle avant tout commit de code du dépôt delta-ia (tests ciblés du diff, CI verte sur le hash exact pour fusionner ; suite complète en repli) ; ne fait rien pendant un passage ni pour un commit de données (docs/data, state, rapports).
---

# verify — contrôle avant commit de code

Claude lance cette skill juste avant un commit. Commence par le tri ci-dessous : dans le cas « hors champ », ne lance **rien** (ni pytest, ni valider.py, ni autre commande) et laisse le commit se faire.

## 1. Hors champ : rien à faire, commit autorisé tout de suite

- Un passage est en cours : `/delta`, `/delta-kb`, `$delta`, `$delta-kb`, ou la chaîne automatique (`scripts/passage-auto.sh`). Un passage commite des données avec une liste `allow` stricte ; pytest y serait refusé et allongerait la chaîne.
- Les chemins indexés (`git diff --cached --name-only`) sont tous dans `docs/data/`, `state/`, `rapports/` ou `PROGRESSION.md`, ou se réduisent à `CONTEXTE.md`.

## 2. Code : vérification ciblée locale

Dès qu'un chemin indexé est dans `scripts/`, `tests/`, `docs/*.html`, `docs/assets/`, `prompts/`, `.claude/`, `.agents/`, `.github/`, `deploy/`, `pytest.ini`, `sources.yaml`, `requirements.txt`, `SPEC.md`, `REGLES.md`, `CLAUDE.md` ou `AGENTS.md`, lance **le seul contrôle ciblé du diff** (CI-PREUVE, D94) :

```
.venv/bin/python scripts/verifier.py --cible            # diff contre origin/main
.venv/bin/python scripts/verifier.py --cible --liste    # montre la sélection sans rien lancer
```

`scripts/carte.py` calcule la carte fichiers → tests à chaque appel (imports de `scripts/` et `tests/`, aucun fichier à tenir à jour) : un test modifié se lance lui-même ; un module de `scripts/` lance ses tests directs et ceux de ses dépendants directs ; un module central (`scripts/deltalib/`) lance ses seuls tests directs et `scripts/valider.py` sur les trois périmètres ; un fichier hors graphe (prompt, page du site, skill, SPEC) lance les tests qui le citent ; un fichier inconnu lance les tests de même nom (ou l'outillage `test_verifier`, `test_carte`, `test_skill_verify`) et `valider.py` ; `tests/conftest.py`, `pytest.ini` et `requirements.txt` lancent l'outillage seul, la CI fait foi. **Le mode ciblé ne lance jamais la suite complète.** Il passe par le verrou machine commun (voir ci-dessous) et n'est jamais enregistré.

```
.venv/bin/python scripts/verifier.py tests/test_x.py   # tests choisis à la main (pytest seul)
.venv/bin/python scripts/verifier.py                    # suite complète = le repli du §3 (D87), ou « résultat réutilisé » en moins d'une seconde
.venv/bin/python scripts/verifier.py --sans-cache       # forcer une nouvelle exécution
```

La suite complète (`.venv/bin/pytest -q`, puis `scripts/valider.py --perimetre claude`, `openai` et `actu`) passe par `scripts/verifier.py` : verrou machine, et **aucun relancement sur un arbre déjà vérifié avec succès**. La clé du cache est le contenu réel du répertoire de travail (arbre git de `write-tree`, fichiers non suivis non ignorés compris) plus l'environnement (Python, paquets, `requirements.txt`) ; le registre est `~/.local/state/delta/verify-resultats.json`, hors du dépôt ; un échec n'est jamais enregistré.

**Verrou commun (VERROU-COMMUN, D94).** Toute suite lancée par `verifier.py` (complète, `--cible`, `--local`, tests choisis) se relance sous `verrou-tests --depot <racine> --nom delta-ia -- …` : une seule prise par exécution, dans la file FIFO commune à tous les dépôts (tickets sous `$XDG_STATE_HOME`, deux places, `nice 10`). Sous `VERIFY_VERROU_TENU` hérité, aucune seconde prise. **Code 75** : deux passages du même dépôt attendent déjà, `verifier.py` sort en 75 ; relancer plus tard, sans contourner le verrou. Le résultat réutilisé (suite complète sur un arbre déjà vérifié) n'attend aucun verrou. Toute autre suite locale, hors `verifier.py`, passe par le même lanceur ; pour le serveur MCP :

```
verrou-tests --depot mcp -- npm test    # depuis la racine du dépôt ; ou : verrou-tests --depot /home/herbin/projets/delta-ia/mcp -- npm test
```

La CI (D87, D94) n'est pas concernée : elle tourne sur GitHub, sans verrou.

Dans un worktree sans `.venv`, utilise celui du dépôt principal (`/home/herbin/projets/delta-ia/.venv/bin/python`) ; ne crée pas de venv.

Un test en échec ou un code de sortie non nul **interdit le commit** : corriger d'abord, ou s'arrêter et le signaler. Un seul échec connu est toléré : `test_raw_historique_est_ignore_par_git`, hors dépôt git, s'il est le seul et qu'on est hors du dépôt principal (worktree).

## 3. Fusion dans main : la CI GitHub est la preuve

Ordre (CI-PREUVE, D94) : ciblé local → push de la **branche** → CI verte sur le hash exact → contrôle machine éventuel → fusion en fast-forward.

1. `verifier.py --cible` (§2), puis commit et `git push origin operer/<nom>` : la CI (`.github/workflows/tests.yml`) fait la suite complète et `valider.py` sur le commit poussé.
2. `.venv/bin/python scripts/verifier.py --ci operer/<nom>` : code 0 seulement si un run **terminé `success`** a pour `headSha` le hash exact de la branche (pas le dernier run). Équivalent manuel : `gh run list --branch <branche> --json conclusion,headSha`.
3. `.venv/bin/python scripts/verifier.py --local` : ce que la CI ne peut pas faire, c'est-à-dire les tests marqués `local` (état réel de la machine, D87). Aucun test marqué : succès.
4. Si `origin/main` a avancé, rebase de la branche dessus **avant** la fusion, puis push sous un nouveau nom (`operer/<nom>-r2`, jamais `--force`) et nouvelle CI verte sur ce nouveau hash (l'étape 2 sur ce nom). Un rebase sans changement de contenu garde la preuve `verifier.py` du cache.
5. Sur `main`, enchaîné : `git fetch origin && git merge --ff-only operer/<nom> && git push origin main`. Le hash poussé est celui qui a la CI verte. **Pas de `git pull --rebase` entre la fusion et le push** : il recréerait des commits si `origin` a bougé et le hash fusionné ne serait plus celui de la CI (incident du 08/10, S2). Si le fast-forward ou le push est refusé parce que `main` a avancé : `git rebase --abort` si un rebase est en cours, puis retour à l'étape 4 (rebase de la branche, nouveau nom, nouvelle CI).

**Repli** : sans CI verte exploitable (`--ci` code 1 : aucun run, run en cours ou en échec, `gh` illisible, hash rebasé sans CI), la suite complète locale redevient exigée avant la fusion : `.venv/bin/python scripts/verifier.py`.

## 4. Fenêtre de la chaîne

De 03:30 à 08:00 (heure locale), aucun commit de développement, quel que soit le résultat des tests (CLAUDE.md, chaîne D70).
