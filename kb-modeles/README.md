# Catalogue des modèles et efforts

Sources éditées dans les fichiers YAML ; génération sans réseau :

```sh
python scripts/catalogue.py modeles
```

L’unique fichier public est `docs/data/kb/modeles.json`. Le schéma v2 contient :

- `modeles`, dictionnaire des données communes par identifiant : fournisseur, forfait, prix API,
  points forts/faibles, benchmarks, constats, sources, description commune et gabarits d’alias ;
- `entrees`, un enregistrement par couple modèle × effort : `modele` désigne la donnée commune ;
  coût quota, invocation, recommandation et description propre à l’effort restent sur le couple ;
- `forfaits`, les forfaits de référence, et les compteurs `total_modeles` et `total`.

Un lecteur assemble `{...doc.modeles[couple.modele], ...couple}`. Le site emploie
`developperModeles` dans `docs/assets/kb-modeles.mjs`, qui reconstitue aussi la description et les alias.
Le MCP garde son lecteur dans `mcp/lib/modeles.js`, dans sa racine de déploiement ; un test compare
les deux sorties sur le catalogue public.
Les consommateurs programmatiques peuvent lire les données structurées sans produire les descriptions.
`schema_version` doit être contrôlé avant la lecture. Aucun lecteur ne doit encore viser
`docs/data/modeles.json`, supprimé car redondant.

`effort_defaut_modele`, avec `effort_defaut_portee` et `effort_defaut_detail`, décrit le défaut de
l’exécutant ou une convention locale, selon la portée indiquée. Ce n’est pas une consigne de lancement
OPÉRER : le couple choisi à l’ouverture de la mission reste explicite. Un niveau Codex comme `ultra`
ne devient pas un niveau API par déduction. Les fenêtres API ne décrivent pas le contexte effectif CLI.
`produits` conserve les contextes d’usage auxquels une fiche est pertinente ; ce champ n’identifie pas
le fournisseur. Les modèles locaux et Antigravity restent donc visibles aux utilisateurs de Codex
et de Claude Code, tandis que `executant` et `fournisseur` disent où le couple s’exécute.

Un alias partagé renvoie des candidats dans `fiche_reference` (`ambigu: true`), jamais le premier
trouvé silencieusement. Un identifiant canonique ou un alias qualifié par exécutant départage les
candidats. `chercher_reference` signale aussi les alias ambigus. À score égal, la documentation passe
avant les fiches modèles ; effort et alias ne gonflent pas le nom utilisé dans le classement.

Une valeur inconnue est `null`. Le coût par effort dans l’allocation d’un abonnement n’est pas déduit
du tarif API ni du barème de crédits. `tarifs_credits`, quand renseigné, conserve ce barème séparément ;
il ne donne pas le coût d’une tâche en quota. Les prix Anthropic recopiés sur une fiche Antigravity
portent explicitement sur l’API Anthropic directe du modèle sous-jacent. Les recommandations sont des conseils locaux à évaluer ; les
observations internes sont distinctes des annonces publiques et ne sont pas des barèmes universels.
Pour une affirmation ou un benchmark `verifie: true`, un `extrait` de la page lue est obligatoire.
Ce contrôle de forme ne remplace pas une nouvelle lecture de la source lors d’une mise à jour.

Reprise du 20/10/2026 : comparaisons contradictoires ou absentes retirées ; les nombres maintenus se
lisent dans les sources citées. Les dates de sortie et spécifications non retrouvées restent inconnues.
Les scores Anthropic recopiés dans une fiche Antigravity décrivent le modèle évalué chez Anthropic,
pas une mesure de l’exécutant `agy`. L’accès Pro observé localement ne généralise pas l’annonce Ultra.

Constats internes automatiques (22/10/2026) : `scripts/reglages_pont.py` écrit, par fiche × effort × nature × source (poste
principal, instance d'essai), un constat issu de `operer reglages bilan --json`, repéré dans le YAML par `cle_auto` (champ absent du
catalogue public). Un constat sans `cle_auto` est manuel et n'est jamais lu ni réécrit. Seuil : 5 missions relues par cellule, avec
réserve d'effectif réduit sous 10 ; les cellules écartées et les couples sans fiche sont listés dans le bilan de l'outil. Les
exécutants d'une famille sont confondus, les valeurs inconnues restent « inconnu ». Un timer hebdomadaire prépare la mise à jour sur une
branche dédiée, sans push (`deploy/systemd/reglages-pont.md`).

Ajustements proposés (24/10/2026, lot 4) : le même passage compare chaque couple observé au témoin de la politique en vigueur et range
des ajustements (une clé, motif, observations, limites) dans la couche personnelle, hors dépôt et hors site ; ils entrent « proposé »
dans la boucle d'adoption et attendent la qualification de Delta Lab. Ils ne touchent ni aux fiches ni aux constats.
