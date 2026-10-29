#!/usr/bin/env python3
"""Delta — orchestrateur des passages automatiques (D70). Lancé par `scripts/passage-auto.sh`, qui tient le verrou
`.git/delta-passage.lock` (flock) pendant toute la chaîne ; jamais lancé directement par un timer.

Chaîne, dans l'ordre, chaque étape ne démarrant qu'à la fin de la précédente :
  delta (Claude : claude, actu) -> codex-delta (Codex : openai) -> delta-kb (Claude) -> codex-delta-kb (Codex)
  -> supervision (Claude, lecture seule), TOUJOURS lancée, même si une étape a échoué.

Pour chaque étape, sans aucun LLM :
1. garde `scripts/garde.py --etape <étape>` : code 11 (quota Claude) ou 12 (déjà fait) = étape sautée, la chaîne continue ;
   10, 13, 14, 15 ou toute autre erreur = la chaîne s'arrête (la supervision reste lancée) ;
2. étapes kb : sautées (code interne 129) quand aucun lot n'est dû ;
3. lancement dans son propre groupe de processus, sous délai maximal ; dépassement ou échec : SIGTERM puis SIGKILL sur tout le
   groupe (un enfant ne survit pas), puis arrêt propre limité aux chemins de l'étape (`git checkout --` et `git clean -f --`).
   Exception Claude, hors supervision : délai dépassé ou résultat illisible après livraison de TOUS les commits attendus
   dans origin/main, arbre déjà propre AVANT nettoyage, intégrité git et comptes conformes : « livrée sans retour »,
   code 0 avec le diagnostic du transport conservé ; les validations habituelles tournent et la chaîne continue.
   Un commit manquant (dont delta(actu)) reste nommé dans l'échec ; aucune livraison partielle n'est promue en succès ;
4. succès d'une étape Claude : code 0, JSON lisible, `subtype` success, `is_error` faux ; étape Codex : code 0. Le code 0 ne
   suffit jamais (`codex exec` rend 0 même quand l'agent s'arrête sur une erreur) : le résultat produit doit être conforme
   (`resultat_incomplet`, code 133 sinon) : chaque commit attendu présent, arbre propre, aucun compte d'éléments nul alors que le
   brut du jour annonce des nouveautés, rapport écrit pour la supervision. Un refus de
   permission (`permission_denials` non vide) est fatal (code 125) SAUF si tout le reste est conforme : le résultat est
   `success`, l'état final est propre (126), et chaque commit attendu de l'étape (`commits_attendus`, sujets de la
   configuration) figure dans `git log` depuis le début de l'étape avec `origin/main` qui les contient. Pour la supervision,
   qui ne commite jamais, le résultat attendu est un rapport non vide `rapports/<jour>_HHMM-supervision.md` du jour de la
   chaîne, créé ou modifié pendant l'étape (mtime >= début de l'étape). Le refus devient alors un avertissement (ligne
   `<étape>-refus`, code 125) ; sans ce rapport pour la supervision, ou sans les commits attendus pour les autres étapes,
   il reste fatal même après un arrêt propre. Dans les deux cas l'état final doit être propre (arbre sans fichier modifié,
   pas de `.git/index.lock`,
   aucun commit local absent de `origin/main`), et `.git/hooks/` (noms et contenus) comme `.git/config` doivent être
   inchangés (un hook ou un réglage git écrit par une étape s'exécuterait ensuite hors de son bac à sable : code 126),
   sinon la chaîne s'arrête : l'orchestrateur ne pousse aucun commit d'étape, ne supprime
   jamais un `.git/index.lock` (D21) et ne touche jamais à `raw/` (historique du brut, D72), sauf le capteur de la liste X (clé
   `chaine.capteur_x`) : relevé avant la première étape, publication dédiée des seuls IDs (`delta(x):`,
   push avant fast-forward local, échec non bloquant), purge du texte des posts après la supervision ;
5. contrôle de `valider.py` : étape réussie, `valider.py` relancé seul (sans tube : son code est lu directement) sur l'arbre
   après l'étape, un appel par périmètre (`valider` de la configuration, avec `--date` du jour ; `--kb` du produit pour une
   étape kb). Un échec marque l'étape en échec (code 131, détail dans la ligne de sortie de l'étape et dans la supervision) ;
   rien n'est annulé ni poussé de plus (jamais de `--force`), la chaîne continue ;
6. échec réseau (D122) : une étape Claude ou Codex en échec dont la sortie dit sans ambiguïté qu'Internet ou le service est
   indisponible (Claude : `terminal_reason` `api_error`, aucun jeton, `result` avec ENOTFOUND, ECONNREFUSED, ETIMEDOUT,
   ECONNRESET, EAI_AGAIN ou « Can't reach the API server » ; Codex : « Selected model is at capacity ») est remise en place par
   l'arrêt propre puis relancée, trois fois au plus, après 5, 10 puis 20 min d'attente (`chaine.relances_reseau_s`) ; pendant
   l'attente, la résolution DNS de l'hôte de l'API est testée (une panne DNS relance dès qu'elle répond), aucune tentative ne
   commence entre 07 h 30 et 08 h 00 (`relances_limite`, `fenetre_fin`) ; chaque tentative est journalisée dans la sortie de
   l'étape, la ligne de `passages.log` reste unique (code final) ; une relance n'a lieu que si l'arbre, `.git` et le dépôt
   distant sont dans l'état d'avant l'étape, sinon l'échec suit le chemin ordinaire (126, 15) ;
7. une ligne `orchestrateur` dans `rapports/passages.log` (scripts/passages.py) et la sortie de l'étape dans
   `rapports/auto/AAAA-MM-JJ-<étape>.log` (jamais l'environnement).

Mode Claude : `[claude].mode = "cle"` passe par `claude-cle --usage <nom>` (clé lue uniquement par delta-cle-api).
Le code 5 déclenche un repli unique sur la commande abonnement, seulement si le dépôt est resté intact ; une nouvelle garde
réactive les quotas abonnement. L'événement `<étape>-repli-abonnement`, code 5, est ajouté au journal, avec le détail dans
la sortie d'étape. `mode = "abonnement"` restaure les commandes antérieures. Les skills restent lues par leur chemin explicite.

Colonne « code » de la ligne `orchestrateur | <étape>` : 0 réussie ou saut normal ; les codes internes 11 (quota Claude),
12 (déjà fait), 128 (non lancée après un arrêt antérieur), 129 (aucun lot dû) et 130 (quota Codex épuisé) restent dans
`Issue.code` mais la ligne de journal porte 0 et une cause commençant exactement par `saut:` dans sa dernière colonne.
Une réussite réelle a une cause vide ou sans ce préfixe. 10, 13, 14 ou 15 arrêtée par la garde ;
124 délai dépassé ; 125 permission refusée (Claude), fatale ; la ligne `<étape>-refus` à 0 est un avertissement (refus non
fatal, étape réussie avec ses commits poussés ou son rapport de supervision écrit pendant l'étape) ;
126 état final non conforme (arbre sale, `.git/index.lock`, hooks ou config git modifiés) ;
127 binaire introuvable ; 128 non lancée (chaîne arrêtée plus tôt) ; 129 sautée, aucun lot dû ;
130 sautée, quota de l'agent épuisé (refus constaté de Codex, arbre propre, sans seuil : la chaîne continue) ;
131 étape réussie mais `valider.py` échoue sur l'arbre qu'elle a laissé (déjà poussé : signalé, la chaîne continue) ;
132 étape abandonnée sur échec réseau (trois relances échouées, ou relance interdite en fin de fenêtre) : la chaîne s'arrête ;
133 étape sortie en code 0 mais résultat incomplet ou contradictoire : l'agent s'est arrêté avant la fin de son skill (`codex exec`
rend 0 même sur une commande en erreur), un commit attendu (`commits_attendus`) manque, l'arbre est sale (remis en place par
l'arrêt propre), un compte d'éléments est nul alors que le brut du jour en annonce, ou la supervision n'a écrit aucun rapport :
échec, jamais compté comme fait du jour (l'arrêt propre efface le fichier du jour, la garde ne répond pas 12), la chaîne s'arrête ;
autre : code de sortie de l'agent.
Dernière ligne : `orchestrateur | chaine`, code 0 si aucune étape n'a échoué, 1 sinon.

Aucun appel à `claude` ou `codex` hors de `lancer()` ; les tests y injectent de fausses commandes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time as heure, timedelta
from pathlib import Path
from time import sleep, time_ns

sys.path.insert(0, str(Path(__file__).resolve().parent))

import passages  # noqa: E402
from deltalib import capteur_x  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).resolve().parent / "orchestrateur.toml"
AGENT_JOURNAL = "orchestrateur"

CODE_DELAI, CODE_PERMISSION, CODE_ETAT, CODE_BINAIRE, CODE_NON_LANCEE, CODE_SANS_LOT = 124, 125, 126, 127, 128, 129
CODE_QUOTA_EPUISE = 130  # Codex refuse de tourner (limite d'usage atteinte) : étape sautée, la chaîne continue
CODE_VALIDATION = 131    # l'étape a réussi mais `valider.py` échoue sur l'arbre qu'elle a laissé : échec signalé, la chaîne continue
CODE_RESEAU = 132        # échec réseau persistant : relances épuisées ou interdites en fin de fenêtre (D122)
CODE_INCOMPLET = 133     # code 0 de l'agent mais résultat incomplet ou contradictoire (arrêt avant la fin du skill, commit manquant)
DELAI_VALIDATION_S = 300
LONGUEUR_RAPPORT_SUPERVISION_MIN = 100
MARQUEUR_REFUS_SUPERVISION = re.compile(
    r"\b(?:je ne peux pas|je ne suis pas en mesure|je n[’']ai pas acc[eè]s|"
    r"i cannot|i can[’']t|i(?: am|[’']m) unable to)\b", re.IGNORECASE)
SIGNATURE_QUOTA_CODEX = re.compile(r"You[’']ve hit your usage limit", re.IGNORECASE)
REPRISE_QUOTA_CODEX = re.compile(r"try again at ([^\r\n]*?)\.?\s*$", re.IGNORECASE | re.MULTILINE)
CODES_RESEAU_CLAUDE = re.compile(r"ENOTFOUND|ECONNREFUSED|ETIMEDOUT|ECONNRESET|EAI_AGAIN")
PHRASE_RESEAU_CLAUDE = re.compile(r"Can[’']t reach the API server")
MOTIFS_DNS = re.compile(r"ENOTFOUND|EAI_AGAIN")  # panne de résolution : la relance part dès que le DNS répond
MOTIF_RESEAU_CODEX = re.compile(r"^ERROR: Selected model is at capacity\. Please try a different model\.\s*$", re.MULTILINE)  # relevé le 13/10/2026
PAS_DNS_S = 15
CODES_GARDE_SAUTEE = (11, 12)  # l'étape est sautée, la chaîne continue ; tout autre code de garde arrête la chaîne


@dataclass
class Etape:
    nom: str
    agent: str                      # claude | codex
    commande: list[str]             # complète ; construite par construire_etapes, ou fausse dans les tests
    delai_s: float
    garde: str | None = None        # valeur de `garde.py --etape` ; None : pas de garde (supervision)
    commits_attendus: list[str] = field(default_factory=list)  # débuts de sujets de commit que l'étape doit produire (refus non fatal)
    kb: str | None = None           # périmètre kb : étape sautée quand aucun lot n'est dû
    valider: list[str] = field(default_factory=list)  # périmètres quotidiens que `valider.py` contrôle après l'étape
    valider_kb: bool = False        # étape kb : `valider.py --kb` du produit `kb` contrôlé après l'étape
    supervision: bool = False
    checkout: list[str] = field(default_factory=list)
    clean: list[str] = field(default_factory=list)
    env_extra: dict[str, str] = field(default_factory=dict)
    commande_abonnement: list[str] = field(default_factory=list)  # repli unique, uniquement sur code 5 de claude-cle


@dataclass
class Resultat:
    code: int
    stdout: str
    stderr: str
    delai_depasse: bool
    duree_s: float
    garde_abonnement: bool = False


@dataclass
class Issue:
    etape: str
    code: int
    ok: bool                         # étape réussie ou sautée sans faute
    arret_chaine: bool
    detail: str
    commit: str = "aucun"


# ------------------------------------------------------------------------------------------------ configuration

def charger_config(chemin: Path = CONFIG) -> dict:
    with open(chemin, "rb") as f:
        return tomllib.load(f)


def _chemin(p: str) -> str:
    return os.path.expanduser(p)


def maison() -> str:
    return pwd.getpwuid(os.getuid()).pw_dir


def environnement(cfg: dict, supervision: bool = False, extra: dict | None = None) -> dict:
    """Environnement d'une étape : construit, jamais hérité (HOME, PATH et dossier de travail fixés par l'orchestrateur)."""
    home = maison()
    env = {
        "HOME": home,
        "USER": pwd.getpwuid(os.getuid()).pw_name,
        "LOGNAME": pwd.getpwuid(os.getuid()).pw_name,
        "PATH": ":".join(p.replace("~", home, 1) if p.startswith("~") else p for p in cfg["chaine"]["path"]),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "GIT_TERMINAL_PROMPT": "0",      # un push ne doit jamais attendre un mot de passe
        "DELTA_CHAINE_PID": str(os.getpid()),
    }
    if supervision:
        env["GIT_OPTIONAL_LOCKS"] = "0"  # la supervision ne laisse jamais de .git/index.lock
    for cle in ("XDG_RUNTIME_DIR", "DELTA_INSTANCE_POLICY"):   # DELTA_INSTANCE_POLICY : seuils de garde.py (OBS6)
        if cle in os.environ:
            env[cle] = os.environ[cle]
    env.update(extra or {})
    return env


def commande_claude(cfg: dict, e: dict, racine: Path, prompt: str, *, mode: str | None = None) -> list[str]:
    """Syntaxe du `claude --help` de la version installée (2.1.302) : -p, --permission-mode bypassPermissions (étapes Claude
    depuis le 06/10/2026, décision de Sylvain, D83), --strict-mcp-config (aucun serveur MCP), --output-format json (le résultat
    porte `permission_denials`, traité comme avant). Jamais --dangerously-skip-permissions."""
    mode = mode or cfg["claude"].get("mode", "abonnement")
    if mode not in ("cle", "abonnement"):
        raise ValueError(f"claude.mode inconnu : {mode!r} (cle ou abonnement attendu)")
    # Le lanceur commun a un défaut de 600 s destiné aux appels courts. L'orchestrateur possède le délai
    # de l'étape : le garde-fou interne reste borné mais expire après notre arrêt du groupe.
    c = ([_chemin(cfg["claude"]["bin_cle"]), "--usage", e["usage"], "--delai",
          str(e["delai_min"] * 60 + cfg["chaine"]["arret_delai_s"] + 1)] if mode == "cle"
         else [_chemin(cfg["claude"]["bin"])])
    c += ["-p", prompt, "--permission-mode", "bypassPermissions",
         "--strict-mcp-config", "--output-format", "json"]
    if e.get("modele"):
        c += ["--model", e["modele"]]
    if e.get("effort"):
        c += ["--effort", e["effort"]]
    if e.get("supervision"):
        c += ["--setting-sources", ""]
        if mode == "abonnement":
            c += ["--settings", str(racine / e["settings"])]
    else:
        c += ["--setting-sources", cfg["claude"]["sources_etapes"]]
    if mode == "cle":
        # --settings est réservé au apiKeyHelper. Fournir les listes par CLI conserve aussi allow dans une copie
        # non approuvée (le CLI ignore alors les allow de project). Les deny restent applicables en bypassPermissions.
        source = e["settings"] if e.get("supervision") else ".claude/settings.json"
        reglages = json.loads((racine / source).read_text(encoding="utf-8"))
        if not isinstance(reglages, dict) or not isinstance(reglages.get("permissions"), dict):
            raise ValueError("Claude sur clé : objet permissions attendu")
        permissions = reglages["permissions"]
        if (e.get("supervision") and set(reglages) != {"permissions"}) or set(permissions) - {"allow", "deny"}:
            raise ValueError("Claude sur clé : seuls permissions.allow et permissions.deny sont traduisibles")
        for liste, option in (("allow", "--allowedTools"), ("deny", "--disallowedTools")):
            regles = permissions.get(liste, [])
            if not isinstance(regles, list) or any(not isinstance(r, str) or not r for r in regles):
                raise ValueError(f"Claude : permissions.{liste} doit être une liste de règles")
            if regles:
                c += [option, *regles]
        # --bare saute la découverte de CLAUDE.md ; une inclusion @ n'est pas développée dans un prompt ajouté.
        # Le seul import du CLAUDE.md du dépôt est REGLES.md : fournir les deux contenus explicitement.
        contexte = "\n\n".join(f"# {nom}\n{(racine / nom).read_text(encoding='utf-8')}"
                                for nom in ("CLAUDE.md", "REGLES.md"))
        c += ["--append-system-prompt", contexte]
    return c


def commande_codex(cfg: dict, e: dict, racine: Path, prompt: str) -> list[str]:
    c = [_chemin(cfg["codex"]["bin"]), "exec", "--ignore-user-config", "-C", str(racine), "--color", "never"]
    for kv in cfg["codex"]["config"]:
        c += ["-c", kv]
    return c + [prompt]


def construire_etapes(cfg: dict, racine: Path = RACINE) -> list[Etape]:
    etapes = []
    for nom, e in cfg["etapes"].items():
        prompt = (racine / e["prompt_fichier"]).read_text(encoding="utf-8") if e.get("prompt_fichier") else e["prompt"]
        cmd = commande_claude(cfg, e, racine, prompt) if e["agent"] == "claude" else commande_codex(cfg, e, racine, prompt)
        sur_cle = e["agent"] == "claude" and cfg["claude"].get("mode", "abonnement") == "cle"
        etapes.append(Etape(nom=nom, agent=e["agent"], commande=cmd, delai_s=e["delai_min"] * 60, garde=e.get("garde"),
                            kb=e.get("kb"), valider=list(e.get("valider", [])), valider_kb=bool(e.get("valider_kb")), supervision=bool(e.get("supervision")), checkout=list(e.get("checkout", [])),
                            commits_attendus=list(e.get("commits_attendus", [])),
                            env_extra={"DELTA_CLAUDE_MODE": "cle"} if sur_cle else {},
                            commande_abonnement=commande_claude(cfg, e, racine, prompt, mode="abonnement") if sur_cle else [],
                            clean=list(e.get("clean", []))))
    return etapes


# ------------------------------------------------------------------------------------------------------------ git

def git(racine: Path, *args: str, env: dict | None = None) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(racine), *args], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})
    return r.returncode, (r.stdout + r.stderr).strip()


def tete_courte(racine: Path) -> str:
    code, sortie = git(racine, "rev-parse", "--short", "HEAD")
    return sortie if code == 0 and sortie else "aucun"


def sujets_depuis(racine: Path, depuis: str) -> list[str]:
    """Sujets des commits ajoutés à HEAD depuis `depuis` (un `git pull --rebase` de l'étape peut y mêler des commits d'autrui)."""
    code, sortie = git(racine, "log", "--format=%s", f"{depuis}..HEAD")
    return sortie.splitlines() if code == 0 and sortie else []


def etat_depot(racine: Path, distant: bool = True) -> dict:
    """index_lock, fichiers modifiés ou non suivis (hors ignorés), commits locaux absents de origin/main (None : non évalué)."""
    if distant and git(racine, "remote")[1].strip():
        git(racine, "fetch", "--quiet", "origin")  # une panne réseau laisse l'ancienne référence : on ne s'arrête pas pour cela
    _, statut = git(racine, "status", "--porcelain=v1", "--untracked-files=all", env={"GIT_OPTIONAL_LOCKS": "0"})
    code, n = git(racine, "rev-list", "--count", "origin/main..HEAD")
    return {"index_lock": (racine / ".git" / "index.lock").exists(),
            "sales": [l for l in statut.splitlines() if l.strip()],
            "en_avance": int(n) if code == 0 and n.isdigit() else None}


def empreinte_git(racine: Path) -> dict[str, str]:
    """Empreinte de l'intégrité de git : {« config » ou « hooks/<chemin> » : sha256 du contenu}. Avec `.git` en écriture pour
    Codex, un hook ou un réglage ajouté pendant une étape s'exécuterait plus tard hors du bac à sable (git commit de Claude ou
    de Sylvain). Les noms comptent autant que les contenus : un fichier ajouté ou supprimé change l'empreinte."""
    code, gitdir = git(racine, "rev-parse", "--absolute-git-dir")
    if code != 0 or not gitdir:
        return {"?": "git illisible"}
    base = Path(gitdir)
    res: dict[str, str] = {}
    config = base / "config"
    res["config"] = hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else "absent"
    hooks = base / "hooks"
    if hooks.is_dir():
        for f in sorted(p for p in hooks.rglob("*") if p.is_file() or p.is_symlink()):
            try:
                res[f"hooks/{f.relative_to(hooks)}"] = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                res[f"hooks/{f.relative_to(hooks)}"] = "illisible"
    return res


