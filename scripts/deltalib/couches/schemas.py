"""Contrats v1 des deux couches (conception §2.2, §2.3) : `delta.commun`, `delta.personnel`, `delta.manifest`.

Schémas fermés : une clé non prévue est refusée. La validation d'un document commun ne fait pas confiance au producteur :
chaque fiche est reprojetée sur la table de classement de sa famille source (`classement`), et tout chemin qui n'y est pas C
(P, S, inconnu, mis en attente en L1) est une erreur, comme toute donnée personnelle détectée dans un texte.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from . import classement as cl
from .sentinelles import Detecteur
from .stockage import empreinte, sha256_fichier

COMMUN, PERSONNEL, MANIFEST = "delta.commun", "delta.personnel", "delta.manifest"
VERSION = 1
STATUTS_OBJET = ("non_personnalise", "importe", "a_revoir", "reference_retiree", "reference_introuvable")
RE_GENERATION = re.compile(r"g-[0-9a-f]{16}")
RE_IDENTITE = re.compile(r"(kb:(claude|openai):|kb:delta:(methodes|modeles):|veille:(claude|openai|actu):|version:)\S+")
# Préfixes d'identité, du plus long au plus court : l'id brut qui suit peut contenir « : » (veille dont l'id est une URL).
PREFIXES_IDENTITE = ("kb:delta:methodes:", "kb:delta:modeles:", "kb:delta:forfaits:", "kb:introuvable:", "kb:claude:",
                     "kb:openai:", "veille:claude:", "veille:openai:", "veille:actu:", "version:", "fichier:")
RE_SHA256 = re.compile(r"[0-9a-f]{64}")
TAILLE_MAX = 64 << 20  # par fichier d'une génération

# Racine de chaque famille commune : clés permises, et famille source dont les fiches sont reprojetées.
RACINES_COMMUN = {
    "kb": {"perimetre", "categorie", "maj_le", "total", "entrees"},
    "methodes": {"categorie", "maj_le", "origine", "total", "entrees"},
    "modeles": {"categorie", "date_releve", "maj_le", "origine", "version_source", "total", "total_modeles", "entrees",
                "modeles"},
    "veille": {"perimetre", "total", "entrees"},
    "versions": {"total", "entrees"},
    "noms": {"noms"},
}
CLES_MANIFEST = {"schema", "schema_version", "generation", "publie_le", "donnees_du", "schemas_requis", "langues",
                 "couverture", "fichiers"}
CLES_ACTIF = {"schema", "schema_version", "vue", "generation", "manifest_sha256", "precedente"}
CLES_OBJET = {"objet", "commun_empreinte", "statut", "langue", "observe_le", "evalue_le", "statut_usage",
              "recommandation", "pour_toi", "action", "exemple_local", "essais", "reevaluations", "rejugements",
              "historique_importe"}
CLES_PERSONNEL = {"overlay": {"schema", "schema_version", "vue", "commun_generation", "profil_empreinte", "objets"},
                  "en_attente": {"schema", "schema_version", "vue", "commun_generation", "objets", "refus"},
                  "import": {"schema", "schema_version", "vue", "commun_generation", "entrees", "comptes"}}


def id_brut(identite: str) -> str:
    """Id d'origine porté par une identité (`veille:actu:https://…` → `https://…`) ; l'identité entière sinon."""
    for prefixe in PREFIXES_IDENTITE:
        if identite.startswith(prefixe):
            return identite[len(prefixe):]
    return identite


def _fermer(doc, permises: set[str], ou: str, erreurs: list[str]) -> bool:
    if not isinstance(doc, dict):
        erreurs.append(f"{ou}: objet attendu")
        return False
    inconnues = sorted(set(doc) - permises)
    if inconnues:
        erreurs.append(f"{ou}: clés non prévues {inconnues}")
    return True


def _en_tete(doc, schema: str, ou: str, erreurs: list[str]) -> bool:
    if not isinstance(doc, dict) or doc.get("schema") != schema:
        erreurs.append(f"{ou}: schema {schema} attendu")
        return False
    if doc.get("schema_version") != VERSION:
        erreurs.append(f"{ou}: version {doc.get('schema_version')!r} non prise en charge (version {VERSION} attendue)")
        return False
    return True


def _hors_commun(famille_source: str, enveloppe) -> list[str]:
    """Chemins normalisés de l'enveloppe reprojetée qui ne sont pas C (P, S, inconnus, en attente L1)."""
    return sorted({norm for norm, _, _ in cl.feuilles(famille_source, enveloppe)
                   if cl.classer(famille_source, norm) != cl.COMMUN})


