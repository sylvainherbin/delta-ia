"""Bibliothèque de lecture des deux couches (conception §4.1) : génération commune active et magasin personnel local.

Le lecteur n'écrit rien et n'appelle aucun modèle. Chaque bloc porte sa couche, ses dates et sa validité : une réponse
composée n'est pas étiquetée « commun » à sa racine. Sans magasin personnel (instance neuve, profil absent), le bloc
personnel dit `non_personnalise`, jamais un avis de repli. Sans génération commune valide, l'indisponibilité est explicite.
Le mode `personnel=False` est celui d'un serveur public : la racine personnelle n'est jamais ouverte.

Lot L2 : fraîcheur du commun (vérification du miroir et publication, ou dernier jour des données chez le producteur),
dernière erreur de synchronisation, texte d'une fiche dans la langue demandée avec repli anglais annoncé ; un avis importé
devient `a_revoir` quand le commun est très ancien.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from . import schemas
from .publication import chemin_synchro, fraicheur
from .racines import Racines
from .sentinelles import Detecteur
from .stockage import sha256_fichier
from ..kb.catalogue import normaliser_nom


class Lecteur:
    def __init__(self, racines: Racines, personnel: bool = True, detecteur: Detecteur | None = None, langue: str = "en",
                 maintenant: datetime | None = None, seuils: dict | None = None):
        self.racines, self.langue = racines, langue
        self.maintenant = maintenant or datetime.now(timezone.utc)
        self.seuils = seuils or {"ancienne_h": 24, "tres_ancienne_j": 7}
        self.publie_le = self.verifie_le = self.fraicheur = self.erreur_synchro = None
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
        self.publie_le = actif.get("publie_le") if actif.get("origine") == "synchro" else self.manifest.get("publie_le")
        try:
            synchro = json.loads(chemin_synchro(self.racines).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            synchro = {}
        if actif.get("origine") == "synchro" and isinstance(synchro, dict) and not schemas.valider_synchro(synchro):
            self.verifie_le, self.erreur_synchro = synchro.get("verifie_le"), synchro.get("erreur")
        self.fraicheur = fraicheur(self.maintenant, self.verifie_le, self.publie_le, self.manifest.get("donnees_du"),
                                   self.seuils["ancienne_h"], self.seuils["tres_ancienne_j"])

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
        bloc = {"couche": "commun", "statut": "disponible", "generation": self.generation, "publie_le": self.publie_le,
                "donnees_du": self.manifest.get("donnees_du"), "source_verifiee_le": fiche.get("verifie_le"),
                "verifie_le": self.verifie_le, "langue": self.langue, "fraicheur": self.fraicheur, "fiche": fiche}
        if self.erreur_synchro:
            bloc["derniere_erreur_synchro"] = self.erreur_synchro
        if "textes" in fiche:
            bloc["textes"] = {champ: self.texte(fiche, champ) for champ in fiche["textes"]}
        return bloc

    def texte(self, fiche: dict, champ: str) -> dict:
        """Texte d'un champ dans la langue du lecteur ; à défaut, l'anglais avec `repli: true` (jamais un texte de l'avis)."""
        langues = fiche.get("textes", {}).get(champ, {})
        choisi = langues.get(self.langue)
        if choisi is not None:
            return {"langue": self.langue, "texte": choisi["texte"], "statut": choisi["statut"], "repli": False}
        en = langues.get("en")
        return {"langue": "en", "texte": en["texte"] if en else None, "statut": en["statut"] if en else None,
                "repli": self.langue != "en"}

    def bloc_personnel(self, identite: str) -> dict:
        if self.personnel_statut != "disponible":
            return {"couche": "personnel", "statut": "non_personnalise", "magasin": self.personnel_statut, "avis": None}
        o = self.objets.get(identite)
        if o is None:
            return {"couche": "personnel", "statut": "non_personnalise", "magasin": "disponible", "avis": None}
        fiche = self.fiches.get(identite)
        statut, motif = o["statut"], None
        # mêmes règles que LecteurLocal.blocPersonnel (mcp/lib/local.js), dans le même ordre
        if self.commun_statut != "disponible" and statut == "importe":
            statut, motif = "a_revoir", "commun_indisponible"  # aucune compatibilité actuelle établie sans commun
        elif fiche is not None and o["commun_empreinte"] not in (None, fiche["empreinte"]):
            statut, motif = "a_revoir", "commun_modifie"  # le fait commun a changé depuis l'avis
        elif fiche is None and statut == "importe" and o["commun_empreinte"]:
            statut, motif = "reference_introuvable", "fiche_absente"
        elif statut == "importe" and self.fraicheur == "tres_ancienne":
            statut, motif = "a_revoir", "commun_tres_ancien"  # la compatibilité actuelle n'est plus établie par un commun récent
        avis = {"statut_usage": o["statut_usage"], "recommandation": o["recommandation"]}
        courant = statut == "importe"
        # comme LecteurLocal.blocPersonnel : un avis à revoir reste lisible comme précédent, jamais comme conseil courant
        return {"couche": "personnel", "statut": statut, **({"motif": motif} if motif else {}),
                "observe_le": o["observe_le"], "evalue_le": o["evalue_le"],
                "avis": avis if courant else None, **({} if courant else {"avis_precedent": avis}),
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
                           "motif": self.motif, "fraicheur": self.fraicheur, "publie_le": self.publie_le,
                           "verifie_le": self.verifie_le}, "total": len(tous), "affichees": len(lignes), "resultats": lignes}
