# Sélection hebdomadaire S1

Installer **après relecture et fusion sur main**, depuis `/home/herbin/projets/delta-ia` :

```sh
install -Dm644 deploy/systemd/delta-ia-selection.service ~/.config/systemd/user/delta-ia-selection.service
install -Dm644 deploy/systemd/delta-ia-selection.timer ~/.config/systemd/user/delta-ia-selection.timer
systemctl --user daemon-reload
systemctl --user enable --now delta-ia-selection.timer
systemctl --user list-timers delta-ia-selection.timer --no-pager
```

Avant le 19 octobre 2026, le service ne produit rien (même en rattrapage persistant).
Installé avant cette date, le prochain déclenchement attendu est **lundi 19/10/2026 à 06:30 Europe/Paris**.
Le calendrier garde 06:30 à Paris après les changements d'heure. Vérification sans installation :

```sh
systemd-analyze calendar --base-time='2026-10-15 12:00:00' 'Mon *-*-* 06:30:00 Europe/Paris'
```

Le service prend `.git/delta-passage.lock` avant toute lecture/écriture Git et le garde jusqu'à la fin du push.
Il attend la fin de la chaîne nocturne ; le délai total du service est borné à 4 h 15.
Il exige main, l'absence de changements étrangers et aucun commit local étranger non publié, récupère origin/main
en avance rapide, appelle le sélecteur, puis `valider.py` sur les trois périmètres avant tout commit/push.
Sans distant, il commite localement. Avec origin, il pousse le SHA produit vers main, sans force.
`selection.py` écrit les sélections sans faire de commit ; le service est responsable de publier
tous les `rapports/selection/AAAA-Www.json` et `.md` en attente, quelle que soit leur semaine.
Une semaine ancienne lue ou refaite depuis la Console est donc embarquée avec la semaine publiée.
Chaque JSON est relu et son bref reconstitué avant validation et ajout explicite des seuls chemins concernés.
Tout changement dans l'arbre ou l'index hors de ce domaine continue de bloquer la publication.
`retours.yaml` et `retours.yaml.lock` restent ignorés : ils ne bloquent pas et ne sont jamais ajoutés.
Le Markdown compte au plus cinq lignes (titres et raisons courtes) ; `selection.py --bref` garde son contrat actuel.

Précontrôles machine après fusion : `loginctl show-user "$USER" -p Linger`, `git config --get commit.gpgsign`,
hooks du dépôt et authentification Git sans interaction (`GIT_TERMINAL_PROMPT=0 git ls-remote origin HEAD`).
Le service utilise le PATH utilisateur incluant `~/.local/bin` (notamment le helper Git existant).
Il ne modifie ni les hooks, ni la signature, ni les identifiants Git du compte.

En cas d'échec : `journalctl --user -u delta-ia-selection.service -n 50 --no-pager`.
`Persistent=true` rattrape un calendrier manqué, mais ne réessaie pas un service en échec.
Après correction : `systemctl --user start delta-ia-selection.service`.
Un JSON déjà produit est relu à l'identique ; un Markdown manquant est reconstitué.
Un unique commit au titre de cette semaine est repoussé seulement si son parent est le distant,
ses chemins appartiennent tous au domaine des sélections, l'arbre et l'index n'ont aucun changement
public en attente, et chaque paire JSON/bref embarquée est cohérente (ainsi que la semaine courante),
après validation. La reprise ne crée aucun nouveau commit.
Si origin avance après ce commit (push rejeté), le service refuse la divergence : résolution manuelle,
sans rebase/reset automatique. Aucun commit de sélection anticipée ne fait partie de la livraison.