def differences_git(avant: dict[str, str], apres: dict[str, str]) -> list[str]:
    return sorted(k for k in set(avant) | set(apres) if avant.get(k) != apres.get(k))


def arret_propre(racine: Path, etape: Etape) -> list[str]:
    """D68, D70 : remet en place les seuls chemins de l'étape, un par un ; renvoie les commandes jouées (pour le journal)."""
    jouees = []
    for chemin in etape.checkout:
        code, _ = git(racine, "checkout", "--", chemin)
        jouees.append(f"git checkout -- {chemin} ({code})")
    for chemin in etape.clean:
        code, _ = git(racine, "clean", "-f", "--", chemin)
        jouees.append(f"git clean -f -- {chemin} ({code})")
    return jouees


# ------------------------------------------------------------------------------------------------------- exécution

def tuer_groupe(proc: subprocess.Popen, delai_arret_s: float) -> None:
    """SIGTERM sur tout le groupe de l'étape, puis SIGKILL : aucun enfant (git, fetch.py, un agent) ne survit à l'arrêt."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=delai_arret_s)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def lancer(etape: Etape, racine: Path, env: dict, delai_arret_s: float = 10.0) -> Resultat:
    debut = datetime.now()
    try:
        proc = subprocess.Popen(etape.commande, cwd=racine, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except FileNotFoundError as e:
        return Resultat(CODE_BINAIRE, "", f"binaire introuvable : {e}", False, 0.0)
    depasse = False
    try:
        out, err = proc.communicate(timeout=etape.delai_s)
    except subprocess.TimeoutExpired:
        depasse = True
        tuer_groupe(proc, delai_arret_s)
        try:
            out, err = proc.communicate(timeout=delai_arret_s)
        except subprocess.TimeoutExpired:
            out, err = "", "sortie perdue après l'arrêt du groupe"
    try:  # un enfant resté en arrière-plan après la fin normale de l'étape ne survit pas non plus
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return Resultat(proc.returncode if proc.returncode is not None else -9, out or "", err or "", depasse,
                    (datetime.now() - debut).total_seconds())


def version_codex(binaire: str, delai_s: float = 10.0, env: dict | None = None) -> str | None:
    """Version lue au lancement de l'étape (`<binaire> --version`) ; `None` si la lecture échoue : l'étape se lance quand même."""
    try:
        r = subprocess.run([binaire, "--version"], capture_output=True, text=True, timeout=delai_s, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    sortie = r.stdout.strip()
    return sortie.splitlines()[0] if r.returncode == 0 and sortie else None


def refus_permission(res: Resultat) -> list[str]:
    """Commandes ou fichiers dont la permission a été refusée (`permission_denials` du JSON de Claude), vide si rien ou illisible."""
    try:
        refus = json.loads(res.stdout).get("permission_denials") or []
    except (ValueError, AttributeError):
        return []
    return [str((r.get("tool_input") or {}).get("command") or (r.get("tool_input") or {}).get("file_path") or r.get("tool_name"))[:160]
            for r in refus if isinstance(r, dict)]


def cause_sans_json(res: Resultat) -> str:
    """Détail d'une sortie de Claude sans JSON : le code de sortie et ce que dit le lanceur (première ligne utile de stderr), pour que
    `passages.log` donne la cause. Stdout vide : Claude n'a rien rendu (lanceur ou Claude arrêté avant tout résultat)."""
    erreur = next((" ".join(l.split()) for l in res.stderr.splitlines() if l.strip()), "")[:200]
    sortie = " ".join(res.stdout.split())[:120]
    if not sortie:
        return f"aucune sortie de Claude (code {res.code})" + (f" : {erreur}" if erreur else "")
    return (f"sortie Claude illisible (JSON attendu, code {res.code}) : {sortie}" + (f" ; stderr : {erreur}" if erreur else ""))


