"""Bibliothèque de lecture des deux couches (conception §4.1) : génération commune active et magasin personnel local.

Le lecteur n'écrit rien et n'appelle aucun modèle. Chaque bloc porte sa couche, ses dates et sa validité : une réponse
composée n'est pas étiquetée « commun » à sa racine. Sans magasin personnel (instance neuve, profil absent), le bloc
personnel dit `non_personnalise`, jamais un avis de repli. Sans génération commune valide, l'indisponibilité est explicite.
Le mode `personnel=False` est celui d'un serveur public : la racine personnelle n'est jamais ouverte.
"""

from __future__ import annotations

import json

from . import schemas
from .racines import Racines
from .sentinelles import Detecteur
from .stockage import sha256_fichier
from ..kb.catalogue import normaliser_nom


class Lecteur:
    def __init__(self, racines: Racines, personnel: bool = True, detecteur: Detecteur | None = None):
        self.racines = racines
        self.commun_statut, self.motif, self.generation, self.manifest = "indisponible", None, None, None
        self.fiches: dict[str, dict] = {}
        self.noms: dict[str, list[str]] = {}
        self.objets: dict[str, dict] | None = None
        self.personnel_statut = "desactive" if not personnel else "absent"
        self._charger_commun(detecteur or Detecteur())
        if personnel:
            self._charger_personnel()

    def _charger_commun(self, detecteur: Detecteur) -> None:
        try:
            actif = json.loads(self.racines.commun_actif.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.motif = "aucune génération commune active"
            return
        if not isinstance(actif, dict) or actif.get("schema") != schemas.COMMUN or actif.get("vue") != "actif":
            self.motif = "pointeur de génération illisible"
            return
        if actif.get("schema_version") != schemas.VERSION:
            self.motif = f"version {actif.get('schema_version')!r} du commun non prise en charge"
            return
        generation = actif.get("generation")
        if not isinstance(generation, str) or not schemas.RE_GENERATION.fullmatch(generation):
            self.motif = "pointeur de génération invalide"
            return
        dossier = self.racines.commun / generation
        if not (dossier / "manifest.json").is_file() or sha256_fichier(dossier / "manifest.json") != actif.get("manifest_sha256"):
            self.motif = f"manifeste de {generation} absent ou différent du pointeur"
            return
        erreurs = schemas.valider_generation(dossier, detecteur)
        if erreurs:
            self.motif = f"génération {generation} invalide : {erreurs[0]}"
            return
        self.manifest = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
        for f in self.manifest["fichiers"]:
            doc = json.loads((dossier / f["chemin"]).read_text(encoding="utf-8"))
            if doc["famille"] == "noms":
                self.noms = doc["noms"]
            for fiche in doc.get("entrees", []):
                self.fiches[fiche["identite"]] = fiche
            for fiche in (doc.get("modeles") or {}).values():
                self.fiches[fiche["identite"]] = fiche
        self.generation, self.commun_statut = generation, "disponible"

    def _charger_personnel(self) -> None:
        chemin = self.racines.personnel / "overlay.json"
        try:
            doc = json.loads(chemin.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return  # instance sans observations : statut `absent`
        except (OSError, ValueError):
            self.personnel_statut = "illisible"
            return
        if schemas.valider_personnel(doc, "overlay", "overlay.json"):
            self.personnel_statut = "invalide"
            return
        self.objets, self.personnel_statut = doc["objets"], "disponible"

    # --- résolution ---
    def resoudre(self, ref: str) -> list[str]:
        """Identités désignées par `ref` : identité exacte, id de fiche, puis nom exact (`/add-dir`, `--model`)."""
        if ref in self.fiches or (self.objets and ref in self.objets):
            return [ref]
        par_id = sorted(i for i in self.fiches if schemas.id_brut(i) == ref)
        if par_id:
            return par_id
        ids = self.noms.get(normaliser_nom(ref), [])
        return sorted(i for i in self.fiches if schemas.id_brut(i) in ids)

    def bloc_commun(self, identite: str) -> dict:
        if self.commun_statut != "disponible":
            return {"couche": "commun", "statut": "indisponible", "motif": self.motif}
        fiche = self.fiches.get(identite)
        if fiche is None:
            return {"couche": "commun", "statut": "introuvable", "generation": self.generation}
        return {"couche": "commun", "statut": "disponible", "generation": self.generation,
                "publie_le": self.manifest.get("publie_le"), "donnees_du": self.manifest.get("donnees_du"),
                "source_verifiee_le": fiche.get("verifie_le"), "verifie_le": None, "langue": None, "fraicheur": None,
                "fiche": fiche}

    def bloc_personnel(self, identite: str) -> dict:
        if self.personnel_statut != "disponible":
            return {"couche": "personnel", "statut": "non_personnalise", "magasin": self.personnel_statut, "avis": None}
        o = self.objets.get(identite)
        if o is None:
            return {"couche": "personnel", "statut": "non_personnalise", "magasin": "disponible", "avis": None}
        fiche = self.fiches.get(identite)
        statut = o["statut"]
        if fiche is not None and o["commun_empreinte"] not in (None, fiche["empreinte"]):
            statut = "a_revoir"  # le fait commun a changé depuis l'avis
        elif fiche is None and self.commun_statut == "disponible" and statut == "importe" and o["commun_empreinte"]:
            statut = "reference_introuvable"
        return {"couche": "personnel", "statut": statut, "observe_le": o["observe_le"], "evalue_le": o["evalue_le"],
                "avis": {"statut_usage": o["statut_usage"], "recommandation": o["recommandation"]},
                "essais": o["essais"], "reevaluations": o["reevaluations"], "rejugements": o["rejugements"],
                "historique_importe": o["historique_importe"]}

    def fiche(self, ref: str) -> dict:
        identites = self.resoudre(ref)
        if len(identites) != 1:
            return {"reference": ref, "statut": "ambigu" if identites else "introuvable", "identites": identites,
                    "commun": self.bloc_commun(ref) if not identites else None}
        identite = identites[0]
        reponse = {"identite": identite, "commun": self.bloc_commun(identite)}
        if self.personnel_statut != "desactive":
            reponse["personnel"] = self.bloc_personnel(identite)
        return reponse

    def chercher(self, texte: str, limite: int = 20) -> dict:
        """Recherche exacte (identité, id, nom) avant plein texte sur nom, usage et description d'origine ; une ligne par
        identité, avec la présence d'un avis local quand le magasin personnel est ouvert."""
        exacts = self.resoudre(texte)
        cle = texte.casefold()
        pleins = [i for i, f in self.fiches.items() if i not in exacts and any(
            isinstance(f.get(c), str) and cle in f[c].casefold() for c in ("nom", "usage", "description_source", "id"))]
        tous = exacts + sorted(pleins)
        lignes = []
        for i in tous[:limite]:
            f = self.fiches.get(i, {})
            ligne = {"identite": i, "nom": f.get("nom"), "exact": i in exacts}
            if self.personnel_statut != "desactive":
                ligne["avis_local"] = bool(self.objets and i in self.objets)
            lignes.append(ligne)
        return {"commun": {"couche": "commun", "statut": self.commun_statut, "generation": self.generation,
                           "motif": self.motif}, "total": len(tous), "affichees": len(lignes), "resultats": lignes}
