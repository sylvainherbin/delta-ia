---
name: delta-kb
description: Commente par lots (deux au plus par lancement) la base de référence Delta du périmètre openai, docs/data/kb/openai/. À invoquer explicitement avec $delta-kb ; ne pas déclencher implicitement.
---

# delta-kb — commentaire de la base de référence (Codex, périmètre `openai`)

Tu commentes par lots la base de référence `docs/data/kb/openai/` (produits `chatgpt` et `codex`), générée une seule fois puis maintenue par les passages quotidiens (D44). Lis d'abord `SPEC.md` §7.4, `REGLES.md` (qui prime) et `CONTEXTE.md` en entier. Tu n'écris que dans `docs/data/kb/openai/` et dans `raw/kb/`.

## 0. Préparation

- Si `.git/index.lock` existe, arrête-toi et signale-le. Ne lance jamais delta-kb pendant un passage quotidien (`$delta` pour Codex, `/delta` pour Claude Code) (D21).
- `git pull --rebase` ; en cas de conflit, arrête-toi et signale.
- Python : `.venv/bin/python`.

## 1. Réévaluations prioritaires, avant les lots

1. **Recalibrage ponctuel (D57).** Si `git log --oneline --grep 'recalibrage commandes'` ne renvoie rien, commence par réévaluer selon D57 **toutes** les entrées dont le verdict est `utiliser` (il y en avait 26 le 23/09) : `.venv/bin/python -c "import json,glob; print(json.dumps([e for f in glob.glob('docs/data/kb/openai/*.json') for e in json.load(open(f))['entrees'] if e.get('commentee') and e['recommandation']['verdict']=='utiliser'], ensure_ascii=False, indent=1))"`. Applique les corrections avec `scripts/catalogue.py appliquer`, valide avec `valider.py --kb`, puis commite à part : `delta-kb(openai): recalibrage commandes`, et pousse. Cette étape n'a lieu qu'une fois.
2. **Commentaires périmés (D60).** `.venv/bin/python scripts/catalogue.py a-commenter --perimetre openai --lot perimees` donne au plus 30 entrées `utiliser` ou `tester` commentées avec un autre CONTEXTE.md que l'actuel. Réévalue-les selon les règles ci-dessous (le verdict peut baisser ou monter), applique, valide, puis commite à part : `delta-kb(openai): réévaluation contexte — <n> entrées`. Ces réévaluations s'ajoutent aux deux lots, elles n'en prennent pas la place.

## 2. Lots du jour : deux au plus (D46)

1. `.venv/bin/python scripts/catalogue.py lots --perimetre openai` liste les lots par valeur décroissante (D51) : commandes, fonctionnalités, `skills+plugins+mcp` (regroupés), raccourcis, puis paramètres. Une grande catégorie est coupée en deux (`commandes:1`, `commandes:2`), les paramètres en quarts (`parametres:1` à `parametres:4`) (D50).
2. Prends les **deux premiers lots** qui ont encore des entrées à commenter. Pas un de plus, même s'il reste du temps : la génération s'étale sur plusieurs jours.

## 3. Pour chaque lot

1. `.venv/bin/python scripts/catalogue.py a-commenter --perimetre openai --lot <lot> > raw/kb/a-commenter-<lot>.json`.
2. Commente par tranches de 25 à 40 entrées : écris `raw/kb/commentaires-<lot>-<n>.json`, puis applique-le avec `scripts/catalogue.py appliquer --perimetre openai --fichier …`. Une tranche appliquée n'est jamais perdue si la suite échoue.
3. `.venv/bin/python scripts/valider.py --perimetre openai --kb` doit rendre 0. Corrige tes commentaires (jamais `usage`) jusqu'à ce qu'il passe.
4. Relis ce que tu as écrit : aucun secret, aucune donnée de tiers identifiable (REGLES §5).
5. `git add docs/data/kb/openai` (jamais `git add -A`), message `delta-kb(openai): lot <lot> — <n> entrées commentées`, puis `git push`.

## Règles de commentaire (D40, D41, D26, SPEC §7.4)

Tu commentes des entrées déjà extraites de la documentation officielle par `scripts/catalogue.py` (`commentee: false`). Pour chacune, tu produis **uniquement** `description`, `statut_usage`, `recommandation`, et le cas échéant `exemple` et `disponibilite`. Tu ne touches jamais à `usage`, `nom`, `id`, `sources`, `description_source` : ce sont des copies de la documentation. Si `usage` te paraît faux ou incomplet, tu le signales dans le compte rendu, sans le corriger.

