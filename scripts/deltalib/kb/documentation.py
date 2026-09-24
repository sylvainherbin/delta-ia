"""Section `documentation` de sources.yaml et récupération des pages dans raw/kb/ avec empreintes (D44)."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from ..dates import maintenant_iso
from ..http import Client
from ..modeles import ErreurSource
from .extracteurs import EXTRACTEURS
from .modeles import PERIMETRE_DU_PRODUIT

STATUTS_ACTIFS = ("ok", "a_valider")


@dataclass
class DocSource:
    id: str
    perimetre: str
    produit: str
    extracteur: str
    statut: str
    url: str | None = None
    base: str | None = None
    note: str = ""
    options: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.statut in STATUTS_ACTIFS

    @property
    def url_publique(self) -> str:
        """URL lisible par un humain : sans `.md`, sans `?surface=` quand la variante Markdown est lue."""
        u = self.url or self.base or ""
        return u[:-3] if u.endswith(".md") else u.replace(".md?", "?")

    @property
    def libelle(self) -> str:
        return urlsplit(self.url_publique).path.rstrip("/").rsplit("/", 1)[-1] or self.id

    def fichiers(self) -> dict[str, str]:
        """Nom logique -> URL à récupérer."""
        if self.extracteur == "pages":
            # option `chemin` : l'article a changé d'adresse ; la clé (donc l'id de l'entrée et le cache) reste
            return {f"page:{c}": f"{self.base}{chemin_page(c, v)}.md" for c, v in self.options["pages"].items()}
        res = {"page": self.url}
        if self.options.get("url_md"):
            res["md"] = self.options["url_md"]
        return res


def chemin_page(cle: str, conf) -> str:
    """Chemin réel d'une page : `chemin` de sa configuration s'il est donné, sinon sa clé."""
    return conf.get("chemin", cle) if isinstance(conf, dict) else cle


class ErreurDocumentation(Exception):
    pass


def charger_documentation(chemin: str | Path) -> list[DocSource]:
    with open(chemin, encoding="utf-8") as f:
        brutes = (yaml.safe_load(f) or {}).get("documentation") or []
    docs, vus = [], set()
    for b in brutes:
        d = DocSource(**{k: b.get(k) for k in ("id", "perimetre", "produit", "extracteur", "statut", "url", "base")},
                      note=b.get("note") or "", options=b.get("options") or {})
        if not d.id or d.id in vus:
            raise ErreurDocumentation(f"identifiant de documentation absent ou en double : {d.id!r}")
        vus.add(d.id)
        if d.extracteur not in EXTRACTEURS:
            raise ErreurDocumentation(f"{d.id}: extracteur inconnu {d.extracteur!r}")
        if PERIMETRE_DU_PRODUIT.get(d.produit) != d.perimetre:
            raise ErreurDocumentation(f"{d.id}: produit {d.produit!r} hors du périmètre {d.perimetre!r}")
        if not (d.url or (d.base and d.options.get("pages"))):
            raise ErreurDocumentation(f"{d.id}: `url`, ou `base` et `options.pages`, requis")
        docs.append(d)
    return docs


def chemin_cache(racine: Path, doc: DocSource, nom: str) -> Path:
    base = racine / "raw" / "kb" / doc.produit / doc.id
    if nom == "page":
        return base / ("page.html" if not (doc.url or "").split("?")[0].endswith(".md") else "page.md")
    if nom == "md":
        return base / "page-source.md"
    return base / (nom.split(":", 1)[1].replace("/", "__") + ".md")


def empreinte(texte: str) -> str:
    return hashlib.sha1(texte.encode("utf-8")).hexdigest()[:16]


def lire_cache(racine: Path, doc: DocSource, surcharge: dict | None = None) -> dict[str, str]:
    """Fichiers d'une documentation : la version récupérée en mémoire (dry-run) prime sur la copie de raw/kb/."""
    res = {}
    for nom in doc.fichiers():
        cle = f"{doc.id}/{nom}"
        if surcharge and cle in surcharge:
            res[nom] = surcharge[cle]
            continue
        p = chemin_cache(racine, doc, nom)
        if p.exists():
            res[nom] = p.read_text(encoding="utf-8")
    return res


def recuperer(racine: Path, docs: list[DocSource], fabrique_client=Client, paralleles: int = 4,
              ecrire: bool = True) -> dict:
    """Télécharge chaque fichier ; en cas d'échec, l'ancienne copie reste en place. Rend un bilan par page.

    D47 : avec `ecrire=False` (dry-run), rien n'est écrit, ni copie ni empreinte ; les textes récupérés sont
    rendus dans `bilan["textes"]` pour une extraction en mémoire.
    """
    local = threading.local()

    def client():
        if not hasattr(local, "c"):
            local.c = fabrique_client()
        return local.c

    taches = [(d, nom, url) for d in docs for nom, url in d.fichiers().items()]

    def une(t):
        d, nom, url = t
        try:
            rep = client().get(url, accept="text/markdown, text/html")
        except ErreurSource as e:
            return d, nom, url, None, str(e)
        return d, nom, url, rep.texte, None

    with ThreadPoolExecutor(max_workers=paralleles) as ex:
        resultats = list(ex.map(une, taches))
    bilan = {"pages": 0, "modifiees": [], "nouvelles": [], "echecs": [], "textes": {}}
    par_produit: dict[str, dict] = {}
    for d, nom, url, texte, erreur in resultats:
        chemin = chemin_cache(racine, d, nom)
        index_path = racine / "raw" / "kb" / d.produit / "empreintes.json"
        index = par_produit.setdefault(d.produit, _lire_json(index_path))
        cle = f"{d.id}/{nom}"
        if erreur:
            bilan["echecs"].append({"doc": d.id, "fichier": nom, "url": url, "erreur": erreur})
            continue
        e = empreinte(texte)
        ancienne = (index.get(cle) or {}).get("empreinte")
        if ecrire:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(texte, encoding="utf-8")
            index[cle] = {"url": url, "empreinte": e, "recupere_le": maintenant_iso(), "octets": len(texte.encode("utf-8"))}
        else:
            bilan["textes"][cle] = texte
        bilan["pages"] += 1
        if ancienne is None:
            bilan["nouvelles"].append(cle)
        elif ancienne != e:
            bilan["modifiees"].append(cle)
    for produit, index in (par_produit.items() if ecrire else ()):
        p = racine / "raw" / "kb" / produit / "empreintes.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(sorted(index.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    return bilan


def _lire_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
