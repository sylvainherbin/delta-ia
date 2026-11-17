"""Prélecture des arbres d'entrée : aucun lien symbolique, même dans un parent."""
from pathlib import Path


def refuser_liens(racine: Path, chemin: Path) -> None:
    racine, chemin = racine.absolute(), chemin.absolute()  # jamais resolve(), qui suivrait le lien
    rel = chemin.relative_to(racine)
    courant = racine
    for composant in ("", *rel.parts):
        courant = courant / composant
        if composant == ".." or courant.is_symlink():
            raise ValueError(f"LIEN_SYMBOLIQUE_REFUSE : {courant.relative_to(racine)}")
    if chemin.is_dir():
        for enfant in sorted(chemin.iterdir()):
            refuser_liens(racine, enfant)
