---
name: delta-kb
description: Commente par lots (deux au plus par lancement) la base de référence Delta du périmètre claude, docs/data/kb/claude/. À lancer à la main, jamais pendant un passage quotidien.
disable-model-invocation: true
model: opus
---

# delta-kb — commentaire de la base de référence (Claude Code, périmètre `claude`)

Tu commentes par lots la base de référence `docs/data/kb/claude/` (produits `claude` et `claude-code`), générée une seule fois puis maintenue par les passages quotidiens (D44). Lis d'abord `SPEC.md` §7.4, `REGLES.md` (qui prime) et `CONTEXTE.md` en entier. Tu n'écris que dans `docs/data/kb/claude/` et dans `raw/kb/`.

## 0. Préparation

- Si `.git/index.lock` existe, arrête-toi et signale-le. Ne lance jamais delta-kb pendant un passage quotidien (`/delta` pour Claude Code, `$delta` pour Codex) (D21).
- `git pull --rebase` ; en cas de conflit, arrête-toi et signale.
- Python : `.venv/bin/python`. Modèle recommandé : Opus 5.5 (fixé par cette skill), pour épargner la limite Fable.

## 1. Lots du jour : deux au plus (D46)

1. `.venv/bin/python scripts/catalogue.py lots --perimetre claude` liste les lots par valeur décroissante (D51) : commandes, fonctionnalités, skills, plugins et MCP, raccourcis, puis paramètres. Une grande catégorie est coupée en deux (`commandes:1`, `commandes:2`), les paramètres en quarts (`parametres:1` à `parametres:4`) (D50).
2. Prends les **deux premiers lots** qui ont encore des entrées à commenter. Pas un de plus, même s'il reste du temps : la génération s'étale sur plusieurs jours.

## 2. Pour chaque lot

1. `.venv/bin/python scripts/catalogue.py a-commenter --perimetre claude --lot <lot> > raw/kb/a-commenter-<lot>.json`.
2. Commente par tranches de 25 à 40 entrées : écris `raw/kb/commentaires-<lot>-<n>.json`, puis applique-le avec `scripts/catalogue.py appliquer --perimetre claude --fichier …`. Une tranche appliquée n'est jamais perdue si la suite échoue.
3. `.venv/bin/python scripts/valider.py --perimetre claude --kb` doit rendre 0. Corrige tes commentaires (jamais `usage`) jusqu'à ce qu'il passe.
4. Relis ce que tu as écrit : aucun secret, aucune donnée de tiers identifiable (REGLES §5).
5. `git add docs/data/kb/claude` (jamais `git add -A`), message `delta-kb(claude): lot <lot> — <n> entrées commentées`, puis `git push`.

## Règles de commentaire (D40, D41, D26, SPEC §7.4)

Tu commentes des entrées déjà extraites de la documentation officielle par `scripts/catalogue.py` (`commentee: false`). Pour chacune, tu produis **uniquement** `description`, `statut_usage`, `recommandation`, et le cas échéant `exemple` et `disponibilite`. Tu ne touches jamais à `usage`, `nom`, `id`, `sources`, `description_source` : ce sont des copies de la documentation. Si `usage` te paraît faux ou incomplet, tu le signales dans le compte rendu, sans le corriger.

- **Lis la source, sobrement.** `description_source` et `usage` d'abord ; pour une entrée du gabarit complet, lis aussi la page en cache dans `raw/kb/<produit>/<origine>/` (le nom du fichier suit l'URL de `sources[0]`), mais au plus ses 120 premières lignes, ou seulement la section de l'entrée (`groupe`, ancre de l'URL) avec `grep -n` puis `sed -n`. Ne lis jamais une page entière de plus de 120 lignes : c'est le poste de coût principal.
- **Gabarit complet** (fonctionnalités, commandes, skills, plugins, MCP) : `description` en 2 ou 3 phrases, en français, précise et utilisable ; `exemple` recopié tel quel depuis la page de documentation (commande, bloc de configuration, étapes), jamais inventé, ou `null` si la page n'en donne pas d'autre que `usage` ; `recommandation.pourquoi` en 1 ou 2 phrases.
- **Nature de l'usage** (D49) : `usage_nature` vaut `syntaxe` (commande, clé, bloc de code) ou `etapes` (chemin d'accès ou étapes d'une page narrative) ; elle est fixée par l'extraction, tu ne la changes pas.
- **Gabarit court** (paramètres, variables d'environnement, options CLI, clés `config.toml`, raccourcis) : `description` en 1 phrase, `recommandation.pourquoi` en 1 phrase, `exemple: null`.
- **`statut_usage`** d'après CONTEXTE.md : `utilise` si l'usage est observé ou déclaré (réglage présent, commande tapée, outil cité), `non_utilise` si CONTEXTE dit explicitement que Sylvain ne s'en sert pas, sinon `inconnu`. Ne déduis jamais un usage.
- **`recommandation.verdict`** : `utiliser`, `tester` ou `ignorer`. `utiliser` et `tester` exigent un `pourquoi` qui nomme un projet (trading-sim d'abord, puis carnet, chatgpt-trading-sim, les sites), une session (herbin-mint, herbin-dev, herbin-trading, delta-ia…) ou une habitude de CONTEXTE.md (pilotage depuis l'iPhone, Remote Control, sessions tmux systemd, audits croisés Claude ↔ Codex, limites hebdomadaires, Wi-Fi fragile, machine lente) et ce que ça change concrètement (D26). Sans lien réel, le verdict est `ignorer` et le `pourquoi` le dit en une phrase ; ne fabrique jamais de pertinence.
- **Effets de bord** : quand `description_source` mentionne un effet de bord (réglage enregistré par défaut pour toutes les sessions ou pour les nouvelles sessions, persistance dans un fichier, action irréversible), le `pourquoi` le signale et donne la variante sans effet de bord si la documentation en décrit une. Exemple : `/model` enregistre le modèle comme défaut des nouvelles sessions ; `s` dans le sélecteur ne change que la session courante.
- **Style** (REGLES §7) : français, factuel, sans superlatif ; noms de commandes, d'options et de produits en version originale ; comparaisons chiffrées avec leur référence (D28).
- **`disponibilite`** : plan ou plateforme seulement si la page le dit (par exemple « Max et Team », « Linux, iOS, web »), sinon laisse `null`.
- **Écriture** : un fichier JSON `{id: {description, statut_usage, recommandation: {verdict, pourquoi}, exemple, disponibilite}}`, appliqué par `.venv/bin/python scripts/catalogue.py appliquer --perimetre P --fichier <fichier>`. Le script refuse tout autre champ et rien n'est écrit en cas d'erreur.

## 3. Compte rendu (10 lignes au plus)

Lots traités ; entrées commentées par verdict (`utiliser`, `tester`, `ignorer`) et par `statut_usage` ; les `utiliser` en une ligne chacun ; les entrées dont `usage` paraît faux ou incomplet ; les lots restants et l'avancement `n/N` (`catalogue.py inventaire --perimetre claude`).
