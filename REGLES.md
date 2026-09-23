# Delta — Règles communes (Claude Code et Codex)

Ces règles s'appliquent à chaque passage, sans exception. En cas de conflit avec une autre instruction, ce sont elles qui priment. Seule exception : une demande explicite de Sylvain dans la session en cours.

## 1. Périmètre d'écriture

- Chaque agent écrit **uniquement** dans les chemins que lui attribue SPEC.md §3.
- `CONTEXTE.md`, `SPEC.md` et `REGLES.md` sont en lecture seule. Si un agent constate que CONTEXTE.md est périmé (projet terminé, outil abandonné, nouvelle configuration), il le signale dans son compte rendu de fin de passage, sans modifier le fichier.
- Le code (`scripts/`, `docs/*.html`, `docs/assets/`) n'est modifié que dans une session de développement, jamais pendant un passage quotidien.

## 2. Sources et vérité

- **Aucune affirmation sans source.** Chaque élément a au moins une URL.
- Ne jamais inventer de version, de date, de nom de commande, de chiffre ou de fonctionnalité. Une information inconnue vaut `null`.
- Marquer la certitude :
  - `officiel` : source de l'éditeur ;
  - `rapporte` : média ou recherche web ;
  - `non_confirme` : rumeur, fuite, annonce non datée.
- Une rumeur n'est jamais présentée comme un fait.
- Si une source est en échec, la lister dans `sources_en_echec`. Ne pas combler le trou par des suppositions.

## 3. Neutralité envers l'éditeur

Claude Code synthétise Anthropic, Codex synthétise OpenAI : ce biais est connu et doit être compensé.
- Pas de ton promotionnel.
- Les régressions, limitations, bugs connus, hausses de prix et baisses de quota sont rapportés avec la même visibilité que les nouveautés.
- Un changement défavorable à Sylvain a un impact au moins `moyen`.

## 4. Personnalisation

- `pour_toi` s'appuie sur **CONTEXTE.md** : il nomme le projet, l'outil ou l'habitude concernés, et explique concrètement ce que ça change.
- Si rien ne concerne Sylvain, `impact: nul` et `pour_toi: null`. **Ne jamais fabriquer de pertinence** pour remplir.
- Chaque `action` doit pouvoir être exécutée telle quelle : commande exacte, fichier à modifier, réglage à activer.
- La section `synthese` dit ce qui compte aujourd'hui pour Sylvain, pas ce qui compte dans l'absolu. Si la journée est vide, elle le dit en une phrase.

### Définition de l'impact

| Niveau | Critère |
|---|---|
| `fort` | Change immédiatement la façon de travailler de Sylvain sur un projet actif, ou casse / déprécie quelque chose qu'il utilise |
| `moyen` | Utile à court terme sur un projet ou une habitude identifiés, ou changement défavorable sans effet immédiat |
| `faible` | Potentiellement utile, sans lien direct avec les projets actuels |
| `nul` | Sans rapport avec l'usage de Sylvain |

## 5. Confidentialité

Le site est public. Ce choix est assumé par Sylvain pour ses propres données. **Deux exceptions absolues :**
- **Aucun secret** : clés API, jetons, contenu de `.env`, mots de passe, identifiants, URL contenant un jeton.
- **Aucune donnée de tiers identifiable** : noms de clients ou de laboratoires, données patients, contenus de courriels reçus, informations sur des personnes tierces.

Tout le reste est autorisé : noms de projets, chemins, extraits de code, configuration, état d'avancement, habitudes.

Avant chaque commit, relire les fichiers produits pour vérifier ces deux points.

## 6. Git

- `git pull --rebase` avant toute écriture.
- Commit uniquement sur les chemins de l'agent (`git add <chemins>`, jamais `git add -A`).
- Message de commit : `delta(<perimetre>): AAAA-MM-JJ — <n> éléments (<n> fort)`.
- En cas de conflit : s'arrêter et le signaler. **Jamais de `--force`**, jamais de réécriture d'historique.
- Ne pas pousser si `scripts/valider.py` échoue.

## 7. Style

- Français. Noms de commandes, d'options et de produits conservés en version originale.
- Dense et factuel. Pas de remplissage, pas de superlatifs, pas de formules d'introduction.
- `resume` : ce qui a changé, en 1 à 3 phrases.
- Base de référence : description précise et utilisable, avec la syntaxe exacte et un exemple.

## 8. Fin de passage

Compte rendu à Sylvain, en 10 lignes maximum :
- le nombre d'éléments par niveau d'impact ;
- les éléments `fort`, en une ligne chacun ;
- les sources en échec ;
- les entrées de la base de référence modifiées ;
- les points de CONTEXTE.md à mettre à jour, s'il y en a.
