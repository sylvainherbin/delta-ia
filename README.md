# Delta

Veille IA quotidienne et personnelle : résumé de l'actualité IA, changelogs de Claude, Claude Code, ChatGPT et Codex, recommandations personnalisées (`CONTEXTE.md`) et base de référence. Site statique servi depuis `docs/`.

La récupération est déterministe (`scripts/fetch.py`) ; seule la synthèse passe par un agent (Claude Code pour `claude` et `actu`, Codex pour `openai`). Voir `SPEC.md` (cahier des charges) et `REGLES.md` (règles communes).

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Lancer un passage

- Claude Code : `/delta` (skill `.claude/skills/delta/SKILL.md`), périmètres `claude` puis `actu`.
- Codex : `$delta` (skill `.agents/skills/delta/SKILL.md`), périmètre `openai` ; à défaut, coller `prompts/codex-delta.md`.

Ce que la skill enchaîne (SPEC.md §6) :

```bash
# 1. Récupérer et détecter les nouveautés, sans toucher à l'état (premier passage réel : --depuis J-7)
.venv/bin/python scripts/fetch.py --perimetre claude        # ou openai, actu -> raw/claude-nouveautes.json
# 2. L'agent écrit docs/data/claude/AAAA-MM-JJ.json et index.json
# 3. Valider les JSON produits et la couverture des nouveautés brutes
.venv/bin/python scripts/valider.py --perimetre claude --brut raw/claude-nouveautes.json
# 4. Faire avancer l'état pour ce que le fichier quotidien comptabilise (code 4 si des nouveautés restent en attente)
.venv/bin/python scripts/fetch.py --perimetre claude --valider [--date AAAA-MM-JJ]
```

Options de `fetch.py` : `--depuis AAAA-MM-JJ` (borne basse, sinon 30 jours au premier passage), `--dry-run` (n'écrit rien), `--sources chemin.yaml`.

## Tests

```bash
.venv/bin/pytest -q
```

## Connecteur MCP

- Serveur : `https://delta-mcp-ruddy.vercel.app/mcp` (Streamable HTTP, code dans `mcp/`, déployé sur Vercel à chaque push sur `main`).
- Outils : `resume_du_jour`, `chercher_reference`, `fiche_reference`, `etat_versions`, `a_tester`, `nouveautes_base`.
- Lecture seule sur les JSON publics de `docs/data` : ni jeton, ni écriture, ni déclenchement de passage (SPEC §2, D61).
- Deux sources (deux couches, lot L3) : l'ancienne route `docs/data` (défaut tant que la bascule L5 n'est pas faite) ou la génération commune `docs/commun/v1/` (`?source=commun` sur l'adresse, ou `DELTA_SOURCE=commun` sur Vercel). Chaque réponse dit sa source (`donnees`). Sur la référence commune : aucun avis, impact, essai ni version installée, dits indisponibles.
- Langue : anglais par défaut, français par `?langue=fr` sur l'adresse ou `langue: "fr"` à chaque appel ; commandes, identifiants et données ne se traduisent pas. Constats internes et recommandations OPÉRER ne sont jamais rendus.
- Adresses publiques : seule source `scripts/deltalib/couches/bootstrap.json` ; `scripts/urls.py` en écrit les copies `docs/assets/config.js` et `mcp/lib/config.js`.
