#!/usr/bin/env bash
# Delta — point d'entrée de la chaîne de passages automatiques (D70), lancé par un timer systemd utilisateur.
# Tient `flock -n .git/delta-passage.lock` pendant toute la chaîne : une seule chaîne à la fois, et la garde (code 14) arrête
# net toute relance manuelle pendant ce temps. Fixe lui-même HOME, PATH et le dossier de travail (aucun environnement hérité
# d'une session graphique : mode nuit). Ne lance rien d'autre que scripts/orchestrateur.py, qui porte toute la logique.
#
# Codes de sortie : 0 chaîne sans échec ; 1 au moins une étape en échec (dont le contrôle de valider.py après une étape, code 131 dans le journal) ; 2 mauvais argument ; 14 chaîne déjà en cours ;
# 16 environnement du dépôt illisible (.venv absent) ; 126 témoin d'incident git non levé (rapports/auto/incident-git.json)
# ou binaire Python (*.pyc, *.pyo, *.so, *.pyd) sous scripts/ hors __pycache__/ (ARBRE_CODE_SALE).
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
    # SUITE 3, point 6 : trace au journal des passages, en shell (aucun Python ne démarre), au format de passages.ligne ;
    # un journal non inscriptible ne change pas le code.
    mkdir -p "$RACINE/rapports" 2>/dev/null
    printf '%s | orchestrateur | chaine-git | 0 éléments (0 fort) | aucun | 126 | %s\n' "$(date +%Y-%m-%d_%H%M)" \
        "INCIDENT_GIT : rapports/auto/incident-git.json non levé, passage-auto n'a rien lancé" \
        >> "$RACINE/rapports/passages.log" 2>/dev/null
    exit 126
fi
# SUITE 4, point 1 : aucun git avant l'orchestrateur (un core.fsmonitor ou un hook posé dans .git s'exécuterait au premier
# git, ls-files compris). Parcours de scripts/ par la seule bibliothèque standard, en Python isolé : tout *.pyc, *.pyo,
# *.so ou *.pyd hors de __pycache__/ (un html.pyc sans source, importé par l'orchestrateur avant son propre contrôle)
# arrête. __pycache__/ est écarté par PYTHONPYCACHEPREFIX. Même code que les ExecStartPre des unités.
# SUITE 5, point 3 : tout lien symbolique sous scripts/ (scripts/ compris, __pycache__/ compris) arrête aussi.
if ! /usr/bin/python3 -I -S -c "import os, sys; x = ('.pyc', '.pyo', '.so', '.pyd'); w = list(os.walk('scripts', onerror=lambda e: (sys.stderr.write('ARBRE_CODE_SALE : scripts illisible (' + str(e) + '), rien n est lancé\\n'), os._exit(126)))); l = (['scripts'] if os.path.islink('scripts') else []) + sorted(os.path.join(d, n) for d, s, fs in w for n in s + fs if os.path.islink(os.path.join(d, n))); b = sorted(os.path.join(d, f) for d, s, fs in w if '__pycache__' not in d.split(os.sep) for f in fs if f.lower().endswith(x)); sys.stderr.write('ARBRE_CODE_SALE : liens symboliques sous scripts : ' + ' '.join(l[:5]) + ', rien n est lancé\\n' if l else ''); sys.stderr.write('ARBRE_CODE_SALE : binaires hors de __pycache__ sous scripts : ' + ' '.join(b[:5]) + ', rien n est lancé\\n' if b else ''); sys.exit(126 if l or b else 0)"; then
    echo "passage-auto : ARBRE_CODE_SALE, rien n'est lancé" >&2
    exit 126
fi
exec "$PYTHON" "$RACINE/scripts/orchestrateur.py" "$@"
