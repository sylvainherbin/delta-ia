"""Contrats v1 des deux couches (conception §2.2, §2.3) : `delta.commun`, `delta.personnel`, `delta.manifest`.

Schémas fermés : une clé non prévue est refusée. La validation d'un document commun ne fait pas confiance au producteur :
chaque fiche est reprojetée sur la table de classement de sa famille source (`classement`), et tout chemin qui n'y est pas C
(P, S, inconnu, mis en attente en L1) est une erreur, comme toute donnée personnelle détectée dans un texte.

Lot L2 : enveloppe bilingue `textes` (produite par le générateur commun, hors de l'empreinte factuelle : une traduction ne
périme aucun avis), jours couverts de la veille, document de publication d'une route versionnée et état de synchronisation.
"""

from __future__ import annotations

import hashlib
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
LANGUES = ("en", "fr")
STATUTS_TRADUCTION = ("automatique", "revu")
# Champs portant une enveloppe `textes`, par famille commune, et champ C dont le texte anglais est l'extrait.
CHAMPS_TEXTES = {"kb": {"description": "description_source"}}
RE_GLOSSAIRE = re.compile(r"r[0-9]+")
RE_HORODATAGE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")

# Racine de chaque famille commune : clés permises, et famille source dont les fiches sont reprojetées.
RACINES_COMMUN = {
    "kb": {"perimetre", "categorie", "maj_le", "total", "entrees"},
    "methodes": {"categorie", "maj_le", "origine", "total", "entrees"},
    "modeles": {"categorie", "date_releve", "maj_le", "origine", "version_source", "total", "total_modeles", "entrees",
                "modeles"},
    "veille": {"perimetre", "maj_le", "jours", "total", "entrees"},
    "versions": {"total", "entrees"},
    "noms": {"noms"},
}
CLES_MANIFEST = {"schema", "schema_version", "generation", "publie_le", "donnees_du", "schemas_requis", "langues",
                 "couverture", "fichiers", "couverture_langues", "couverture_sources"}
CLES_ACTIF = {"schema", "schema_version", "vue", "generation", "manifest_sha256", "precedente", "origine", "publie_le"}
CLES_PUBLICATION = {"schema", "schema_version", "vue", "generation", "manifest_sha256", "publie_le", "precedente",
                    "cycle_attendu_h", "perimetres"}
CLES_SYNCHRO = {"schema", "schema_version", "vue", "source", "verifie_le", "derniere_tentative", "erreur", "etag",
                "last_modified", "publie_le", "generation"}
CLES_OBJET = {"objet", "commun_empreinte", "statut", "langue", "observe_le", "evalue_le", "statut_usage",
              "recommandation", "pour_toi", "action", "exemple_local", "essais", "reevaluations", "rejugements",
              "historique_importe"}
CLES_PERSONNEL = {"overlay": {"schema", "schema_version", "vue", "commun_generation", "profil_empreinte", "objets"},
                  "en_attente": {"schema", "schema_version", "vue", "commun_generation", "objets", "refus"},
                  "import": {"schema", "schema_version", "vue", "commun_generation", "entrees", "comptes"},
                  "sources": {"schema", "schema_version", "vue", "commun_generation", "fichiers"},
                  # lot L4 : instantanés des sources OPÉRER et projection modèle × effort (bilan.py)
                  "reglages_bilan": {"schema", "schema_version", "vue", "commande", "filtres", "version", "jusqu_au",
                                     "lignes_ignorees", "lu_le", "sha256", "bilan"},
                  "essais_operer": {"schema", "schema_version", "vue", "commande", "lu_le", "sha256", "essais"},
                  "modeles_efforts": {"schema", "schema_version", "vue", "commun_generation", "bilan_empreinte", "filtres",
                                      "jusqu_au", "observe_le", "objets", "non_rattaches"},
                  # lot 2 : profil d'hôte et réglages courants de l'instance (instance.py)
                  "instance": {"schema", "schema_version", "vue", "lu_le", "profil", "reglages", "sha256"}}
