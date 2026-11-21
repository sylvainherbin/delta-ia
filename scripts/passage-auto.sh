#!/usr/bin/env bash
# Delta — point d'entrée de la chaîne de passages automatiques (D70), lancé par un timer systemd utilisateur.
# Tient `flock -n .git/delta-passage.lock` pendant toute la chaîne : une seule chaîne à la fois, et la garde (code 14) arrête
# net toute relance manuelle pendant ce temps. Fixe lui-même HOME, PATH et le dossier de travail (aucun environnement hérité
# d'une session graphique : mode nuit). Ne lance rien d'autre que scripts/orchestrateur.py, qui porte toute la logique.
#
# Codes de sortie : 0 chaîne sans échec ; 1 au moins une étape en échec (dont le contrôle de valider.py après une étape, code 131 dans le journal) ; 2 mauvais argument ; 14 chaîne déjà en cours ;
# 16 environnement du dépôt illisible (.venv absent) ; 126 témoin d'incident git non levé (rapports/auto/incident-git.json)
# ou fichier ignoré sous scripts/ hors __pycache__/ (ARBRE_CODE_SALE).
set -u

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE" || exit 16
HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
export HOME
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8
# B2 : .pyc hors de l'arbre (un __pycache__/ piégé dans scripts/, ignoré par git, n'est pas chargé).
export PYTHONPYCACHEPREFIX="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/delta-ia-pycache"

PYTHON="$RACINE/.venv/bin/python"
[ -x "$PYTHON" ] || { echo "passage-auto : $PYTHON introuvable (voir CLAUDE.md : python3 -m venv .venv)" >&2; exit 16; }

VERROU="$RACINE/.git/delta-passage.lock"
exec 9>>"$VERROU"
if ! flock -n 9; then
    echo "passage-auto : une chaîne est déjà en cours (.git/delta-passage.lock tenu), rien n'est lancé" >&2
    exit 14
fi
# Le descripteur 9 reste ouvert dans le processus Python (même PID après exec) : le verrou dure jusqu'à la fin de la chaîne.
# Témoin d'incident non levé : un .pth ou un sitecustomize posé dans le .venv s'exécuterait au démarrage de Python, avant
# le contrôle de l'orchestrateur. Rien n'est lancé (126) tant que le superviseur ne l'a pas levé.
if [ -e "$RACINE/rapports/auto/incident-git.json" ] || [ -L "$RACINE/rapports/auto/incident-git.json" ]; then
    echo "passage-auto : INCIDENT_GIT, rapports/auto/incident-git.json non levé : rien n'est lancé" >&2
    exit 126
fi
# B2a, après le témoin : un fichier IGNORÉ sous scripts/ (un html.pyc ou un zoneinfo.pyc sans source) serait importé par
# l'orchestrateur avant son propre contrôle. Seul __pycache__/ est toléré : PYTHONPYCACHEPREFIX l'écarte.
if ! IGNORES="$(git ls-files -o -i --exclude-standard -- scripts)"; then
    echo "passage-auto : ARBRE_CODE_SALE, fichiers ignorés sous scripts/ illisibles : rien n'est lancé" >&2
    exit 126
fi
IGNORES="$(printf '%s\n' "$IGNORES" | grep -v -e '/__pycache__/')"
if [ -n "$IGNORES" ]; then
    echo "passage-auto : ARBRE_CODE_SALE, fichiers ignorés sous scripts/ : $(printf '%s\n' "$IGNORES" | head -n 5 | tr '\n' ' '); rien n'est lancé" >&2
    exit 126
fi
exec "$PYTHON" "$RACINE/scripts/orchestrateur.py" "$@"
