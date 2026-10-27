#!/usr/bin/env bash
# Delta — mise à jour hebdomadaire des constats internes des fiches de modèles depuis le bilan des réglages.
# Lancé par le timer systemd utilisateur delta-reglages-pont (lundi 10 h 30). Travaille dans un worktree et une branche à lui
# (reglages-pont/AAAA-MM-JJ), jamais dans le dépôt principal : collecte les bilans (scripts/reglages_pont.py tout), régénère
# docs/data/kb/modeles.json, passe valider.py et les tests des fiches, commite sur la branche, puis prévient le chef dev
# par sa boîte de fichiers avec la branche et le hash. Aucun push, aucune fusion : le chef relit avant publication (site public).
# Le même passage range les ajustements proposés (lot 4) dans la couche personnelle, hors dépôt ; un nouvel ajustement est dit
# au chef même sans constat à changer. Rien n'est appliqué : Delta Lab qualifie sur le K8 avant tout lot.
#
# Fenêtre sans commit 03 h 30 – 08 h 00 : en cas de lancement dans la fenêtre (rattrapage au démarrage), attend 08 h 05.
# Tient .git/delta-passage.lock sans attendre pendant tout le travail (une chaîne de nuit en cours : rien n'est fait, code 14).
# Variables d'essai : DELTA_PONT_BOITE=<dossier> (boîte du chef dev, défaut ~/.local/state/chef-dev/boite),
# DELTA_PONT_SANS_MESSAGE=1 (affiche le message sans écrire dans la boîte), DELTA_PONT_HEURE=HHMM (heure simulée),
# DELTA_PONT_BASE=<branche> (base de la branche de travail, défaut main), DELTA_PONT_PYTHON (interpréteur, défaut .venv du dépôt).
#
# Codes : 0 fait (constats prêts, ou rien à changer) ; 1 échec (message au chef) ; 3 fait, mais une source du bilan est en échec
# (dite dans le message) ; 14 chaîne en cours ; 16 environnement illisible.
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
export HOME
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8 GIT_TERMINAL_PROMPT=0
PYTHON="${DELTA_PONT_PYTHON:-$RACINE/.venv/bin/python}"
[ -x "$PYTHON" ] || { echo "reglages-pont : $PYTHON introuvable" >&2; exit 16; }
cd "$RACINE" || exit 16

