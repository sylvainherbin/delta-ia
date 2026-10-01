#!/usr/bin/env bash
# Delta — point d'entrée de la chaîne de passages automatiques (D70), lancé par un timer systemd utilisateur.
# Tient `flock -n .git/delta-passage.lock` pendant toute la chaîne : une seule chaîne à la fois, et la garde (code 14) arrête
# net toute relance manuelle pendant ce temps. Fixe lui-même HOME, PATH et le dossier de travail (aucun environnement hérité
# d'une session graphique : mode nuit). Ne lance rien d'autre que scripts/orchestrateur.py, qui porte toute la logique.
#
# Codes de sortie : 0 chaîne sans échec ; 1 au moins une étape en échec ; 2 mauvais argument ; 14 chaîne déjà en cours ;
# 16 environnement du dépôt illisible (.venv absent).
set -u

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE" || exit 16
HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
export HOME
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

PYTHON="$RACINE/.venv/bin/python"
[ -x "$PYTHON" ] || { echo "passage-auto : $PYTHON introuvable (voir CLAUDE.md : python3 -m venv .venv)" >&2; exit 16; }

VERROU="$RACINE/.git/delta-passage.lock"
exec 9>>"$VERROU"
if ! flock -n 9; then
    echo "passage-auto : une chaîne est déjà en cours (.git/delta-passage.lock tenu), rien n'est lancé" >&2
    exit 14
fi
# Le descripteur 9 reste ouvert dans le processus Python (même PID après exec) : le verrou dure jusqu'à la fin de la chaîne.
exec "$PYTHON" "$RACINE/scripts/orchestrateur.py" "$@"
