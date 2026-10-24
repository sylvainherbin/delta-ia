# Génération commune quotidienne (lot L2 des deux couches)

Installer **après relecture et fusion sur main**, depuis `~/projets/delta-ia` :

```sh
install -Dm644 deploy/systemd/delta-ia-commun.service ~/.config/systemd/user/delta-ia-commun.service
install -Dm644 deploy/systemd/delta-ia-commun.timer ~/.config/systemd/user/delta-ia-commun.timer
systemctl --user daemon-reload
systemctl --user enable --now delta-ia-commun.timer
systemctl --user list-timers delta-ia-commun.timer --no-pager
```

Chaque jour à 06:45 (Paris), après la chaîne de 04:00 (seul commit automatique admis dans la fenêtre 03:30-08:00, SPEC §3) : le service prend `.git/delta-passage.lock`, exige main et un
arbre propre hors de la route commune, avance origin/main en avance rapide, puis lance `scripts/commun_auto.py` :
import dans les racines de l'installation historique (`~/.local/state/delta/delta-ia/`, `~/.cache/delta/delta-ia/`),
extraction de la base sans filtre de système depuis `raw/kb/`, génération commune isolée, publication dans
`docs/commun/v1/` (servie à `https://ai.orqyra.io/commun/v1/`), validation de la route, commit des seuls chemins
`docs/commun/v1/` et `kb-traductions/fr.json`, push sans force.

Mode : le service publie toujours depuis l'installation historique, productrice par construction (même exception que
`couches.py publier`) ; il ne lit pas `mode` et n'exige aucun `config.json`. `mode: producteur` ne sert qu'à une autre
instance qui publierait par `couches.py publier`.

Traductions : `production.budget_traduction` vaut 0 dans `scripts/deltalib/couches/bootstrap.json` (cache seul, aucun
appel de modèle). Pour traduire chaque nuit les textes nouveaux, le fixer dans `~/.config/delta/delta-ia/config.json` :

```json
{"production": {"budget_traduction": 40}}
```

Le rédacteur est `claude -p --safe-mode` (Haiku, sans outil ni profil) : `claude` doit être dans le PATH du service
(`~/.local/bin`). Coût mesuré le 24/10/2026 : environ 0,009 $ au prix catalogue et 50 s par lot de 40 textes.

Surveillance du producteur, sans écriture : `.venv/bin/python scripts/couches.py surveiller --url https://ai.orqyra.io/commun/v1/`
(code 1 si le cycle de 24 h est manqué de plus de 6 h ou si un périmètre n'a pas de jour depuis plus de 2 jours).

En cas d'échec : `journalctl --user -u delta-ia-commun.service -n 50 --no-pager`. `Persistent=true` rattrape un
calendrier manqué, mais ne réessaie pas un service en échec. Retrait : `systemctl --user disable --now delta-ia-commun.timer`.
