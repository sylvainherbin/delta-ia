"""Instantané de l'instance pour la vue « Utile pour mon ORQYRA » (lot 2) : profil d'hôte de P1 et réglages courants.

La vue dit pourquoi une fiche commune concerne cette instance ; elle ne décide rien. Elle s'appuie sur trois faits de
l'instance, chacun avec sa source :
- le profil d'instance K1 (`Racines.profil`) et, en version 2, son profil d'hôte `delta.hote` (P1, discipline
  `portabilite/profil_hote.py`) : identité de l'hôte, socle commun et couches personnelles déclarées (identifiant et
  libellé seulement : ressources, migrations et lectures SSH ne servent pas à la vue et ne sont pas recopiés), noms des
  exécutables déclarés (sans leurs chemins) ;
- les réglages courants d'OPÉRER : table `operer.reglage_missions` (modèle et effort par nature et taille) de la politique
  de l'instance, résolue comme OPÉRER (`OPERER_POLICY_FILE`, puis `OPERER_CONFIG_DIR/politique.json`, puis la
  configuration de l'instance K1, puis, sur l'installation historique, `config/instance-policy.json` du dépôt de la
  commande `operer`). Chaque case est rattachée au couple commun par la règle du bilan (`bilan.rattacher`) : une case sans
  fiche reste non rattachée, avec son motif ;
- les versions installées, déjà dans le magasin (objets `version:*`).

Rangé dans `personnel/instance.json` par `couches.py personnel rafraichir`, sous le même verrou que le bilan : aucun
collecteur de plus, aucun appel de commande, aucun appel de modèle. Le lecteur local (mcp/lib/local.js) ne fait que le lire.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from uuid import UUID

from . import schemas
from .bilan import modeles_communs, rattacher
from .racines import Racines
from .stockage import empreinte

SOCLE = ("moteur", "operer", "files", "tic", "pilote")
FICHIER = "instance.json"
RE_NOM = re.compile(r"[a-z][a-z0-9-]{0,63}")


class PolitiqueIllisible(RuntimeError):
    """Politique d'instance présente mais illisible : source en échec, le dernier instantané reste."""


def _hote(h) -> dict:
    """Résumé d'un profil d'hôte `delta.hote` v1/v2 ; ValueError s'il est hors contrat (mêmes refus de forme que P1)."""
    if not isinstance(h, dict) or h.get("schema") != "delta.hote" or type(h.get("version")) is not int \
            or h["version"] not in (1, 2):
        raise ValueError("profil d'hôte : delta.hote version 1 ou 2 attendu")
    if not isinstance(h.get("id"), str) or not RE_NOM.fullmatch(h["id"]):
        raise ValueError("profil d'hôte : identifiant invalide")
    if h.get("socle") != list(SOCLE):
        raise ValueError("profil d'hôte : socle commun moteur, operer, files, tic, pilote attendu")
    couches = h.get("couches_personnelles")
    if not isinstance(couches, list):
        raise ValueError("profil d'hôte : liste de couches attendue")
    vues = []
    for c in couches:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not RE_NOM.fullmatch(c["id"]) \
                or not isinstance(c.get("libelle"), str) or not c["libelle"].strip():
            raise ValueError("profil d'hôte : couche sans identifiant ou libellé valide")
        vues.append({"id": c["id"], "libelle": c["libelle"]})
    return {"id": h["id"], "version": h["version"], "socle": list(SOCLE), "couches_personnelles": vues}


