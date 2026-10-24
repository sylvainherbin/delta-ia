"""Traduction des textes communs (conception §3.2, lot L2) : cache par empreinte et rédacteur isolé du profil.

Cache : clé `(sha256 du texte source, champ, langue cible, révision du glossaire)`. Un texte déjà traduit n'est jamais
renvoyé au modèle ; une relance sans changement ne fait aucun appel et ne réécrit pas le cache. Le cache ne contient que
des traductions de textes publics (extraits de documentation) : il peut être suivi par Git avec la publication.

Rédacteur : `claude -p` en mode sans personnalisation (`--safe-mode` : ni CLAUDE.md, ni skills, ni MCP, ni hooks), sans
outil, invite système neutre de ce module, lancé dans un dossier vide, sans session gardée. Il ne reçoit que des textes
masqués (code entre accents graves et URL remplacés par `⟦n⟧`, rétablis au retour) ; la réponse est refusée si un repère
manque ou change. Contrôle des entrées réelles : le nombre de jetons d'entrée facturés est comparé à la taille de la
charge envoyée ; un contexte inattendu (instructions ou mémoire ajoutées par l'outil) fait refuser tout le lot.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import schemas
from .stockage import ecrire_public, empreinte

GLOSSAIRE = "r1"
LOT = 40  # unités par appel
SURCOUT_MAX = 2500  # jetons d'entrée tolérés au-delà de la charge estimée (cadre minimal de l'outil)
CONSIGNE = (
    "You translate short descriptions taken from official software documentation (Claude Code, Codex and related "
    "developer tools) from English into French.\n"
    "Rules:\n"
    "- Each placeholder like ⟦0⟧ stands for code or a URL: copy every placeholder exactly once, unchanged.\n"
    "- Keep product names, command names, flags, setting keys, file names and environment variables in English.\n"
    "- Neutral documentation register: infinitive or impersonal phrasing, never address the reader as tu or vous.\n"
    "- Translate faithfully: add, remove or explain nothing.\n"
    "Input: a JSON object {\"<key>\": \"<English text>\"}. Output: only a JSON object with the same keys and the French "
    "translations as values, with no other text.")
RE_MASQUE = re.compile(r"`[^`\n]+`|https?://[^\s)>\]]*[^\s)>\].,;:!?'\"]")  # URL sans la ponctuation qui la suit
RE_REPERE = re.compile(r"⟦(\d+)⟧")


def cle(texte_source: str, champ: str, langue: str = "fr", glossaire: str = GLOSSAIRE) -> str:
    return f"{schemas.sha256_texte(texte_source)}:{champ}:{langue}:{glossaire}"


def masquer(texte: str) -> tuple[str, list[str]]:
    morceaux: list[str] = []

    def remplacer(m):
        morceaux.append(m.group(0))
        return f"⟦{len(morceaux) - 1}⟧"
    return RE_MASQUE.sub(remplacer, texte), morceaux


def retablir(traduit: str, morceaux: list[str]) -> str | None:
    """Texte traduit avec ses repères rétablis, ou None si un repère manque, est en double ou inconnu."""
    vus = [int(m.group(1)) for m in RE_REPERE.finditer(traduit)]
    if sorted(vus) != list(range(len(morceaux))):
        return None
    return RE_REPERE.sub(lambda m: morceaux[int(m.group(1))], traduit)


class CacheInvalide(ValueError):
    pass


class Cache:
    """Traductions d'une langue ; `lire` passe par le lecteur borné du générateur quand il est fourni."""

    def __init__(self, chemin: Path | None, langue: str = "fr", lire=None):
        self.chemin, self.langue, self.entrees, self.ajouts, self.ecrit = chemin, langue, {}, 0, False
        if chemin is None or not chemin.exists():
            return
        try:
            doc = json.loads((lire(chemin) if lire else chemin.read_bytes()).decode("utf-8"))
        except (OSError, ValueError) as e:
            raise CacheInvalide(f"cache de traduction illisible : {e}") from e
        if (not isinstance(doc, dict) or doc.get("schema") != schemas.COMMUN or doc.get("vue") != "traductions"
                or doc.get("schema_version") != schemas.VERSION or doc.get("langue") != langue
                or not isinstance(doc.get("entrees"), dict)):
            raise CacheInvalide("cache de traduction : vue traductions v1 de la langue attendue")
        for k, v in doc["entrees"].items():
            if not isinstance(v, dict) or set(v) != {"texte", "modele", "le"} or not isinstance(v["texte"], str):
                raise CacheInvalide(f"cache de traduction : entrée {k[:20]}… invalide")
        self.entrees = doc["entrees"]

    def get(self, texte_source: str, champ: str) -> str | None:
        e = self.entrees.get(cle(texte_source, champ, self.langue))
        return e["texte"] if e else None

    def ajouter(self, texte_source: str, champ: str, texte: str, modele: str, le: str) -> None:
        self.entrees[cle(texte_source, champ, self.langue)] = {"texte": texte, "modele": modele, "le": le}
        self.ajouts += 1

    def enregistrer(self) -> bool:
        """Écrit le cache seulement s'il a reçu des traductions ; rend True si le fichier a changé (une fois au moins)."""
        if self.chemin is None or not self.ajouts:
            return False
        self.ecrit = True
        doc = {"schema": schemas.COMMUN, "schema_version": schemas.VERSION, "vue": "traductions", "langue": self.langue,
               "de": "en", "glossaire": GLOSSAIRE, "entrees": dict(sorted(self.entrees.items()))}
        return ecrire_public(self.chemin, doc)