CLES_COUPLE = {"objet", "commun_empreinte", "bilan_empreinte", "observe_le", "jusqu_au", "groupes"}


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
    contenu = contenu_factuel(fiche)
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
    if "textes" in fiche and famille_source != "kb_catalogue":
        erreurs.append(f"{ou}: `textes` non prévu pour cette famille")


def contenu_factuel(fiche: dict) -> dict:
    """Champs factuels d'une fiche : sans identité, empreinte ni enveloppe de textes (une traduction ne change pas le fait)."""
    return {k: v for k, v in fiche.items() if k not in ("identite", "empreinte", "textes")}


def empreinte_fiche(identite, contenu: dict) -> str:
    return empreinte({"identite": identite, **{k: v for k, v in contenu.items() if k != "textes"}})


def sha256_texte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _textes(fiche: dict, famille: str, ou: str, erreurs: list[str]) -> None:
    """Enveloppe bilingue (conception §3.2) : anglais = extrait de la source déclaré tel quel ; français traduit de cet
    extrait exact (empreinte), avec sa révision de glossaire et son statut. Rien d'autre."""
    if "textes" not in fiche:
        return
    textes, permis = fiche["textes"], CHAMPS_TEXTES.get(famille, {})
    if not isinstance(textes, dict) or not textes or set(textes) - set(permis):
        erreurs.append(f"{ou}: `textes` attendu pour {sorted(permis)} seulement")
        return
    for champ, langues in textes.items():
        if not isinstance(langues, dict) or "en" not in langues or set(langues) - set(LANGUES):
            erreurs.append(f"{ou} textes.{champ}: langues {list(LANGUES)} avec `en` attendues")
            continue
        en, fr = langues["en"], langues.get("fr")
        if (not isinstance(en, dict) or set(en) != {"texte", "statut", "origine"} or en.get("statut") != "source"
                or en.get("origine") != permis[champ] or en.get("texte") != fiche.get(permis[champ])):
            erreurs.append(f"{ou} textes.{champ}.en: extrait `{permis[champ]}` de la fiche, statut source, attendu")
            continue
        if fr is None:
            continue
        if (not isinstance(fr, dict) or set(fr) != {"texte", "statut", "de", "source_sha256", "glossaire"}
                or fr.get("statut") not in STATUTS_TRADUCTION or fr.get("de") != "en"
                or not isinstance(fr.get("texte"), str) or not fr["texte"].strip()
                or not isinstance(fr.get("glossaire"), str) or not RE_GLOSSAIRE.fullmatch(fr["glossaire"])):
            erreurs.append(f"{ou} textes.{champ}.fr: {{texte, statut, de: en, source_sha256, glossaire}} attendu")
        elif fr["source_sha256"] != sha256_texte(en["texte"]):
            erreurs.append(f"{ou} textes.{champ}.fr: traduction d'un autre texte que l'extrait actuel")


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
            if isinstance(f, dict):
                _textes(f, "kb", f"{ou} entrees[{i}]", erreurs)
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
        racine = {k: doc[k] for k in ("jours", "maj_le", "perimetre") if k in doc}
        hors = _hors_commun("index_veille", racine)
        if hors:
            erreurs.append(f"{ou}: champs non communs {hors}")
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
    langues = manifest.get("langues")
    if not isinstance(langues, list) or set(langues) - set(LANGUES):
        erreurs.append(f"manifest.json: langues parmi {list(LANGUES)} attendues")
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
    elif vue == "modeles_efforts":
        objets = doc.get("objets")
        if not isinstance(objets, dict) or not isinstance(doc.get("non_rattaches"), list):
            return erreurs + [f"{ou}: `objets` et `non_rattaches` attendus"]
        for cle, o in objets.items():
            if not cle.startswith("kb:delta:modeles:"):
                erreurs.append(f"{ou} {cle}: clé de couple kb:delta:modeles:<id> attendue")
            if _fermer(o, CLES_COUPLE, f"{ou} {cle}", erreurs) and o.get("objet") != cle:
                erreurs.append(f"{ou} {cle}: `objet` différent de sa clé")
    elif vue == "instance":
        contenu = {"profil": doc.get("profil"), "reglages": doc.get("reglages")}
        if not isinstance(doc.get("sha256"), str) or doc["sha256"] != empreinte(contenu):
            erreurs.append(f"{ou}: `sha256` différent du contenu")
        if not isinstance(doc.get("profil"), dict) or doc["profil"].get("statut") not in ("absent", "invalide", "present"):
            erreurs.append(f"{ou}: statut de profil inconnu")
        if not isinstance(doc.get("reglages"), dict) or not isinstance(doc["reglages"].get("cases"), list):
            erreurs.append(f"{ou}: `reglages.cases` attendu")
    elif vue in ("reglages_bilan", "essais_operer"):
        contenu = doc.get("bilan" if vue == "reglages_bilan" else "essais")
        if not isinstance(doc.get("sha256"), str) or doc["sha256"] != empreinte(contenu):
            erreurs.append(f"{ou}: `sha256` différent du contenu")
    return erreurs