def lire_profil(chemin: Path | None) -> dict:
    """Résumé du profil d'instance : `absent` (installation historique, ou aucun profil installé), `invalide` (avec son
    motif) ou `present`. Jamais de chemin ni de ressource personnelle recopiés."""
    if chemin is None:
        return {"statut": "absent", "motif": "aucun_profil"}
    try:
        d = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"statut": "absent", "motif": "profil_introuvable"}
    except (OSError, UnicodeError, ValueError):
        return {"statut": "invalide", "motif": "profil_illisible"}
    if not isinstance(d, dict) or d.get("schema") != "delta.instance" or d.get("version") not in (1, 2):
        return {"statut": "invalide", "motif": "profil_forme"}
    hote = None
    if d["version"] == 2:
        try:
            hote = _hote(d.get("hote"))
            if str(UUID(d.get("installation"))) != d.get("installation"):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            return {"statut": "invalide", "motif": "hote_forme"}
    executables = d.get("executables") if isinstance(d.get("executables"), dict) else {}
    return {"statut": "present", "identite": d.get("identite"), "version": d["version"], "mode": d.get("mode"),
            "hote": hote, "executables": sorted(k for k in executables if isinstance(k, str))}


def chemin_politique(racines: Racines, env: dict | None = None, explicite: Path | None = None,
                     operer: str | None = None) -> tuple[Path | None, str | None]:
    """(fichier, origine) de la politique d'instance, dans l'ordre d'OPÉRER (discipline `shared/configuration.py`)."""
    env = dict(os.environ) if env is None else env
    if explicite is not None:
        return Path(explicite), "option"
    if env.get("OPERER_POLICY_FILE"):
        return Path(env["OPERER_POLICY_FILE"]).expanduser(), "OPERER_POLICY_FILE"
    if env.get("OPERER_CONFIG_DIR"):
        return Path(env["OPERER_CONFIG_DIR"]).expanduser() / "politique.json", "OPERER_CONFIG_DIR"
    if racines.origine == "instance":
        return racines.configuration / "politique.json", "instance"
    if racines.origine == "historique":
        commande = operer if operer is not None else shutil.which("operer")
        if commande:
            # bin/operer du dépôt discipline : la politique historique est `config/instance-policy.json` de ce dépôt
            return Path(commande).resolve().parent.parent / "config" / "instance-policy.json", "operer"
    return None, None


def lire_reglages(racines: Racines, chemin: Path | None, origine: str | None) -> dict:
    """Cases de la table `operer.reglage_missions`, rattachées aux couples communs ; `absent` sans politique ni table."""
    if chemin is None:
        return {"statut": "absent", "motif": "politique_non_designee", "origine": None, "cases": []}
    try:
        politique = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # OPÉRER lit alors une politique neutre, sans table : aucun réglage courant
        return {"statut": "absent", "motif": "politique_absente", "origine": origine, "cases": []}
    except (OSError, UnicodeError, ValueError) as e:
        raise PolitiqueIllisible(f"politique d'instance illisible ({origine}) : {type(e).__name__}") from e
    table = ((politique.get("operer") or {}).get("reglage_missions") if isinstance(politique, dict) else None) or {}
    if not isinstance(table, dict) or not table:
        return {"statut": "absent", "motif": "aucune_table", "origine": origine, "cases": []}
    generation, doc = modeles_communs(racines)
    cases = []
    for famille, f in sorted(table.items()):
        for nature, tailles in sorted(((f or {}).get("table") or {}).items()):
            for taille, c in sorted((tailles or {}).items()):
                if not isinstance(c, dict):
                    continue
                case = {"famille": famille, "nature": nature, "taille": taille, "modele": c.get("modele"),
                        "effort": c.get("effort"), "motif_reglage": c.get("motif")}
                couple, motif = rattacher({"modele": case["modele"], "effort": case["effort"], "executant": famille}, doc)
                case.update(couple=couple["identite"] if couple else None,
                            couple_empreinte=couple.get("empreinte") if couple else None,
                            non_rattache=motif)
                cases.append(case)
    return {"statut": "disponible", "motif": None, "origine": origine, "commun_generation": generation,
            "sha256": empreinte(table), "cases": cases}


def instantane(racines: Racines, lu_le: str, politique: Path | None = None, env: dict | None = None,
               operer: str | None = None) -> dict:
    chemin, origine = chemin_politique(racines, env, politique, operer)
    contenu = {"profil": lire_profil(racines.profil), "reglages": lire_reglages(racines, chemin, origine)}
    return {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "instance", "lu_le": lu_le,
            **contenu, "sha256": empreinte(contenu)}