heure="${DELTA_PONT_HEURE:-$(date +%H%M)}"
if (( 10#$heure >= 330 && 10#$heure < 800 )); then
    attente=$(( ( (8 * 60 + 5) - (10#${heure:0:2} * 60 + 10#${heure:2:2}) ) * 60 ))
    echo "reglages-pont : fenêtre 03:30–08:00, attente de ${attente} s" >&2
    [ -n "${DELTA_PONT_HEURE:-}" ] && exit 0
    sleep "$attente"
fi

VERROU="$(git rev-parse --path-format=absolute --git-common-dir)/delta-passage.lock"
exec 9>>"$VERROU"
flock -n 9 || { echo "reglages-pont : une chaîne est en cours (delta-passage.lock tenu), rien n'est fait" >&2; exit 14; }

JOUR="$(date +%Y-%m-%d)"
BRANCHE="reglages-pont/$JOUR"
git show-ref --verify --quiet "refs/heads/$BRANCHE" && BRANCHE="$BRANCHE-$(date +%H%M)"
WT="$HOME/projets/.worktrees/delta-ia/reglages-pont-${BRANCHE#reglages-pont/}"
DOSSIER="$HOME/.local/state/delta/reglages-bilans"
mkdir -p "$DOSSIER"

prevenir() {
    local texte="[PONT RÉGLAGES] $1"
    if [ -n "${DELTA_PONT_SANS_MESSAGE:-}" ]; then echo "$texte"; return 0; fi
    local boite="${DELTA_PONT_BOITE:-$HOME/.local/state/chef-dev/boite}"
    local temporaire fichier hash
    mkdir -p -- "$boite" || return 1
    temporaire="$(mktemp "$boite/.reglages-pont.XXXXXX")" || return 1
    fichier="$boite/$(date +%Y-%m-%d_%H%M%S)-reglages-pont.md"
    hash="$(git -C "$WT" rev-parse HEAD 2>/dev/null || git rev-parse "${DELTA_PONT_BASE:-main}")" \
        || { rm -f -- "$temporaire"; return 1; }
    # Le verrou du passage sérialise les envois ; conserve aussi deux messages de la même seconde.
    while [ -e "$fichier" ]; do
        sleep 1
        fichier="$boite/$(date +%Y-%m-%d_%H%M%S)-reglages-pont.md"
    done
    if ! printf '%s\n\nBranche : %s\nHash : %s\nWorktree : %s\n' "$texte" "$BRANCHE" "$hash" "$WT" > "$temporaire" \
        || ! mv -- "$temporaire" "$fichier"; then
        rm -f -- "$temporaire"
        echo "reglages-pont : message au chef dev non écrit dans $boite" >&2
        return 1
    fi
}
echec() { prevenir "Échec de la mise à jour hebdomadaire : $1. Branche $BRANCHE, worktree $WT conservés pour examen."; exit 1; }

git worktree add -q -b "$BRANCHE" "$WT" "${DELTA_PONT_BASE:-main}" || { prevenir "Échec de la mise à jour hebdomadaire : worktree $WT impossible à créer."; exit 1; }
cd "$WT" || exit 16

rapport="$DOSSIER/$(date +%Y-%m-%d_%H%M)-rapport.json"
"$PYTHON" -B scripts/reglages_pont.py tout --racine "$WT" --json > "$rapport"
code=$?
[ "$code" -eq 0 ] || [ "$code" -eq 3 ] || echec "reglages_pont.py code $code"
resume="$("$PYTHON" -B - "$rapport" <<'PY'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
echec = [f"{s['source']} ({s.get('motif')})" for s in r["sources"] if s["statut"] == "echec"]
e = r["ecartes"]
print(f"{len(r['ecrits'])} constats écrits ({len(r['inchanges'])} inchangés, {len(r['obsoletes'])} obsolètes conservés) ; "
      f"écartés : {len(e['sous_seuil'])} cellules sous le seuil de {r['seuil']} relues, {e['nature_inconnue']} missions de nature inconnue, "
      f"{e['sans_reglage']} sans modèle ou effort, {len(e['sans_fiche'])} couples sans fiche"
      + (f" ; SOURCE EN ÉCHEC : {', '.join(echec)}" if echec else ""), end="")
a = r.get("ajustements")
if a and a["statut"] != "ok":
    print(f" ; AJUSTEMENTS EN ÉCHEC : {a['motif']}", end="")
elif a:
    print(f" ; ajustements proposés : {len(a['proposes'])} (nouveaux : {', '.join(a['nouveaux']) or 'aucun'}), "
          "à qualifier par Delta Lab avant tout lot, rien n'est appliqué", end="")
print(f". Rapport : {sys.argv[1]}")
PY
)"

nouveaux="$("$PYTHON" -B -c 'import json, sys; print(len((json.load(open(sys.argv[1], encoding="utf-8")).get("ajustements") or {}).get("nouveaux") or []))' "$rapport")"
if [ -z "$(git status --porcelain -- kb-modeles)" ]; then
    cd "$RACINE" && git worktree remove --force "$WT" && git branch -D "$BRANCHE" >/dev/null
    { [ "$code" -eq 3 ] || [ "${nouveaux:-0}" -gt 0 ]; } && prevenir "Mise à jour hebdomadaire : aucun constat à changer. $resume"
    echo "reglages-pont : aucun constat à changer. $resume"
    exit "$code"
fi

"$PYTHON" -B scripts/catalogue.py modeles || echec "catalogue.py modeles"
"$PYTHON" -B scripts/valider.py --perimetre claude --kb || echec "valider.py en échec"
verrou-tests --depot "$WT" -- "$PYTHON" -m pytest -q tests/test_kb_modeles.py tests/test_reglages_pont.py || echec "tests en échec"

mapfile -t fichiers < <(git diff --name-only -- kb-modeles docs/data/kb/modeles.json)
git add -- "${fichiers[@]}"
git commit -q -m "reglages-pont: constats internes automatiques $JOUR — $(echo "$resume" | cut -d' ' -f1) constats" || echec "commit"
hash="$(git rev-parse --short HEAD)"
prevenir "Constats internes automatiques à relire avant publication (site public) : branche $BRANCHE, commit $hash, worktree $WT. $resume. Pas de push ; fusion et push à ton OK."
echo "reglages-pont : branche $BRANCHE, commit $hash. $resume"
exit "$code"
