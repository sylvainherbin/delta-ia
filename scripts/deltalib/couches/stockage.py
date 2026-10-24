"""Écritures des magasins (conception §2.1) : JSON canonique, remplacement atomique, droits privés, verrou par magasin."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

DROITS_DOSSIER, DROITS_FICHIER = 0o700, 0o600


class MagasinOccupe(RuntimeError):
    """Un autre écrivain tient le verrou du magasin."""


def canonique(valeur) -> bytes:
    """JSON aux clés triées, sans espace : base des empreintes factuelles et des générations."""
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def empreinte(valeur) -> str:
    return hashlib.sha256(canonique(valeur)).hexdigest()


def sha256_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def serialiser(doc) -> bytes:
    """Forme écrite sur disque : lisible, déterministe (même contenu, mêmes octets)."""
    return (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def dossier_prive(chemin: Path) -> Path:
    chemin.mkdir(parents=True, exist_ok=True, mode=DROITS_DOSSIER)
    os.chmod(chemin, DROITS_DOSSIER)
    return chemin


def ecrire(chemin: Path, doc) -> bool:
    """Remplacement atomique par fichier voisin, droits 0600 ; rien n'est réécrit si les octets sont déjà identiques.
    Rend True si le fichier a changé."""
    contenu = serialiser(doc)
    try:
        if chemin.read_bytes() == contenu:
            return False
    except OSError:
        pass
    dossier_prive(chemin.parent)
    tmp = chemin.with_name(f".{chemin.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, DROITS_FICHIER)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenu)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, chemin)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


def ecrire_public(chemin: Path, doc) -> bool:
    """Comme `ecrire`, pour un fichier destiné à la publication (route versionnée, cache de traductions suivi) : droits
    0644, dossier parent laissé tel quel. Rend True si le fichier a changé."""
    contenu = serialiser(doc)
    return ecrire_octets_public(chemin, contenu)


def ecrire_octets_public(chemin: Path, contenu: bytes) -> bool:
    try:
        if chemin.read_bytes() == contenu:
            return False
    except OSError:
        pass
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(f".{chemin.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(contenu)
        os.chmod(tmp, 0o644)
        os.replace(tmp, chemin)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


@contextmanager
def verrou(dossier: Path, nom: str):
    """Verrou exclusif non bloquant `<dossier>/<nom>.lock` : un seul écrivain par magasin."""
    dossier_prive(dossier)
    fd = os.open(dossier / f"{nom}.lock", os.O_RDWR | os.O_CREAT, DROITS_FICHIER)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise MagasinOccupe(f"magasin {nom} occupé par un autre écrivain") from e
        yield
    finally:
        os.close(fd)