def evaluer_claude(res: Resultat) -> tuple[int, str]:
    """(code, détail) : 0 seulement si exit 0, JSON lisible, subtype success, is_error faux. Les refus de permission se jugent
    à part (`refus_permission`, voir `Chaine.executer_etape`) : fatals sauf étape complète avec ses commits poussés
    ou son rapport de supervision écrit pendant l'étape."""
    try:
        d = json.loads(res.stdout)
    except ValueError:
        return (res.code if res.code else 1), cause_sans_json(res)
    if not isinstance(d, dict):
        return (res.code if res.code else 1), cause_sans_json(res)
    if res.code != 0:
        return res.code, f"code de sortie {res.code}"
    if d.get("is_error") or d.get("subtype") != "success":
        return 1, f"résultat Claude en erreur (subtype {d.get('subtype')!r}, is_error {d.get('is_error')!r})"
    return 0, "ok"


def sans_retour_claude(res: Resultat) -> bool:
    """Transport interrompu ou résultat illisible ; une erreur structurée ou un refus du lanceur reste fatal.

    Le vieux lanceur rend 2, stderr TimeoutExpired et stdout vide, sans positionner delai_depasse.
    Un JSON success reçu avant un délai (enfant gardant un tube ouvert) peut aussi être récupéré.
    Ce prédicat ne vaut jamais preuve de livraison : tous les contrôles portent ensuite sur le dépôt.
    """
    try:
        doc = json.loads(res.stdout)
    except ValueError:
        doc = None
    if isinstance(doc, dict) and ("subtype" in doc or "is_error" in doc):
        return res.delai_depasse and doc.get("subtype") == "success" and not doc.get("is_error")
    return (res.delai_depasse or res.code == 0 or bool(res.stdout.strip())
            or (res.code == 2 and res.stderr.strip() == "claude-cle : claude : appel impossible (TimeoutExpired)"))