@dataclass
class Unite:
    cle: str  # clé courte de l'unité dans la charge (identité de la fiche + champ)
    champ: str
    texte: str  # texte source anglais


@dataclass
class Bilan:
    """Coût et couverture d'un lot de traduction, mesurés et jamais supposés nuls."""
    appels: int = 0
    unites_envoyees: int = 0
    acceptees: int = 0
    refusees: int = 0
    lots_refuses: int = 0
    jetons_entree: int = 0
    jetons_sortie: int = 0
    cout_usd_catalogue: float = 0.0
    duree_s: float = 0.0
    modeles: set = field(default_factory=set)
    journal: list = field(default_factory=list)

    def resume(self) -> dict:
        return {"appels": self.appels, "unites_envoyees": self.unites_envoyees, "acceptees": self.acceptees,
                "refusees": self.refusees, "lots_refuses": self.lots_refuses, "jetons_entree": self.jetons_entree,
                "jetons_sortie": self.jetons_sortie, "cout_usd_catalogue": round(self.cout_usd_catalogue, 6),
                "duree_s": round(self.duree_s, 1), "modeles": sorted(self.modeles)}


class RedacteurClaude:
    """Appel `claude -p` isolé ; `executer` remplaçable (tests). Rend (traductions par clé, mesure de l'appel)."""
    outil = "claude"

    def __init__(self, modele: str = "haiku", executable: str = "claude", delai: int = 300, executer=None,
                 effort: str | None = "low"):
        self.modele, self.executable, self.delai, self.effort = modele, executable, delai, effort
        self.executer = executer or self._executer

    def commande(self) -> list[str]:
        return [self.executable, "-p", "--safe-mode", "--model", self.modele, *(["--effort", self.effort] if self.effort else []),
                "--tools", "", "--no-session-persistence", "--output-format", "json", "--system-prompt", CONSIGNE]

    def _executer(self, commande: list[str], entree: str) -> str:
        with tempfile.TemporaryDirectory(prefix="delta-commun-") as vide:
            res = subprocess.run(commande, input=entree, cwd=vide, capture_output=True, text=True, timeout=self.delai)
        if res.returncode:
            raise RuntimeError(f"claude -p : code {res.returncode}")
        return res.stdout

    def traduire(self, charge: dict[str, str]) -> tuple[dict[str, str], dict]:
        entree = json.dumps(charge, ensure_ascii=False)
        brut = json.loads(self.executer(self.commande(), entree))
        if brut.get("is_error") or brut.get("subtype") != "success":
            raise RuntimeError(f"claude -p : échec ({brut.get('subtype')})")
        usage = brut.get("usage") or {}
        jetons_entree = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                              "cache_read_input_tokens"))
        mesure = {"jetons_entree": jetons_entree, "jetons_sortie": int(usage.get("output_tokens") or 0),
                  "cout_usd_catalogue": float(brut.get("total_cost_usd") or 0.0),
                  "modele": next(iter(brut.get("modelUsage") or {}), self.modele),
                  "octets_envoyes": len((CONSIGNE + entree).encode("utf-8"))}
        texte = (brut.get("result") or "").strip()
        texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte)
        reponse = json.loads(texte)
        if not isinstance(reponse, dict):
            raise ValueError("réponse : objet JSON attendu")
        return {k: v for k, v in reponse.items() if isinstance(v, str)}, mesure


