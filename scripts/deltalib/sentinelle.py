"""Sentinelle `.gitattributes` du pilote Codex : le seul fichier non suivi que les contrôles d'arbre tolèrent.

Pour lancer un pilote Codex dans un bac à sable, Delta crée à la racine du dépôt de travail un `.gitattributes` vide en
lecture seule : point de montage qui empêche la commande lancée d'écrire un vrai `.gitattributes`. Non suivi, ce fichier
faisait refuser l'arbre par les contrôles d'état (incident du 20/11/2026, orchestrateur, code 126).

Même critère que discipline (`delta.operer.restes_bac`, `est_ligne_reste` pour `.gitattributes`), resserré : chemin exactement
`.gitattributes` à la racine, non suivi, fichier régulier (`lstat`, jamais un lien), taille 0, mode exactement 0444.
Tout autre état à ce chemin (contenu, autre mode, lien, suivi, modifié) reste un changement à déclarer ; `sous/.gitattributes`
aussi. Aucun import de discipline : la chaîne de nuit ne dépend d'aucun autre dépôt (un test épingle l'accord des deux)."""

from __future__ import annotations

import stat
from pathlib import Path

NOM = ".gitattributes"
MODE = 0o444


def est_sentinelle_codex(racine: Path | str, ligne: str) -> bool:
    """`ligne` : entrée de `git status --porcelain=v1` (`?? .gitattributes`, avec ou sans `-z`) ; pour une liste de
    `git ls-files --others`, passer `"?? " + chemin`. Seule une entrée non suivie (`?? `) peut être la sentinelle :
    un fichier suivi ou modifié (` M `, `A `…) n'est jamais toléré. `ligne` est brute : aucun `strip()` en amont.
    `racine` est le haut du dépôt (les chemins de git sont relatifs à lui) : sans `racine/.git`, refus."""
    if ligne != "?? " + NOM:
        return False
    racine = Path(racine)
    if not (racine / ".git").exists():
        return False
    try:
        info = (racine / NOM).lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size == 0 and stat.S_IMODE(info.st_mode) == MODE