def evaluer(etape: Etape, res: Resultat) -> tuple[int, str]:
    if res.code == CODE_BINAIRE:
        return CODE_BINAIRE, res.stderr
    if res.delai_depasse:
        return CODE_DELAI, f"délai dépassé ({etape.delai_s / 60:g} min), groupe de processus arrêté"
    if etape.agent == "claude":
        return evaluer_claude(res)
    return (0, "ok") if res.code == 0 else (res.code, f"code de sortie {res.code}")


def quota_codex_epuise(res: Resultat) -> bool:
    return bool(SIGNATURE_QUOTA_CODEX.search(res.stdout) or SIGNATURE_QUOTA_CODEX.search(res.stderr))


def reprise_quota_codex(res: Resultat) -> str | None:
    """Date de reprise citée par Codex (« try again at … »), telle quelle ; None si elle ne se lit pas."""
    for texte in (res.stderr, res.stdout):
        m = REPRISE_QUOTA_CODEX.search(texte)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def motif_reseau(etape: Etape, res: Resultat) -> str | None:
    """Motif d'un échec réseau reconnu sans ambiguïté (D122), sinon None. Claude : `is_error`, `terminal_reason` `api_error`, aucun
    jeton consommé et un motif réseau dans `result`. Codex : la ligne d'erreur de capacité relevée sur un vrai journal (des jetons
    ont pu être consommés et l'étape écrire avant l'échec : l'arrêt propre remet l'arbre en place avant la relance)."""
    if res.delai_depasse or res.code in (0, CODE_BINAIRE):
        return None
    if etape.agent == "codex":
        m = next((m for t in (res.stdout, res.stderr) if (m := MOTIF_RESEAU_CODEX.search(t))), None)
        return m.group(0).strip() if m else None
    try:
        d = json.loads(res.stdout)
        usage = d["usage"]
        jetons = sum(int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        m = CODES_RESEAU_CLAUDE.search(d["result"]) or PHRASE_RESEAU_CLAUDE.search(d["result"])  # le code précis d'abord
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return m.group(0) if d.get("is_error") is True and d.get("terminal_reason") == "api_error" and jetons == 0 and m else None


def resoudre_hote(hote: str) -> bool:
    try:
        socket.getaddrinfo(hote, 443)
        return True
    except OSError:
        return False


def ecrire_sortie(racine: Path, cfg: dict, jour: date, etape: Etape, res: Resultat, code: int, detail: str,
                  jouees: list[str], version: str | None = None, controle: str = "") -> Path:
    dossier = racine / cfg["chaine"]["sortie_dossier"]
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / f"{jour.isoformat()}-{etape.nom}.log"
    with f.open("a", encoding="utf-8") as h:  # ajout : une relance le même jour ne perd rien
        h.write(f"===== {datetime.now().isoformat(timespec='seconds')} étape {etape.nom} : code {code} ({detail}), {res.duree_s:.0f} s\n")
        if etape.agent == "codex":
            h.write(f"version codex : {version if version else 'null'}\n")
        for j in jouees:
            h.write(f"arrêt propre : {j}\n")
        h.write("----- stdout\n" + res.stdout.rstrip() + "\n----- stderr\n" + res.stderr.rstrip() + "\n")
        if controle:
            h.write("===== contrôle valider.py après l'étape\n" + controle.rstrip() + "\n")
    return f


def journaliser(racine: Path, perimetre: str, commit: str, code: int, cause: str = "") -> None:
    cause = re.sub(r"[|\r\n]+", " ", cause).strip()
    passages.ajouter(racine, passages.ligne(AGENT_JOURNAL, perimetre, 0, 0, commit, code, cause=cause))


def publier_selection_en_attente(racine: Path, jour: date) -> str | None:
    """Publie avant les passages les seules sorties de sélection déjà créées mais encore non publiées.

    Le minuteur de sélection peut avoir écrit les deux rapports hebdomadaires avant que la chaîne ne prenne
    son verrou. Les publier ici évite qu'ils soient pris pour des écritures étrangères par le contrôle 126.
    Toute autre modification continue de faire échouer le contrôle strict de `selection_auto`.
    """
    import selection_auto

    if not (racine / ".git").exists():  # appels unitaires du capteur hors dépôt Git
        return None
    try:
        changements = selection_auto.chemins_git(racine, "diff", "--name-only")
        changements |= selection_auto.chemins_git(racine, "diff", "--cached", "--name-only")
        changements |= selection_auto.chemins_git(racine, "ls-files", "--others", "--exclude-standard")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return f"sélection hebdomadaire en attente non vérifiable ({type(exc).__name__})"
    if not changements:
        return None
    if any(not selection_auto_est_sortie(p) for p in changements):
        return None  # l'étape ordinaire qualifiera l'arbre sale, sans publier un changement étranger
    try:
        selection_auto.publier(racine, jour)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return f"publication de la sélection hebdomadaire impossible ({type(exc).__name__})"
    return None


def selection_auto_est_sortie(chemin: str) -> bool:
    return re.fullmatch(r"rapports/selection/[0-9]{4}-W[0-9]{2}\.(?:json|md)", chemin) is not None


@contextmanager
def dossier_rapports_supervision(racine: Path, *, creer: bool = False):
    """Ancre chaque composant sans suivre de lien ni exiger la lecture des ancêtres."""
    racine = racine.absolute()  # resolve() suivrait précisément les liens à refuser
    if ".." in racine.parts:
        raise ValueError("racine de supervision contenant '..'")
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(racine.anchor, os.O_PATH | flags)
    try:
        for composant in racine.parts[1:]:
            suivant = os.open(composant, os.O_PATH | flags, dir_fd=fd)
            os.close(fd)
            fd = suivant
        if creer:
            try:
                os.mkdir("rapports", dir_fd=fd)
            except FileExistsError:
                pass  # l'ouverture ci-dessous refuse aussi les liens apparus entre-temps
        # listdir() et fsync() nécessitent un descripteur lisible du dossier final.
        suivant = os.open("rapports", os.O_RDONLY | flags, dir_fd=fd)
        os.close(fd)
        fd = suivant
        yield fd
    finally:
        os.close(fd)


def enregistrer_rapport_supervision(racine: Path, jour: date, debut: float, stdout: str) -> bool:
    """Récupère un résultat JSON sans is_error : au moins 100 caractères utiles, sans marqueur de refus manifeste."""
    try:
        doc = json.loads(stdout)
        if not isinstance(doc, dict) or doc.get("is_error"):
            return False
        resultat = doc.get("result")
        if not isinstance(resultat, str):
            return False
        resultat = resultat.strip()
        if (len(resultat) < LONGUEUR_RAPPORT_SUPERVISION_MIN
                or MARQUEUR_REFUS_SUPERVISION.search(re.sub(r"\s+", " ", resultat))):
            return False
        horodatage = datetime.now().astimezone().strftime("%H%M")
        nom = f"{jour.isoformat()}_{horodatage}-supervision.md"
        with dossier_rapports_supervision(racine, creer=True) as dossier:
            temporaire = f".supervision-{secrets.token_hex(16)}.tmp"
            fd = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=dossier)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fichier:
                    fichier.write(resultat + "\n")
                    fichier.flush()
                    # Le mtime automatique peut précéder debut d'un tic d'horloge du noyau.
                    # Seul le fichier neuf, encore ouvert exclusivement, est horodaté.
                    etat = os.fstat(fichier.fileno())
                    os.utime(fichier.fileno(), ns=(etat.st_atime_ns, time_ns()))
                    os.fsync(fichier.fileno())
                    etat = os.fstat(fichier.fileno())
                # Remplace l'entrée seule : ni un lien ni un lien physique préexistant n'est ouvert.
                os.replace(temporaire, nom, src_dir_fd=dossier, dst_dir_fd=dossier)
                os.fsync(dossier)
                return etat.st_mtime >= debut
            finally:
                try:
                    os.unlink(temporaire, dir_fd=dossier)
                except FileNotFoundError:
                    pass
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def rapport_supervision_ecrit(racine: Path, jour: date, debut: float) -> bool:
    """Au moins un rapport du jour, non vide, créé ou modifié depuis le début de l'étape."""
    try:
        with dossier_rapports_supervision(racine) as dossier:
            for nom in os.listdir(dossier):
                if not re.fullmatch(rf"{jour.isoformat()}_[0-9]{{4}}-supervision\.md", nom):
                    continue
                try:
                    etat = os.stat(nom, dir_fd=dossier, follow_symlinks=False)
                    if stat.S_ISREG(etat.st_mode) and etat.st_size > 0 and etat.st_mtime >= debut:
                        return True
                except OSError:
                    continue
    except (OSError, ValueError):
        pass
    return False