def traduire(unites: list[Unite], cache: Cache, redacteur, budget: int, le: str, bilan: Bilan, apres_lot=None) -> None:
    """Traduit au plus `budget` unités absentes du cache, par lots ; une unité refusée reste sans traduction.
    `apres_lot` (enregistrement du cache) est appelé après chaque lot accepté : une interruption ne perd que le lot en cours."""
    restantes = [u for u in unites if cache.get(u.texte, u.champ) is None][:max(budget, 0)]
    for i in range(0, len(restantes), LOT):
        lot = restantes[i:i + LOT]
        masques = {u.cle: masquer(u.texte) for u in lot}
        charge = {k: m[0] for k, m in masques.items()}
        debut = time.monotonic()
        bilan.appels += 1
        bilan.unites_envoyees += len(lot)
        ligne = {"le": le, "outil": redacteur.outil, "unites": len(lot), "envoi_sha256": empreinte(charge),
                 "consigne_sha256": schemas.sha256_texte(CONSIGNE), "envoi": charge}
        try:
            reponse, mesure = redacteur.traduire(charge)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            bilan.lots_refuses += 1
            bilan.refusees += len(lot)
            bilan.journal.append({**ligne, "erreur": type(e).__name__})
            continue
        bilan.duree_s += time.monotonic() - debut
        bilan.jetons_entree += mesure["jetons_entree"]
        bilan.jetons_sortie += mesure["jetons_sortie"]
        bilan.cout_usd_catalogue += mesure["cout_usd_catalogue"]
        bilan.modeles.add(mesure["modele"])
        ligne.update(mesure)
        # Environ un jeton pour trois à quatre octets de texte : au-delà de la moitié des octets envoyés et du cadre minimal
        # de l'outil, du contexte (instructions, mémoire) a été ajouté à la charge.
        if mesure["jetons_entree"] > mesure["octets_envoyes"] // 2 + SURCOUT_MAX:
            bilan.lots_refuses += 1
            bilan.refusees += len(lot)
            bilan.journal.append({**ligne, "erreur": "contexte_inattendu"})
            continue
        acceptees = 0
        for u in lot:
            traduit = reponse.get(u.cle)
            texte = retablir(traduit, masques[u.cle][1]) if isinstance(traduit, str) and traduit.strip() else None
            if texte is None or not (0.3 <= len(texte) / max(len(u.texte), 1) <= 3.0):
                bilan.refusees += 1
                continue
            cache.ajouter(u.texte, u.champ, texte.strip(), mesure["modele"], le)
            acceptees += 1
        bilan.acceptees += acceptees
        bilan.journal.append({**ligne, "acceptees": acceptees})
        if apres_lot is not None and acceptees:
            apres_lot()
