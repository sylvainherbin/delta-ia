---
id: consultation-croisee
nom: "Second regard croisé : ask-codex et ask-claude"
produits: [claude-code, codex]
verifie_le: 2026-10-13
versions:
  claude-code: 2.1.296
  codex: 0.162.1
certitude: officiel
sources:
  - url: https://code.claude.com/docs/en/skills
    libelle: "Claude Code — skills (SKILL.md, ~/.claude/skills)"
  - url: https://code.claude.com/docs/en/headless
    libelle: "Claude Code — mode non interactif (claude -p)"
  - url: https://code.claude.com/docs/en/cli-reference
    libelle: "Claude Code — options de claude (--tools, --disallowed-tools, --no-session-persistence, --output-format, --strict-mcp-config, --setting-sources, --disable-slash-commands, --no-chrome, --system-prompt)"
  - url: https://learn.chatgpt.com/docs/non-interactive-mode
    libelle: "Codex — mode non interactif (codex exec)"
  - url: https://learn.chatgpt.com/docs/developer-commands?surface=cli
    libelle: "Codex — options de codex exec (-s/--sandbox, --ephemeral, --skip-git-repo-check, -C/--cd, --json, -o/--output-last-message, -m/--model)"
  - url: https://learn.chatgpt.com/docs/build-skills
    libelle: "Codex — skills (SKILL.md, agents/openai.yaml, allow_implicit_invocation)"
---

**Statut.** Les commandes et options citées sont celles des éditeurs, vérifiées le 13/10/2026 sur codex-cli 0.162.1 et Claude Code 2.1.296 (sources ci-dessous). La méthode elle-même (les deux skills, le script `consulter`, les règles d'emploi) est locale à Delta : aucun éditeur ne la documente.

**Ce que c'est.** Deux skills qui laissent un agent demander un avis à l'autre fournisseur : `ask-codex` (dans Claude Code) consulte Codex, `ask-claude` (dans Codex) consulte Claude. Une question courte, une seule réponse, aucun fichier modifié par le modèle consulté. L'agent qui consulte confronte la réponse à sa propre analyse et tranche lui-même.

**Quand l'utiliser.** Avant de trancher un choix risqué ou difficile à défaire (architecture, migration, suppression, droits) ; pour chercher les contre-arguments d'un raisonnement ou d'un plan ; devant un doute sur un défaut qu'on n'arrive ni à confirmer ni à écarter. Pas pour une question triviale, pour une information qu'une lecture de fichier ou une commande établit directement, pour déléguer un travail, ni pour relancer la même question jusqu'à obtenir une autre réponse.

**Commandes.** Les skills appellent un script commun, `consulter` :

```bash
consulter codex  -f fichier1 -f fichier2 <<'QUESTION'    # depuis Claude Code
consulter claude -f fichier1 -f fichier2 <<'QUESTION'     # depuis Codex
<question autonome : contexte, ce qui est décidé, ce qu'on veut savoir>
QUESTION
```

Options : `-f FICHIER` (texte UTF-8, répétable), `--max-ko N` (défaut 80, question et fichiers), `--delai S` (défaut 600), `-m MODELE`. La réponse sort sur stdout ; une ligne `[consulter] …` (durée, jetons, coût) sur stderr. Codes : 0 réponse ; 1 échec du modèle consulté ; 2 appel invalide ou contexte trop gros ; 3 binaire absent ; 4 consultation imbriquée refusée ; 124 délai dépassé.

Appels réels derrière le script :
- `codex exec -s read-only --ephemeral --skip-git-repo-check -C <dossier vide> --json -o <fichier> -`
- `claude -p --tools "" --disallowed-tools Edit Write NotebookEdit --no-session-persistence --output-format json --strict-mcp-config --setting-sources project --disable-slash-commands --no-chrome --system-prompt <consigne>`

**Installation.** Script dans le PATH ; skill `ask-codex` dans `~/.claude/skills/ask-codex/SKILL.md` ; skill `ask-claude` dans `$CODEX_HOME/skills/ask-claude/` (`~/.codex/skills/` par défaut), avec `agents/openai.yaml` (`policy: allow_implicit_invocation: true`) pour que Codex puisse l'invoquer seul. Écart à noter : la documentation de Codex donne `$HOME/.agents/skills` comme dossier des skills d'utilisateur et ne mentionne pas `~/.codex/skills` ; l'emplacement ci-dessus est celui constaté en service sur la machine de Delta.

**Limites.**
- Lecture seule et une seule réponse. Claude n'a aucun outil ; Codex tourne en sandbox `read-only` dans un dossier vide, mais ce sandbox autorise encore des lectures sur le disque : le dossier vide limite le contexte, il n'est pas une barrière de confidentialité. Ne transmettre aucun secret.
- Coût réel, décompté du forfait du fournisseur consulté. Sans `--system-prompt`, `--strict-mcp-config` et `--disable-slash-commands`, un « ok » à `claude -p` chargeait 161 k jetons (1,29 $) ; avec, 0,005 $. Un appel de 543 octets a coûté 0,033 $ avec le modèle par défaut (Opus 5.5) ; `-m` choisit un modèle moins cher.
- Contexte borné : refus explicite au-delà de `--max-ko`, jamais de troncature silencieuse.
- Le modèle consulté ne connaît ni la conversation ni le dépôt : la question doit se suffire.
- Un journal local d'une ligne par consultation (horodatage, sens, modèle, durée, jetons, coût, statut, tailles), sans le texte.

**Script.** `consulter` vit dans un dépôt privé, sans adresse publique ; seuls les appels listés plus haut sont documentés ici.
