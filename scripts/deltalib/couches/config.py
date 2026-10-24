"""Configuration du composant delta-ia d'une instance (conception §2.1, §5) : un seul fichier de bootstrap neutre.

`bootstrap.json` (à côté de ce module) porte les valeurs par défaut : mode `lecteur`, langue commune `en`, adresses du
site (et ses anciennes adresses), de la route commune versionnée, de l'ancienne route des données et du MCP public, seuils
de fraîcheur, réglages de production. C'est la seule source des adresses publiques (L3) : `scripts/urls.py` en écrit les
copies lues par le site (`docs/assets/config.js`) et par le MCP (`mcp/lib/config.js`). Une instance peut les
remplacer dans `<configuration>/delta-ia/config.json` (écrit par l'installateur) ; une clé inconnue est refusée. Seule
une configuration locale `mode: producteur` permet de publier, hors de l'installation historique, productrice par
construction (`couches.py publier`, `commun_auto.py`) : le lecteur n'a aucune capacité de publication.
"""

from __future__ import annotations

import json
from pathlib import Path

from .racines import Racines

BOOTSTRAP = Path(__file__).with_name("bootstrap.json")
MODES = ("lecteur", "producteur")
LANGUES = ("en", "fr")


class ConfigInvalide(ValueError):
    pass


def _fusion(base: dict, local: dict, ou: str) -> dict:
    sortie = dict(base)
    for cle, valeur in local.items():
        if cle not in base:
            raise ConfigInvalide(f"{ou}: clé inconnue {cle!r}")
        sortie[cle] = _fusion(base[cle], valeur, f"{ou}.{cle}") if isinstance(base[cle], dict) and isinstance(valeur, dict) else valeur
    return sortie


def charger(racines: Racines | None = None) -> dict:
    base = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    local = {}
    if racines is not None and racines.config.is_file():
        try:
            local = json.loads(racines.config.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConfigInvalide(f"config.json illisible : {e}") from e
        if not isinstance(local, dict):
            raise ConfigInvalide("config.json : objet attendu")
    conf = _fusion(base, local, "config")
    if conf["schema"] != "delta.config" or conf["schema_version"] != 1:
        raise ConfigInvalide("config : delta.config v1 attendu")
    if conf["mode"] not in MODES:
        raise ConfigInvalide(f"config : mode parmi {MODES}")
    if conf["langue_commune_defaut"] not in LANGUES or conf["langue_utilisateur"] not in (None, *LANGUES):
        raise ConfigInvalide(f"config : langues parmi {LANGUES}")
    for cle in ("site_public_url", "reference_base_url", "donnees_compat_url", "mcp_public_url"):
        if not str(conf[cle]).startswith("https://"):
            raise ConfigInvalide(f"config : {cle} en https attendu")
    anciennes = conf["site_anciennes_urls"]
    if not isinstance(anciennes, list) or not all(isinstance(u, str) and u.startswith("https://") for u in anciennes):
        raise ConfigInvalide("config : site_anciennes_urls, liste d'adresses https attendue")
    return conf


def origine(url: str) -> str:
    """`https://hote[:port]` d'une adresse, sans chemin : forme des origines CORS."""
    from urllib.parse import urlsplit
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def origines_site(conf: dict | None = None) -> tuple[str, ...]:
    """Origines du site public, l'actuelle puis les anciennes adresses qui redirigent (relais, contrôles d'origine)."""
    conf = conf or charger()
    vues = []
    for url in (conf["site_public_url"], *conf["site_anciennes_urls"]):
        o = origine(url)
        if o not in vues:
            vues.append(o)
    return tuple(vues)