- **Lis la source, sobrement.** `description_source` et `usage` d'abord ; pour une entrée du gabarit complet, lis aussi la page en cache dans `raw/kb/<produit>/<origine>/` (le nom du fichier suit l'URL de `sources[0]`), mais au plus ses 120 premières lignes, ou seulement la section de l'entrée (`groupe`, ancre de l'URL) avec `grep -n` puis `sed -n`. Ne lis jamais une page entière de plus de 120 lignes : c'est le poste de coût principal.
- **Gabarit complet** (fonctionnalités, commandes, skills, plugins, MCP) : `description` en 2 ou 3 phrases, en français, précise et utilisable ; `exemple` recopié tel quel depuis la page de documentation (commande, bloc de configuration, étapes), jamais inventé, ou `null` si la page n'en donne pas d'autre que `usage` ; `recommandation.pourquoi` en 1 ou 2 phrases.
- **Nature de l'usage** (D49) : `usage_nature` vaut `syntaxe` (commande, clé, bloc de code) ou `etapes` (chemin d'accès ou étapes d'une page narrative) ; elle est fixée par l'extraction, tu ne la changes pas.
- **Gabarit court** (paramètres, variables d'environnement, options CLI, clés `config.toml`, raccourcis) : `description` en 1 phrase, `recommandation.pourquoi` en 1 phrase, `exemple: null`.
- **`statut_usage`** d'après CONTEXTE.md : `utilise` si l'usage est observé ou déclaré (réglage présent, commande tapée, outil cité), `non_utilise` si CONTEXTE dit explicitement que Sylvain ne s'en sert pas, sinon `inconnu`. Ne déduis jamais un usage.
- **`recommandation.verdict`** : `utiliser`, `tester` ou `ignorer`. `utiliser` et `tester` exigent un `pourquoi` qui nomme un projet (trading-sim d'abord, puis carnet, chatgpt-trading-sim, les sites), une session (herbin-mint, herbin-dev, herbin-trading, delta-ia…) ou une habitude de CONTEXTE.md (pilotage depuis l'iPhone, Remote Control, sessions tmux systemd, audits croisés Claude ↔ Codex, limites hebdomadaires, Wi-Fi fragile, machine lente) et ce que ça change concrètement (D26). Sans lien réel, le verdict est `ignorer` et le `pourquoi` le dit en une phrase ; ne fabrique jamais de pertinence.
- **Calibrage du verdict (D57)** : `utiliser` exige soit un usage actuel de Sylvain d'après CONTEXTE.md (pour Codex, c'est surtout l'app de bureau), soit un lien direct avec un objectif déclaré : Codex en CLI + tmux + remote control, économie des limites d'usage, audits croisés Claude ↔ Codex. Un rattachement générique (« avant un audit trading-sim », « utile sur tes projets ») donne au plus `tester`. Contre-exemples côté openai, trop hauts en `utiliser` : `/mention`, `/rename`, `/ps`, `/local`, `/skills`, `codex://skills`, `codex plugin list`.
- **Constats et déductions (D59)** : le `pourquoi` n'affirme sur la machine, les sessions ou les projets de Sylvain que ce que CONTEXTE.md dit explicitement ; une déduction se formule au conditionnel, jamais comme un constat. Relis dans CONTEXTE.md chaque nombre que tu en tires (sessions, versions, compteurs, pourcentages).
- **Empreinte du contexte (D60)** : `scripts/catalogue.py appliquer` inscrit sur chaque entrée commentée l'empreinte de CONTEXTE.md du moment (`contexte_empreinte`) ; tu ne la fournis pas. La page Référence signale les commentaires antérieurs au CONTEXTE actuel.
- **Effets de bord** : quand `description_source` mentionne un effet de bord (réglage enregistré par défaut pour toutes les sessions ou pour les nouvelles sessions, persistance dans un fichier, action irréversible), le `pourquoi` le signale et donne la variante sans effet de bord si la documentation en décrit une. Exemple : `/model` enregistre le modèle comme défaut des nouvelles sessions ; `s` dans le sélecteur ne change que la session courante.
- **Style** (REGLES §7) : français, factuel, sans superlatif ; noms de commandes, d'options et de produits en version originale ; comparaisons chiffrées avec leur référence (D28).
- **`disponibilite`** : plan ou plateforme seulement si la page le dit (par exemple « Max et Team », « Linux, iOS, web »), sinon laisse `null`.
- **Écriture** : un fichier JSON `{id: {description, statut_usage, recommandation: {verdict, pourquoi}, exemple, disponibilite}}`, appliqué par `.venv/bin/python scripts/catalogue.py appliquer --perimetre P --fichier <fichier>`. Le script refuse tout autre champ et rien n'est écrit en cas d'erreur.

## 4. Compte rendu (10 lignes au plus)

Réévaluations faites (recalibrage, entrées périmées) ; lots traités ; entrées commentées par verdict (`utiliser`, `tester`, `ignorer`) et par `statut_usage` ; les `utiliser` en une ligne chacun ; les entrées dont `usage` paraît faux ou incomplet ; les lots restants et l'avancement `n/N` (`catalogue.py inventaire --perimetre openai`).
