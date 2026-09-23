@SPEC.md
@REGLES.md

# Conventions du dépôt Delta

- Français, tutoiement. Noms de commandes, d'options et de produits en version originale.
- Périmètres de Claude Code : `claude`, `claude-code`, `actu`. Écriture uniquement dans `docs/data/claude/`, `docs/data/actu/`, `docs/data/kb/claude/`, `state/claude.json`, `state/actu.json` (SPEC.md §3).
- `CONTEXTE.md`, `SPEC.md`, `REGLES.md` : lecture seule. Signaler, ne pas corriger.
- Python 3.12, environnement `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Pas de `pip` système.
- Tests : `.venv/bin/pytest -q`. Analyseurs testés sur des échantillons réels dans `tests/fixtures/`.
- `scripts/fetch.py` n'écrit jamais dans `state/` sans `--valider`. `raw/` est ignoré par git.
- Une source en échec ou au format inattendu va dans `sources_en_echec` ; jamais de résultat vide silencieux.
- Sources déclarées dans `sources.yaml` uniquement, chaque URL testée avant inscription. Statuts : `ok`, `bloque`, `a_valider`, `desactive` (une source écartée est désactivée, pas supprimée).
- Aucune date, version ou fonctionnalité devinée : inconnu vaut `null`.
- Git (SPEC §6, D9) : `git add <chemins>` explicites, jamais `git add -A`, jamais `--force`. Sans dépôt distant : ni pull ni push. Avec un distant : lancer `/delta` vaut accord de push sur les seuls chemins de l'agent ; en session de développement, push seulement sur accord de Sylvain.
- Le code (`scripts/`, `docs/*.html`, `docs/assets/`) ne change qu'en session de développement, jamais pendant un passage quotidien.
- Passage quotidien : `/delta` (skill `.claude/skills/delta/SKILL.md`), jamais déclenché sans demande de Sylvain. Le pilotage du projet est délégué à la session Delta-IA : ses décisions numérotées s'appliquent sans plan préalable.
