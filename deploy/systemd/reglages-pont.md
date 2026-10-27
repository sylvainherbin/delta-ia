# Pont bilan OPÉRER → constats internes (timer hebdomadaire)

`scripts/reglages_pont.py` transforme `operer reglages bilan --json` (poste principal et instance d'essai) en constats datés dans
`kb-modeles/*.yaml` (clé `cle_auto`, propre au YAML). `scripts/reglages-pont.sh` l'enchaîne sur une branche dédiée
(`reglages-pont/AAAA-MM-JJ`, worktree `~/projets/.worktrees/delta-ia/reglages-pont-AAAA-MM-JJ`), avec `catalogue.py modeles`,
`valider.py --perimetre claude --kb` et les tests des fiches, puis dépose un message dans la boîte du chef dev, hors OPÉRER :
`~/.local/state/chef-dev/boite/AAAA-MM-JJ_HHMMSS-reglages-pont.md`. Le fichier contient le texte, la branche, le hash et le worktree ;
il est écrit dans un fichier temporaire du même dossier, puis renommé atomiquement. `DELTA_PONT_BOITE` redéfinit ce dossier.
Pas de push : le chef relit, fusionne et pousse.

Installation (après la fusion de la mission) :

```sh
mkdir -p ~/.config/delta ~/.config/systemd/user
# commande de l'instance d'essai (lecture seule), hors dépôt ; hôte et compte à renseigner (voir le rapport de la mission)
cat > ~/.config/delta/reglages-bilans.json <<'JSON'
{"essai": ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "<utilisateur>@<hôte-essai>",
           "sudo -n -u <compte-essai> bash -lc 'PATH=<dossier-operer-essai>:$PATH operer reglages bilan --json'"]}
JSON
cp ~/projets/delta-ia/deploy/systemd/delta-reglages-pont.service.exemple ~/.config/systemd/user/delta-reglages-pont.service
cp ~/projets/delta-ia/deploy/systemd/delta-reglages-pont.timer.exemple ~/.config/systemd/user/delta-reglages-pont.timer
systemctl --user daemon-reload && systemctl --user enable --now delta-reglages-pont.timer
systemctl --user list-timers delta-reglages-pont.timer
```

Ajustements proposés (lot 4) : le même passage écrit `<etat>/delta-ia/personnel/ajustements-reglages.json` (couche personnelle,
hors dépôt), lu par le relais local (`GET /suivi`) ; un nouvel ajustement est signalé au chef même sans constat à changer. Rien n'est
appliqué : la qualification revient à Delta Lab (`operer essai ouvrir --protocole`, protocole complété à partir du brouillon).

Essai à blanc, sans message : `DELTA_PONT_SANS_MESSAGE=1 scripts/reglages-pont.sh` (supprimer ensuite la branche et le worktree
affichés). Exports datés : `~/.local/state/delta/reglages-bilans/`.