def nuls_malgre_nouveautes(racine: Path, etape: Etape, jour: date, debut: float) -> list[str]:
    """Périmètres dont le fichier du jour n'a ni élément ni écarté alors que le brut `raw/<p>-nouveautes.json`, écrit pendant
    l'étape, annonce des nouveautés : un compte nul contradictoire (le journal dirait « 0 éléments » d'un jour qui en a)."""
    nuls = []
    for p in etape.valider:
        brut, quotidien = racine / "raw" / f"{p}-nouveautes.json", racine / "docs" / "data" / p / f"{jour.isoformat()}.json"
        try:
            if not brut.is_file() or brut.stat().st_mtime < debut or not quotidien.is_file():
                continue
            nouveautes = json.loads(brut.read_text(encoding="utf-8")).get("nouveautes") or 0
            d = json.loads(quotidien.read_text(encoding="utf-8"))
        except (OSError, ValueError, AttributeError):
            continue
        if nouveautes and not d.get("elements") and not d.get("ecartes"):
            nuls.append(f"{p} : {nouveautes} nouveauté(s) au brut, aucun élément ni écarté dans le fichier du jour")
    return nuls


def resultat_incomplet(racine: Path, etape: Etape, jour: date, avant: str, debut: float, etat: dict) -> str | None:
    """Cause d'un faux succès (code 0 de l'agent, résultat non conforme), None si l'étape a produit ce qu'elle devait.
    `codex exec` rend 0 même quand l'agent s'arrête sur une erreur de commande : seul le résultat produit fait foi."""
    if etape.supervision:
        return None if rapport_supervision_ecrit(racine, jour, debut) else "aucun rapport de supervision écrit pendant l'étape"
    causes = []
    sujets = sujets_depuis(racine, avant)
    manquants = [p for p in etape.commits_attendus if not any(x.startswith(p) for x in sujets)]
    if manquants:
        causes.append(f"commit(s) attendu(s) absent(s) : {', '.join(manquants)}")
    if etat["sales"]:
        causes.append(f"arbre non propre à la fin de l'étape ({len(etat['sales'])} fichier(s) : "
                      + ", ".join(l[3:] for l in etat["sales"][:5]) + "), l'agent s'est arrêté avant son commit")
    causes += nuls_malgre_nouveautes(racine, etape, jour, debut)
    return " ; ".join(causes) or None


# --------------------------------------------------------------------------------------------- contrôle de valider.py

def commande_valider(racine: Path, perimetre: str, jour: date, kb: bool = False) -> list[str]:
    """`valider.py` seul : aucun tube ni redirection, l'orchestrateur lit le code de sortie du processus lui-même."""
    c = [sys.executable, str(racine / "scripts" / "valider.py"), "--perimetre", perimetre]
    c += ["--kb"] if kb else ["--date", jour.isoformat()]
    return c + ["--racine", str(racine)]


