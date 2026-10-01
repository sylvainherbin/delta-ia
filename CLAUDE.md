@REGLES.md

SPEC.md (cahier des charges) se consulte quand une tâche en dépend ; il n'est plus chargé à chaque tour.

# Conventions du dépôt Delta

- Français, tutoiement. Noms de commandes, d'options et de produits en version originale.
- Périmètres de Claude Code : `claude`, `claude-code`, `actu`. Écriture uniquement dans `docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `docs/data/versions.json`, `docs/data/etat.json`, `state/claude.json`, `state/actu.json` (SPEC.md §3).
- `CONTEXTE.md`, `SPEC.md`, `REGLES.md`, `PROGRESSION.md` : lecture seule. Signaler, ne pas corriger. `PROGRESSION.md` est écrit et commité par la seule session professeur, ce fichier seul (D67) ; `CONTEXTE.md` reste sous D32.
- Python 3.12, environnement `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Pas de `pip` système.
- Tests : `.venv/bin/pytest -q`. Analyseurs testés sur des échantillons réels dans `tests/fixtures/`.
- `scripts/fetch.py` n'écrit jamais dans `state/` sans `--valider`. `raw/` est ignoré par git.
- Une source en échec ou au format inattendu va dans `sources_en_echec` ; jamais de résultat vide silencieux.
- Sources déclarées dans `sources.yaml` uniquement, chaque URL testée avant inscription. Statuts : `ok`, `bloque`, `a_valider`, `desactive` (une source écartée est désactivée, pas supprimée).
- Aucune date, version ou fonctionnalité devinée : inconnu vaut `null`.
- Git (SPEC §6, D9) : `git add <chemins>` explicites, jamais `git add -A`, jamais `--force`. Sans dépôt distant : ni pull ni push. Avec un distant : lancer `/delta` vaut accord de push sur les seuls chemins de l'agent ; en session de développement, push après l'OK du chef Delta-IA (autorisation permanente de Sylvain du 02/10/2026), un seul push, après les tests et `valider.py`.
- Le code (`scripts/`, `docs/*.html`, `docs/assets/`) ne change qu'en session de développement, jamais pendant un passage quotidien.
- Passage quotidien : `/delta` (skill `.claude/skills/delta/SKILL.md`), lancé à la demande de Sylvain ou automatiquement par la tâche planifiée de Claude Desktop selon D68 (section « Mode automatique (D68) » de la skill). Le pilotage du projet est délégué à la session Delta-IA : ses décisions numérotées s'appliquent sans plan préalable. Chaîne automatique (D70, après son activation) : `scripts/passage-auto.sh` enchaîne `/delta`, `$delta`, `/delta-kb`, `$delta-kb` et une supervision ; Dev-delta et prof ne commitent pas pendant la fenêtre de la chaîne, de 03 h 30 à 08 h 00 heure locale (timer à 04 h 00, décision de Sylvain du 01/10/2026 ; un `.git/delta-passage.lock` tenu signale la chaîne en cours, la garde s'arrête alors au code 14).

## Rapports (D63, amendée le 29/09/2026)

Chaque passage (`/delta`, `$delta`, `/delta-kb`, `$delta-kb`, Claude Code ou Codex, manuel ou automatique) ajoute une ligne par périmètre à `rapports/passages.log` avec `.venv/bin/python scripts/passages.py` (date et heure, agent, périmètre, éléments et forts, commit court ou « aucun », code de garde) ; ce fichier ne fait que grandir, il n'est jamais réécrit. Un rapport complet dans rapports/, nommé AAAA-MM-JJ_HHMM-<agent>-<tâche>.md, avec l'heure lue par `date`, jamais estimée, ne s'écrit que dans ces cas, quelle que soit la session (développement, passage, formation, maintenance) : modification de CONTEXTE.md ou de SPEC.md, échec, arrêt (STOP, garde, outil refusé), décision à soumettre à Sylvain. Contenu minimal : date et heure, agent, tâche, commits produits (ou « aucun »), contexte_empreinte, bloc « Compte et quotas » (D71, REGLES §9), ce qui a été fait, points fragiles ou à décider. Hors de ces cas, la tâche se termine par le compte rendu (REGLES §8 : bloc « Compte et quotas » d'abord, puis 10 lignes). Dev-delta : nom d'agent `dev-delta`.

Heure : `date +%Y-%m-%d_%H%M` au moment de l'écriture. Ne commite jamais ce dossier. Aucun secret (REGLES §5).