def _fiche(fiche, famille_source: str, envelopper, ou: str, erreurs: list[str], identites: set[str]) -> None:
    if not isinstance(fiche, dict):
        erreurs.append(f"{ou}: fiche objet attendue")
        return
    identite, emp = fiche.get("identite"), fiche.get("empreinte")
    contenu = {k: v for k, v in fiche.items() if k not in ("identite", "empreinte")}
    if not isinstance(identite, str) or not RE_IDENTITE.fullmatch(identite):
        erreurs.append(f"{ou}: identité invalide {identite!r}")
    elif identite in identites:
        erreurs.append(f"{ou}: identité en double {identite}")
    else:
        identites.add(identite)
    if emp != empreinte_fiche(identite, contenu):
        erreurs.append(f"{ou}: empreinte factuelle incohérente")
    hors = _hors_commun(famille_source, envelopper(contenu))
    if hors:
        erreurs.append(f"{ou}: champs non communs {hors[:5]}")


def empreinte_fiche(identite, contenu: dict) -> str:
    return empreinte({"identite": identite, **contenu})


def valider_commun(doc, ou: str, detecteur: Detecteur, identites: set[str]) -> list[str]:
    erreurs: list[str] = []
    if not _en_tete(doc, COMMUN, ou, erreurs):
        return erreurs
    famille = doc.get("famille")
    if famille not in RACINES_COMMUN:
        return [f"{ou}: famille commune inconnue {famille!r}"]
    _fermer(doc, RACINES_COMMUN[famille] | {"schema", "schema_version", "famille"}, ou, erreurs)
    nature = detecteur.motif(doc)
    if nature:
        erreurs.append(f"{ou}: donnée personnelle détectée ({nature})")
    entrees = doc.get("entrees", [])
    if famille != "noms" and not isinstance(entrees, list):
        return erreurs + [f"{ou}: `entrees` liste attendue"]
    if famille != "noms" and doc.get("total") != len(entrees):
        erreurs.append(f"{ou}: total {doc.get('total')!r} ≠ {len(entrees)} entrées")
    if famille == "kb":
        racine = {k: doc[k] for k in ("perimetre", "categorie", "maj_le") if k in doc}
        hors = _hors_commun("kb_catalogue", racine)
        if hors:
            erreurs.append(f"{ou}: champs non communs {hors}")
        for i, f in enumerate(entrees):
            _fiche(f, "kb_catalogue", lambda c: {"entrees": [c]}, f"{ou} entrees[{i}]", erreurs, identites)
    elif famille == "methodes":
        for i, f in enumerate(entrees):
            _fiche(f, "methodes", lambda c: {"entrees": [c]}, f"{ou} entrees[{i}]", erreurs, identites)
    elif famille == "modeles":
        for i, f in enumerate(entrees):
            _fiche(f, "modeles", lambda c: {"entrees": [c]}, f"{ou} entrees[{i}]", erreurs, identites)
        modeles = doc.get("modeles", {})
        if not isinstance(modeles, dict):
            erreurs.append(f"{ou}: `modeles` objet attendu")
            modeles = {}
        if doc.get("total_modeles") != len(modeles):
            erreurs.append(f"{ou}: total_modeles {doc.get('total_modeles')!r} ≠ {len(modeles)}")
        for cle, f in modeles.items():
            _fiche(f, "modeles", lambda c, cle=cle: {"modeles": {cle: c}}, f"{ou} modeles.{cle}", erreurs, identites)
    elif famille == "veille":
        for i, f in enumerate(entrees):
            if not isinstance(f, dict):
                erreurs.append(f"{ou} entrees[{i}]: fiche objet attendue")
                continue
            pubs = f.get("publications")
            if set(f) - {"identite", "empreinte", "id", "publications"} or not isinstance(pubs, list) or not pubs:
                erreurs.append(f"{ou} entrees[{i}]: fiche de veille {{identite, empreinte, id, publications}} attendue")
                continue

            def envelopper(c):
                return [{"date": p.get("jour"), "agent": p.get("agent"), "genere_le": p.get("genere_le"),
                         "elements": [{"id": c["id"], **{k: v for k, v in p.items() if k not in ("jour", "agent", "genere_le")}}]}
                        for p in c["publications"] if isinstance(p, dict)]
            identite, contenu = f.get("identite"), {k: v for k, v in f.items() if k not in ("identite", "empreinte")}
            if not isinstance(identite, str) or not RE_IDENTITE.fullmatch(identite) or identite in identites:
                erreurs.append(f"{ou} entrees[{i}]: identité invalide ou en double {identite!r}")
            else:
                identites.add(identite)
            if f.get("empreinte") != empreinte_fiche(identite, contenu):
                erreurs.append(f"{ou} entrees[{i}]: empreinte factuelle incohérente")
            hors = sorted({h for pub in envelopper(contenu) for h in _hors_commun("quotidien", pub)})
            if hors:
                erreurs.append(f"{ou} entrees[{i}]: champs non communs {hors[:5]}")
    elif famille == "versions":
        for i, f in enumerate(entrees):
            _fiche(f, "versions", lambda c: [c], f"{ou} entrees[{i}]", erreurs, identites)
    elif famille == "noms":
        noms = doc.get("noms")
        if not isinstance(noms, dict) or not all(isinstance(v, list) and all(isinstance(x, str) for x in v)
                                                 for v in noms.values()):
            erreurs.append(f"{ou}: `noms` attendu sous forme {{nom: [id]}}")
    return erreurs