def controles_valider(etape: Etape) -> list[tuple[str, bool]]:
    """(périmètre, kb) à contrôler après l'étape : `valider` pour le quotidien, le produit `kb` avec `valider_kb` pour une étape kb."""
    return [(p, False) for p in etape.valider] + ([(etape.kb, True)] if etape.kb and etape.valider_kb else [])


def verifier_arbre(racine: Path, etape: Etape, jour: date, env: dict) -> tuple[bool, str, str]:
    """Relance `valider.py` pour chaque périmètre de l'étape. Renvoie (tout valide, détail court, sortie complète du journal)."""
    echecs, journal = [], []
    for perimetre, kb in controles_valider(etape):
        cmd = commande_valider(racine, perimetre, jour, kb)
        nom = f"valider.py --perimetre {perimetre}" + (" --kb" if kb else "")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=DELAI_VALIDATION_S, env=env, cwd=racine,
                               stdin=subprocess.DEVNULL)
            code, out, err = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            code, out, err = CODE_DELAI, "", f"délai dépassé ({DELAI_VALIDATION_S} s)"
        except OSError as e:
            code, out, err = CODE_BINAIRE, "", str(e)
        journal.append(f"{nom} : code {code}\n----- stdout\n{out.rstrip()}\n----- stderr\n{err.rstrip()}")
        if code != 0:
            premiere = next((l.strip() for l in (err + out).splitlines() if l.strip().startswith("-")), (err or out).strip()[:120])
            echecs.append(f"{nom} : code {code}" + (f" ({premiere[:160]})" if premiere else ""))
    return not echecs, " ; ".join(echecs), "\n".join(journal)


# ------------------------------------------------------------------------------------------------------ garde, kb

def garde(racine: Path, etape: Etape, jour: date, env: dict) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(racine / "scripts" / "garde.py"), "--etape", etape.garde, "--date", jour.isoformat(),
                        "--json", "--racine", str(racine)], capture_output=True, text=True, timeout=120, env=env, cwd=racine)
    try:
        d = json.loads(r.stdout)
        return d["code"], d.get("motif") or "ok"
    except (ValueError, KeyError):
        return (r.returncode or 2), f"garde illisible : {r.stderr.strip()[:200]}"


def adoptions_en_attente(racine: Path, perimetre: str, entrees: dict) -> int:
    """D67 : entrées de ce périmètre citées dans la section « Adoptions » de PROGRESSION.md et pas encore passées en `utilise`
    (équivalent, sans rien écrire, de `catalogue.py adoptions --dry-run`)."""
    from deltalib.kb import catalogue as cat
    from deltalib.kb.modeles import PRODUITS_PAR_PERIMETRE
    miens = [k for k in cat.adoptions(racine) if any(k.startswith(f"{pr}-") for pr in PRODUITS_PAR_PERIMETRE[perimetre])]
    copie = {k: dict(v) for k, v in entrees.items()}  # appliquer_adoptions modifie ce qu'on lui donne : jamais la base réelle
    return len(cat.appliquer_adoptions(copie, [k for k in miens if k in copie]))


def lots_dus(racine: Path, perimetre: str) -> int:
    """Nombre d'éléments dus pour une étape kb : adoptions déclarées dans PROGRESSION.md pas encore appliquées (le signal le
    plus fiable), lot `perimees` (D64-bis), lot `exemples` (D91), lot `provenance` (D127) et entrées à commenter des lots ordinaires."""
    sys.path.insert(0, str(racine / "scripts"))
    from deltalib.contexte import deprecies as deprecies_contexte, empreintes as empreintes_sections
    from deltalib.kb import catalogue as cat
    entrees = cat.charger(racine, perimetre)
    dues = adoptions_en_attente(racine, perimetre, entrees)
    if not cat.PERIMEES_SUSPENDU:
        try:
            rejugements = cat.charger_rejugements(racine)
        except (ValueError, OSError) as err:
            print(f"! AVERTISSEMENT : {err} ; poursuite sans rejugements D78", file=sys.stderr)
            rejugements = {}
        dues += len(cat.perimees_detail(entrees, empreintes_sections(racine), deprecies_contexte(racine), maximum=None,
                                       rejugements=rejugements))
    dues += len(cat.exemples_detail(entrees, maximum=None))  # D91 : lot `exemples`
    dues += len(cat.provenance_detail(entrees, maximum=None))  # D127 : lot `provenance`
    dues += sum(l["a_commenter"] for l in cat.lots(entrees, perimetre))
    return dues


# ------------------------------------------------------------------------------------------------------------ chaîne