def permissions_privees(chemin: Path) -> bool:
    """POSIX : aucun droit pour le groupe ni les autres."""
    return os.name != "posix" or (chemin.stat().st_mode & 0o077) == 0


def _horodatage(valeur, ou: str, erreurs: list[str], nul: bool = False) -> None:
    if valeur is None and nul:
        return
    if not isinstance(valeur, str) or not RE_HORODATAGE.fullmatch(valeur):
        erreurs.append(f"{ou}: horodatage ISO 8601 avec fuseau attendu")


def valider_publication(doc, ou: str = "index.json") -> list[str]:
    """Document de publication d'une route versionnée : génération servie, empreinte de son manifeste, heure du cycle de
    publication, génération précédente gardée pour retour, cycle attendu et dernier jour couvert par périmètre."""
    erreurs: list[str] = []
    if not _en_tete(doc, MANIFEST, ou, erreurs):
        return erreurs
    if doc.get("vue") != "publication":
        return [f"{ou}: vue publication attendue"]
    _fermer(doc, CLES_PUBLICATION, ou, erreurs)
    if not isinstance(doc.get("generation"), str) or not RE_GENERATION.fullmatch(doc["generation"]):
        erreurs.append(f"{ou}: génération invalide")
    if not isinstance(doc.get("manifest_sha256"), str) or not RE_SHA256.fullmatch(doc["manifest_sha256"]):
        erreurs.append(f"{ou}: manifest_sha256 invalide")
    _horodatage(doc.get("publie_le"), f"{ou} publie_le", erreurs)
    prec = doc.get("precedente")
    if prec is not None and (not isinstance(prec, dict) or set(prec) != {"generation", "manifest_sha256"}
                             or not RE_GENERATION.fullmatch(str(prec.get("generation")))
                             or not RE_SHA256.fullmatch(str(prec.get("manifest_sha256")))):
        erreurs.append(f"{ou}: precedente {{generation, manifest_sha256}} ou null attendue")
    if not isinstance(doc.get("cycle_attendu_h"), int) or doc["cycle_attendu_h"] <= 0:
        erreurs.append(f"{ou}: cycle_attendu_h entier positif attendu")
    perimetres = doc.get("perimetres")
    if not isinstance(perimetres, dict) or set(perimetres) - set(cl.PERIMETRES_VEILLE) or not all(
            isinstance(v, dict) and set(v) == {"dernier_jour"}
            and (v["dernier_jour"] is None or (isinstance(v["dernier_jour"], str) and cl.RE_JOUR.fullmatch(v["dernier_jour"])))
            for v in perimetres.values()):
        erreurs.append(f"{ou}: perimetres {{<périmètre>: {{dernier_jour}}}} attendu")
    return erreurs


def valider_synchro(doc, ou: str = "synchro.json") -> list[str]:
    erreurs: list[str] = []
    if not _en_tete(doc, COMMUN, ou, erreurs):
        return erreurs
    if doc.get("vue") != "synchro":
        return [f"{ou}: vue synchro attendue"]
    _fermer(doc, CLES_SYNCHRO, ou, erreurs)
    for cle in ("verifie_le", "derniere_tentative", "publie_le"):
        _horodatage(doc.get(cle), f"{ou} {cle}", erreurs, nul=True)
    return erreurs