def generation_de(fichiers: list[dict]) -> str:
    return "g-" + empreinte(sorted((f["chemin"], f["sha256"]) for f in fichiers))[:16]


def valider_generation(dossier: Path, detecteur: Detecteur) -> list[str]:
    """Manifeste fermé, fichiers listés présents, réguliers, dans le dossier, aux tailles et empreintes annoncées, aucun
    fichier non listé ; chaque document commun valide et identités uniques sur toute la génération."""
    import json
    erreurs: list[str] = []
    chemin_manifest = dossier / "manifest.json"
    try:
        manifest = json.loads(chemin_manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"manifest.json illisible : {e}"]
    if not _en_tete(manifest, MANIFEST, "manifest.json", erreurs):
        return erreurs
    _fermer(manifest, CLES_MANIFEST, "manifest.json", erreurs)
    fichiers = manifest.get("fichiers")
    if not isinstance(fichiers, list) or not fichiers:
        return erreurs + ["manifest.json: `fichiers` liste non vide attendue"]
    listes: set[str] = set()
    for i, f in enumerate(fichiers):
        if not isinstance(f, dict) or set(f) != {"chemin", "taille", "sha256"}:
            erreurs.append(f"manifest.json fichiers[{i}]: {{chemin, taille, sha256}} attendu")
            continue
        rel = f["chemin"]
        pur = PurePosixPath(rel) if isinstance(rel, str) else None
        if pur is None or pur.is_absolute() or ".." in pur.parts or rel in ("", "manifest.json") or rel in listes:
            erreurs.append(f"manifest.json fichiers[{i}]: chemin refusé {rel!r}")
            continue
        listes.add(rel)
        cible = dossier / rel
        if cible.is_symlink() or not cible.is_file() or dossier.resolve() not in cible.resolve().parents:
            erreurs.append(f"{rel}: fichier absent, lien ou hors de la génération")
            continue
        taille = cible.stat().st_size
        if taille != f["taille"] or taille > TAILLE_MAX:
            erreurs.append(f"{rel}: taille {taille} ≠ {f['taille']} annoncée ou au-delà de la limite")
            continue
        if sha256_fichier(cible) != f["sha256"]:
            erreurs.append(f"{rel}: empreinte SHA-256 différente du manifeste")
    presents = {p.relative_to(dossier).as_posix() for p in dossier.rglob("*") if p.is_file() or p.is_symlink()}
    for rel in sorted(presents - listes - {"manifest.json"}):
        erreurs.append(f"{rel}: fichier non listé dans le manifeste")
    if erreurs:
        return erreurs
    if manifest.get("generation") != generation_de(fichiers) or manifest.get("generation") != dossier.name:
        erreurs.append("manifest.json: génération incohérente avec les fichiers ou le dossier")
    if manifest.get("schemas_requis") != [f"{COMMUN}@{VERSION}"]:
        erreurs.append(f"manifest.json: schemas_requis [{COMMUN}@{VERSION}] attendu")
    identites: set[str] = set()
    for rel in sorted(listes):
        try:
            doc = json.loads((dossier / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            erreurs.append(f"{rel}: illisible ({e})")
            continue
        erreurs.extend(valider_commun(doc, rel, detecteur, identites))
    return erreurs


def valider_personnel(doc, vue: str, ou: str) -> list[str]:
    erreurs: list[str] = []
    if not _en_tete(doc, PERSONNEL, ou, erreurs):
        return erreurs
    if doc.get("vue") != vue:
        return [f"{ou}: vue {vue} attendue"]
    _fermer(doc, CLES_PERSONNEL[vue], ou, erreurs)
    if vue == "overlay":
        objets = doc.get("objets")
        if not isinstance(objets, dict):
            return erreurs + [f"{ou}: `objets` attendu"]
        for cle, o in objets.items():
            if _fermer(o, CLES_OBJET, f"{ou} {cle}", erreurs):
                if o.get("objet") != cle:
                    erreurs.append(f"{ou} {cle}: `objet` différent de sa clé")
                if o.get("statut") not in STATUTS_OBJET:
                    erreurs.append(f"{ou} {cle}: statut inconnu {o.get('statut')!r}")
    return erreurs


def permissions_privees(chemin: Path) -> bool:
    """POSIX : aucun droit pour le groupe ni les autres."""
    return os.name != "posix" or (chemin.stat().st_mode & 0o077) == 0