class Chaine:
    def __init__(self, racine: Path, cfg: dict, etapes: list[Etape], jour: date | None = None, distant: bool = True,
                 compte_lots=lots_dus, dormir=sleep, maintenant=datetime.now, resoudre=resoudre_hote) -> None:
        self.racine, self.cfg, self.etapes = racine, cfg, etapes
        self.jour = jour or date.today()
        self.distant = distant
        self.compte_lots = compte_lots
        self.dormir, self.maintenant, self.resoudre = dormir, maintenant, resoudre  # injectés par les tests
        self.issues: list[Issue] = []

    def _fin(self, etape: Etape, code: int, ok: bool, arret: bool, detail: str, commit: str = "aucun") -> Issue:
        code_journal = 0 if ok else code
        saut = ok and code in (*CODES_GARDE_SAUTEE, CODE_NON_LANCEE, CODE_SANS_LOT, CODE_QUOTA_EPUISE)
        journaliser(self.racine, etape.nom, commit, code_journal, f"saut: {detail}" if saut else detail)
        issue = Issue(etape.nom, code, ok, arret, detail, commit)
        self.issues.append(issue)
        return issue

    def relance_interdite(self, quand: datetime) -> bool:
        """D122 : aucune tentative ne commence entre `relances_limite` (07:30) et `fenetre_fin` (08:00), la fin de la fenêtre de la chaîne."""
        ch = self.cfg["chaine"]
        return heure.fromisoformat(ch["relances_limite"]) <= quand.time() < heure.fromisoformat(ch["fenetre_fin"])

    def attendre_reseau(self, delai_s: float, hote: str, dns_suffit: bool) -> None:
        """Attente avant une relance. Panne DNS : relance dès que l'hôte se résout (au plus `delai_s`). Autre motif : `delai_s` pleins,
        puis attente de la résolution DNS (au plus `delai_s` de plus) ; la relance part ensuite dans tous les cas."""
        ecoule, minimum, plafond = 0.0, (0.0 if dns_suffit else delai_s), (delai_s if dns_suffit else 2 * delai_s)
        while ecoule < plafond:
            if ecoule >= minimum and self.resoudre(hote):
                return
            pas = min(PAS_DNS_S, (minimum if ecoule < minimum else plafond) - ecoule)
            self.dormir(pas)
            ecoule += pas

    def lancer_avec_relances(self, etape: Etape, env: dict, git_avant: dict[str, str]) -> tuple[Resultat, int, str]:
        """Lance l'étape ; sur un échec réseau (`motif_reseau`), arrêt propre, attente, nouvelle tentative (trois au plus, délais de
        `chaine.relances_reseau_s`). Renvoie le résultat de la dernière tentative, son code et son détail (CODE_RESEAU à l'abandon)."""
        ch = self.cfg["chaine"]
        delais = ch["relances_reseau_s"]
        hote = ch["reseau_hotes"][etape.agent]
        tentative = 1
        tete_avant = tete_courte(self.racine)
        repli = ""
        while True:
            res = lancer(etape, self.racine, env, ch["arret_delai_s"])
            code, detail = evaluer(etape, res)
            if code == 5 and etape.agent == "claude" and etape.commande_abonnement:
                # Le lanceur peut aussi rendre 5 après une réponse API sans crédit : ne jamais rejouer un passage
                # ayant déjà écrit/commité. Un refus de permission ou un délai ne déclenche pas de repli.
                etat = etat_depot(self.racine, self.distant)
                if (refus_permission(res) or etat["index_lock"] or etat["sales"] or etat["en_avance"]
                        or tete_courte(self.racine) != tete_avant
                        or differences_git(git_avant, empreinte_git(self.racine))):
                    return res, code, "code 5 : repli abonnement refusé, résultat ou dépôt déjà modifié"
                repli = "repli abonnement après code 5 de claude-cle"
                ecrire_sortie(self.racine, self.cfg, self.jour, etape, res, 5, repli, [])
                journaliser(self.racine, f"{etape.nom}-repli-abonnement", "aucun", 0, "repli abonnement après code 5 de claude-cle")
                etape = replace(etape, commande=etape.commande_abonnement, commande_abonnement=[])
                env["DELTA_CLAUDE_MODE"] = "abonnement"
                if etape.garde:
                    garde_code, motif = garde(self.racine, etape, self.jour, env)
                    if garde_code:
                        return replace(res, garde_abonnement=True), garde_code, f"{repli} ; garde abonnement (code {garde_code}) : {motif}"
                continue
            if repli:
                detail = f"{repli} ; {detail}"
            motif = motif_reseau(etape, res) if code != 0 else None
            if not motif:
                return res, code, detail
            total = f"{tentative} tentative{'s' if tentative > 1 else ''}"
            dns = bool(MOTIFS_DNS.search(motif))
            if tentative > len(delais):
                return res, CODE_RESEAU, f"réseau : étape abandonnée après {total} ({motif})"
            delai = delais[tentative - 1]
            if self.relance_interdite(self.maintenant() + timedelta(seconds=0 if dns else delai)):
                return res, CODE_RESEAU, f"réseau : relance interdite en fin de fenêtre ({ch['relances_limite']}), abandon après {total} ({motif})"
            jouees = arret_propre(self.racine, etape) if etape.checkout or etape.clean else []
            etat = etat_depot(self.racine, self.distant)
            if (etat["index_lock"] or etat["sales"] or etat["en_avance"] or differences_git(git_avant, empreinte_git(self.racine))):
                return res, code, detail  # état différent d'avant l'étape : pas de relance, le chemin ordinaire le qualifie (126, 15)
            ecrire_sortie(self.racine, self.cfg, self.jour, etape, res, code,
                          f"tentative {tentative}/{len(delais) + 1} échouée, réseau ({motif}) : relance après {delai // 60:g} min d'attente au plus", jouees)
            self.attendre_reseau(delai, hote, dns)
            if self.relance_interdite(self.maintenant()):
                return res, CODE_RESEAU, f"réseau : relance interdite en fin de fenêtre ({ch['relances_limite']}), abandon après {total} ({motif})"
            tentative += 1

    def executer_etape(self, etape: Etape) -> Issue:
        racine = self.racine
        env = environnement(self.cfg, etape.supervision, etape.env_extra)
        if etape.garde:
            code, motif = garde(racine, etape, self.jour, env)
            if code in CODES_GARDE_SAUTEE:
                return self._fin(etape, code, True, False, f"sautée par la garde : {motif}")
            if code != 0:
                return self._fin(etape, code, False, True, f"arrêtée par la garde (code {code}) : {motif}")
        if etape.kb and self.compte_lots(racine, etape.kb) == 0:
            return self._fin(etape, CODE_SANS_LOT, True, False, "aucun lot dû")
        avant = tete_courte(racine)
        git_avant = empreinte_git(racine)
        version = version_codex(etape.commande[0], env=env) if etape.agent == "codex" else None
        debut = datetime.now().timestamp()
        res, code, detail = self.lancer_avec_relances(etape, env, git_avant)
        if res.garde_abonnement and code in CODES_GARDE_SAUTEE:  # garde abonnement, sans lancement de l'agent
            ecrire_sortie(racine, self.cfg, self.jour, etape, res, code, detail, [], version)
            return self._fin(etape, code, True, False, detail)
        if etape.supervision and code == 0 and not refus_permission(res) and not rapport_supervision_ecrit(racine, self.jour, debut):
            enregistrer_rapport_supervision(racine, self.jour, debut, res.stdout)
        refus = refus_permission(res) if etape.agent == "claude" else []
        if refus and code != 0:  # étape déjà en échec : le refus s'ajoute à la cause, il reste fatal
            detail = f"{len(refus)} permission(s) refusée(s) : " + " ; ".join(refus[:5]) + f" ; {detail}"
            code = CODE_PERMISSION
        jouees: list[str] = []
        etat = etat_depot(racine, self.distant)
        # Avant tout checkout/clean : un nettoyage ne doit pas transformer un travail inachevé en livraison.
        if etape.agent == "claude" and not etape.supervision and code != 0 and sans_retour_claude(res):
            cause = resultat_incomplet(racine, etape, self.jour, avant, debut, etat)
            if not etape.commits_attendus:
                cause = "aucun commit attendu déclaré pour cette étape"
            elif etat["en_avance"] != 0:
                cause = (cause + " ; " if cause else "") + "commits non poussés ou origin/main illisible"
            if cause:
                detail += " ; livraison non conforme : " + cause
            elif not refus:
                code, detail = 0, "livrée sans retour : " + detail + " ; tous les commits attendus poussés, arbre propre"
        stop = False
        if etat["index_lock"]:  # D21 : jamais supprimé par l'orchestrateur
            code, detail, stop = CODE_ETAT, ".git/index.lock présent après l'étape : non supprimé (D21)", True
        else:
            if code == 0 and not refus:  # `codex exec` rend 0 même sur une erreur de commande : le résultat produit fait foi (un refus a son propre contrôle, 125)
                cause = resultat_incomplet(racine, etape, self.jour, avant, debut, etat)
                if cause:
                    code, detail = CODE_INCOMPLET, "résultat incomplet malgré le code 0 de l'agent : " + cause
            if code != 0 or etat["sales"]:
                jouees = arret_propre(racine, etape) if etape.checkout or etape.clean else []
                etat = etat_depot(racine, False)
            if etat["sales"]:
                code, stop = CODE_ETAT, True
                detail = f"arbre non propre après l'étape ({len(etat['sales'])} fichier(s)) : " + ", ".join(
                    l[3:] for l in etat["sales"][:8])
            elif etat["en_avance"]:
                code, stop = 15, True
                detail = f"{etat['en_avance']} commit(s) local(aux) non poussé(s) : la chaîne s'arrête, rien n'est poussé"
        avertissement = None
        if refus and code == 0 and not stop:  # étape réussie avec des refus : le résultat attendu doit avoir été produit
            cause = None
            if etape.supervision:
                if not rapport_supervision_ecrit(racine, self.jour, debut):
                    cause = "aucun rapport de supervision écrit pendant l'étape"
                elif etat["en_avance"] != 0:
                    cause = "commits non poussés ou origin/main illisible"
            else:
                sujets = sujets_depuis(racine, avant)
                manquants = [p for p in etape.commits_attendus if not any(x.startswith(p) for x in sujets)]
                if not etape.commits_attendus or manquants or etat["en_avance"] != 0:
                    cause = ("aucun commit attendu déclaré pour cette étape" if not etape.commits_attendus else
                             f"commit(s) attendu(s) absent(s) : {', '.join(manquants)}" if manquants else
                             "commits non poussés ou origin/main illisible")
            if cause:
                code = CODE_PERMISSION
                detail = (f"{len(refus)} permission(s) refusée(s) et l'étape n'a pas produit son résultat ({cause}) : "
                          + " ; ".join(refus[:5]))
            else:
                avertissement = f"{len(refus)} permission(s) refusée(s), non fatale(s) : " + " ; ".join(refus[:5])
                detail = "ok avec avertissement : " + avertissement
        modifies = differences_git(git_avant, empreinte_git(racine))
        quota = (etape.agent == "codex" and code != 0 and code not in (CODE_DELAI, CODE_BINAIRE) and not stop and not modifies
                 and not etat["sales"] and not etat["en_avance"] and quota_codex_epuise(res))
        if quota:  # refus constaté de l'agent (pas un seuil) : étape sautée, la chaîne continue
            code = CODE_QUOTA_EPUISE
            reprise = reprise_quota_codex(res)
            detail = "sautée : quota de l'agent épuisé (Codex a refusé de tourner)" + (f" ; reprise annoncée : {reprise}" if reprise else "")
        if modifies:  # priorité sur tout autre motif : l'intégrité de git ne se rétablit pas automatiquement
            code, stop = CODE_ETAT, True
            detail = "hooks ou config git modifiés pendant l'étape : " + ", ".join(modifies[:8]) + " ; rien n'est rétabli, la chaîne s'arrête"
        controle = ""
        if code == 0 and not stop and not etape.supervision and controles_valider(etape):
            valide, resume, controle = verifier_arbre(racine, etape, self.jour, env)
            if not valide:  # le push est déjà fait : on signale, on ne rétablit rien ; la chaîne continue (périmètres indépendants)
                code, detail = CODE_VALIDATION, "valider.py échoue sur l'arbre laissé par l'étape (déjà poussé) : " + resume
        if code not in (0, CODE_QUOTA_EPUISE, CODE_VALIDATION) and not stop and not etape.supervision:
            stop = True  # une étape en échec arrête la chaîne (la supervision, elle, reste lancée)
        ecrire_sortie(racine, self.cfg, self.jour, etape, res, code, detail, jouees, version, controle)
        apres = tete_courte(racine)
        issue = self._fin(etape, code, code in (0, CODE_QUOTA_EPUISE), stop, detail, apres if apres != avant else "aucun")
        if avertissement and code == 0:  # avertissement journalisé : la supervision le relève, la chaîne continue
            journaliser(racine, f"{etape.nom}-refus", "aucun", 0,
                        "permission refusée, résultat conforme et dépôt propre")
        return issue

    def releve_x(self) -> None:
        """Capteur de la liste X (décisions du 22/10/2026), avant la première étape : relevé par l'API X (jeton du trousseau) dans
        l'environnement de la chaîne. Jamais bloquant : le statut du relevé est dans `raw/x-liste.json`, l'analyseur `x_liste` le remonte dans
        `sources_en_echec`. Les seuls IDs sont préparés dans raw/, puis publiés avant les étapes par un commit dédié : ils
        survivent au checkout/clean d'actu. Un échec de publication ne laisse ni arbre sale ni commit en avance et ne bloque
        pas la chaîne. Inactif sans la clé `chaine.capteur_x`."""
        c = self.cfg["chaine"].get("capteur_x")
        if not c:
            return
        code = 0
        try:
            (self.racine / capteur_x.FICHIER_IDS_ATTENTE).unlink(missing_ok=True)
            res = subprocess.run([sys.executable, str(self.racine / "scripts" / "capteur_x.py"), "--racine", str(self.racine), "--ids-en-attente"],
                                 env=environnement(self.cfg), cwd=self.racine, stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, timeout=c.get("delai_s", 180))
            code = res.returncode
        except Exception:   # y compris le délai : le passage continue sans la liste X
            code = 124
        journaliser(self.racine, "capteur-x", "aucun", code,
                    "relevé réussi" if code == 0 else f"processus de relevé en échec (code {code})")
        if code == 0:
            publication, commit, message = capteur_x.publier_ids(self.racine)
            print(f"capteur X : {message}", flush=True)
            journaliser(self.racine, "capteur-x-publication", commit, publication, message)

    def purge_x(self) -> None:
        """Fin de chaîne : purge du texte dans raw/ ; les seuls IDs publics restent (décisions des 22 et 23/10/2026)."""
        if self.cfg["chaine"].get("capteur_x"):
            try:
                capteur_x.purger(self.racine)
            except Exception:
                journaliser(self.racine, "capteur-x-purge", "aucun", 1, "purge du texte X impossible")

    def executer(self) -> int:
        erreur_selection = publier_selection_en_attente(self.racine, self.jour)
        if erreur_selection:
            journaliser(self.racine, "selection-publication", "aucun", 1, erreur_selection)
        self.releve_x()
        arret_par: str | None = None
        for etape in [e for e in self.etapes if not e.supervision]:
            if arret_par:
                self._fin(etape, CODE_NON_LANCEE, True, False, f"non lancée : chaîne arrêtée par {arret_par}")
                continue
            issue = self.executer_etape(etape)
            if issue.arret_chaine:
                arret_par = issue.etape
        for etape in [e for e in self.etapes if e.supervision]:  # toujours, même après un échec
            self.executer_etape(etape)
        self.purge_x()
        echec_etape = any(not i.ok for i in self.issues)
        echec = echec_etape or bool(erreur_selection)
        journaliser(self.racine, "chaine", "aucun", 1 if echec else 0,
                    "au moins une étape en échec" if echec_etape else
                    "étapes terminées, publication de la sélection en échec" if echec else
                    "toutes les étapes terminées sans échec")
        return 1 if echec else 0


