"""Données personnelles dans un champ commun : défense en profondeur de la projection (conception §3.1).

Un champ C est extrait des sources publiques par le code ; s'il contient malgré tout un secret, une trace OPÉRER, un
chemin de dossier personnel, un courriel réel ou un terme propre à l'instance, il est mis en attente au lieu d'être
exporté. Les termes de l'instance sont lus à l'exécution (HOME, courriel git, projets de CONTEXTE.md) et ne sont jamais
écrits dans un fichier suivi. Seuls les noms de projet composés (`trading-sim`) servent de terme : un nom d'un seul mot
courant (« marketing ») apparaît dans la documentation publique et bloquerait des fiches sans raison.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..confidentialite import RE_ORGANISATION_PRIVEE, RE_SECRETS

RE_DOSSIER_PERSONNEL = re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\+Users\\+)([A-Za-z0-9_][\w.-]*)")
# Noms d'exemple de la documentation publique (`/Users/me/.codex`, `/Users/my-project/src`) : pas le dossier d'une personne.
RE_NOM_EXEMPLE = re.compile(r"(?:me|you|user|username|name|example|alice|bob|jane|john|runner|(?:my|your)-[\w.-]*)", re.I)
# Domaines réservés à la documentation (RFC 2606, RFC 6761) : exemples publics, pas des courriels de personnes.
RE_COURRIEL = re.compile(r"[\w.+-]+@(?!(?:[\w-]+\.)*(?:example\.(?:com|org|net)|example|test|invalid|localhost)\b)"
                         r"[\w-]+(?:\.[\w-]+)+")
# Comptes système ou d'intégration continue : leur nom est un mot courant de la documentation, pas une personne.
COMPTES_GENERIQUES = {"root", "admin", "ubuntu", "debian", "runner", "vscode", "codespace", "node", "app", "build", "ci"}
RE_ORGANISATION = [re.compile(m.pattern.decode("ascii")) for m in RE_ORGANISATION_PRIVEE]


def termes_instance(depot: Path | None, home: Path | None = None, contexte: Path | None = None) -> list[str]:
    """Termes propres à l'instance qui lit les données : nom du HOME, courriel git du dépôt, projets composés de CONTEXTE.md.
    Un fichier absent n'est pas une erreur (profil absent accepté)."""
    termes: set[str] = set()
    home = home or Path.home()
    if len(home.name) >= 3 and home.name.lower() not in COMPTES_GENERIQUES and not RE_NOM_EXEMPLE.fullmatch(home.name):
        termes.add(home.name)
    if depot is not None:
        try:
            courriel = subprocess.run(["git", "-C", str(depot), "config", "user.email"], capture_output=True,
                                      text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            courriel = ""
        if courriel:
            termes.add(courriel)
    contexte = contexte if contexte is not None else (depot / "CONTEXTE.md" if depot else None)
    if contexte is not None and contexte.is_file():
        from ..contexte import ContexteInvalide, analyser
        try:
            sections = analyser(contexte.read_text(encoding="utf-8"))[0]
        except (ContexteInvalide, OSError, UnicodeDecodeError):
            sections = {}
        termes.update(cle[len("projet."):] for cle, s in sections.items()
                      if s.get("niveau") == 3 and cle.startswith("projet.") and "-" in cle[len("projet."):])
    return sorted(termes)


class Detecteur:
    def __init__(self, termes: list[str] | tuple[str, ...] = ()):
        self.termes = [re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", re.I) for t in termes if t]

    def motif(self, valeur) -> str | None:
        """Nature de la première donnée personnelle trouvée dans les textes de `valeur` (sans la recopier), ou None."""
        for texte in _textes(valeur):
            for regex, libelle in RE_SECRETS:
                if regex.search(texte):
                    return f"secret ({libelle})"
            if any(r.search(texte) for r in RE_ORGANISATION):
                return "trace OPÉRER"
            if any(not RE_NOM_EXEMPLE.fullmatch(m.group(1)) for m in RE_DOSSIER_PERSONNEL.finditer(texte)):
                return "chemin personnel"
            if RE_COURRIEL.search(texte):
                return "courriel"
            if any(r.search(texte) for r in self.termes):
                return "terme de l'instance"
        return None


def _textes(valeur):
    if isinstance(valeur, str):
        yield valeur
    elif isinstance(valeur, dict):
        for k, v in valeur.items():
            yield str(k)
            yield from _textes(v)
    elif isinstance(valeur, list):
        for v in valeur:
            yield from _textes(v)