def etapes_a_lancer(cfg: dict, etapes: list[Etape], option: str | None = None) -> list[Etape]:
    """Étapes de cette exécution. `--etapes a,b` (essais) ne garde que celles-là ; sinon la liste `chaine.etapes_actives` de la
    configuration (paliers de déploiement) ; sans liste, toutes. La supervision reste lancée dans le cas de la configuration."""
    noms = {e.nom for e in etapes}
    if option:
        voulues = [x.strip() for x in option.split(",") if x.strip()]
        inconnues = [x for x in voulues if x not in noms]
        if inconnues:
            raise ValueError(f"étape(s) inconnue(s) {inconnues}")
        return [e for e in etapes if e.nom in voulues]
    actives = cfg["chaine"].get("etapes_actives")
    if actives is None:
        return etapes
    inconnues = [x for x in actives if x not in noms or x == "supervision"]
    if inconnues:
        raise ValueError(f"chaine.etapes_actives : étape(s) inconnue(s) ou implicite(s) {inconnues} (la supervision tourne toujours)")
    return [e for e in etapes if e.supervision or e.nom in actives]


def ecrire_pid(racine: Path, cfg: dict) -> None:
    """Écrit le PID dans le fichier de verrou déjà tenu par passage-auto.sh : la garde y compare DELTA_CHAINE_PID."""
    (racine / cfg["chaine"]["verrou"]).write_text(f"{os.getpid()}\n", encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="orchestrateur.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", type=Path, default=RACINE, help=argparse.SUPPRESS)
    p.add_argument("--config", type=Path, default=CONFIG, help="fichier de configuration (défaut : scripts/orchestrateur.toml)")
    p.add_argument("--etapes", help="liste d'étapes séparées par des virgules, dans l'ordre de la configuration (essai de réception)")
    p.add_argument("--liste", action="store_true", help="affiche les commandes sans rien lancer")
    a = p.parse_args(argv)
    cfg = charger_config(a.config)
    etapes = construire_etapes(cfg, a.racine)
    try:
        etapes = etapes_a_lancer(cfg, etapes, a.etapes)
    except ValueError as e:
        print(f"orchestrateur.py : {e}", file=sys.stderr)
        return 2
    if a.liste:
        for e in etapes:
            print(f"{e.nom} (délai {e.delai_s / 60:g} min) : " + " ".join(
                (c if len(c) < 80 else c[:77] + "...") for c in e.commande))
        return 0
    ecrire_pid(a.racine, cfg)
    return Chaine(a.racine, cfg, etapes).executer()


if __name__ == "__main__":
    sys.exit(main())
