#!/usr/bin/env python3
"""Delta — orchestrateur des passages automatiques (D70). Lancé par `scripts/passage-auto.sh`, qui tient le verrou
`.git/delta-passage.lock` (flock) pendant toute la chaîne ; jamais lancé directement par un timer.

Chaîne, dans l'ordre, chaque étape ne démarrant qu'à la fin de la précédente :
  delta (Claude : claude, actu) -> codex-delta (Codex : openai) -> delta-kb (Claude) -> codex-delta-kb (Codex)
  -> supervision (Claude, lecture seule), TOUJOURS lancée, même si une étape a échoué.

Pour chaque étape, sans aucun LLM :
1. garde `scripts/garde.py --etape <étape>` : code 11 (quota Claude) ou 12 (déjà fait) = étape sautée, la chaîne continue ;
   10, 13, 14, 15 ou toute autre erreur = la chaîne s'arrête (la supervision reste lancée) ;
2. étapes kb : sautées (code 129) quand aucun lot n'est dû ;
3. lancement dans son propre groupe de processus, sous délai maximal ; dépassement ou échec : SIGTERM puis SIGKILL sur tout le
   groupe (un enfant ne survit pas), puis arrêt propre limité aux chemins de l'étape (`git checkout --` et `git clean -f --`) ;
4. succès d'une étape Claude : code 0, JSON lisible, `subtype` success, `is_error` faux, aucun `permission_denials` ;
   étape Codex : code 0. Dans les deux cas l'état final doit être propre (arbre sans fichier modifié, pas de `.git/index.lock`,
   aucun commit local absent de `origin/main`), et `.git/hooks/` (noms et contenus) comme `.git/config` doivent être
   inchangés (un hook ou un réglage git écrit par une étape s'exécuterait ensuite hors de son bac à sable : code 126),
   sinon la chaîne s'arrête : l'orchestrateur ne pousse jamais, ne supprime
   jamais un `.git/index.lock` (D21) et ne touche jamais à `raw/` (historique du brut, D72) ;
5. une ligne `orchestrateur` dans `rapports/passages.log` (scripts/passages.py) et la sortie de l'étape dans
   `rapports/auto/AAAA-MM-JJ-<étape>.log` (jamais l'environnement).

Colonne « code » de la ligne `orchestrateur | <étape>` : 0 réussie ; 10 à 15 arrêtée par la garde (11 quota Claude, 12 déjà
fait : sautée) ; 124 délai dépassé ; 125 permission refusée (Claude) ; 126 état final non conforme (arbre sale, `.git/index.lock`, hooks ou config git modifiés) ;
127 binaire introuvable ; 128 non lancée (chaîne arrêtée plus tôt) ; 129 sautée, aucun lot dû ; autre : code de sortie de l'agent.
Dernière ligne : `orchestrateur | chaine`, code 0 si aucune étape n'a échoué, 1 sinon.

Aucun appel à `claude` ou `codex` hors de `lancer()` ; les tests y injectent de fausses commandes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import signal
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import passages  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).resolve().parent / "orchestrateur.toml"
AGENT_JOURNAL = "orchestrateur"

CODE_DELAI, CODE_PERMISSION, CODE_ETAT, CODE_BINAIRE, CODE_NON_LANCEE, CODE_SANS_LOT = 124, 125, 126, 127, 128, 129
CODES_GARDE_SAUTEE = (11, 12)  # l'étape est sautée, la chaîne continue ; tout autre code de garde arrête la chaîne


@dataclass
class Etape:
    nom: str
    agent: str                      # claude | codex
    commande: list[str]             # complète ; construite par construire_etapes, ou fausse dans les tests
    delai_s: float
    garde: str | None = None        # valeur de `garde.py --etape` ; None : pas de garde (supervision)
    kb: str | None = None           # périmètre kb : étape sautée quand aucun lot n'est dû
    supervision: bool = False
    checkout: list[str] = field(default_factory=list)
    clean: list[str] = field(default_factory=list)
    env_extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Resultat:
    code: int
    stdout: str
    stderr: str
    delai_depasse: bool
    duree_s: float


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
    if "XDG_RUNTIME_DIR" in os.environ:
        env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
    env.update(extra or {})
    return env


def commande_claude(cfg: dict, e: dict, racine: Path, prompt: str) -> list[str]:
    """Syntaxe du `claude --help` de la version installée (2.1.286) : -p, --permission-mode dontAsk, --permission-prompts none
    (tout ce qui demanderait une approbation est refusé, jamais accordé), --strict-mcp-config (aucun serveur MCP),
    --output-format json (le résultat porte `permission_denials`). Jamais --dangerously-skip-permissions ni bypassPermissions."""
    c = [_chemin(cfg["claude"]["bin"]), "-p", prompt, "--permission-mode", "dontAsk", "--permission-prompts", "none",
         "--strict-mcp-config", "--output-format", "json"]
    if e.get("modele"):
        c += ["--model", e["modele"]]
    if e.get("effort"):
        c += ["--effort", e["effort"]]
    if e.get("supervision"):
        c += ["--setting-sources", "", "--settings", str(racine / e["settings"])]
    else:
        c += ["--setting-sources", cfg["claude"]["sources_etapes"]]
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
        etapes.append(Etape(nom=nom, agent=e["agent"], commande=cmd, delai_s=e["delai_min"] * 60, garde=e.get("garde"),
                            kb=e.get("kb"), supervision=bool(e.get("supervision")), checkout=list(e.get("checkout", [])),
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


def evaluer_claude(res: Resultat) -> tuple[int, str]:
    """(code, détail) : 0 seulement si exit 0, JSON lisible, subtype success, is_error faux, aucun refus de permission."""
    try:
        d = json.loads(res.stdout)
    except ValueError:
        return (res.code if res.code else 1), "sortie Claude illisible (JSON attendu)"
    refus = d.get("permission_denials") or []
    if refus:
        cmds = [str((r.get("tool_input") or {}).get("command") or (r.get("tool_input") or {}).get("file_path") or r.get("tool_name"))
                for r in refus if isinstance(r, dict)]
        return CODE_PERMISSION, f"{len(refus)} permission(s) refusée(s) : " + " ; ".join(c[:120] for c in cmds[:5])
    if res.code != 0:
        return res.code, f"code de sortie {res.code}"
    if d.get("is_error") or d.get("subtype") != "success":
        return 1, f"résultat Claude en erreur (subtype {d.get('subtype')!r}, is_error {d.get('is_error')!r})"
    return 0, "ok"


def evaluer(etape: Etape, res: Resultat) -> tuple[int, str]:
    if res.code == CODE_BINAIRE:
        return CODE_BINAIRE, res.stderr
    if res.delai_depasse:
        return CODE_DELAI, f"délai dépassé ({etape.delai_s / 60:g} min), groupe de processus arrêté"
    if etape.agent == "claude":
        return evaluer_claude(res)
    return (0, "ok") if res.code == 0 else (res.code, f"code de sortie {res.code}")


def ecrire_sortie(racine: Path, cfg: dict, jour: date, etape: Etape, res: Resultat, code: int, detail: str,
                  jouees: list[str]) -> Path:
    dossier = racine / cfg["chaine"]["sortie_dossier"]
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / f"{jour.isoformat()}-{etape.nom}.log"
    with f.open("a", encoding="utf-8") as h:  # ajout : une relance le même jour ne perd rien
        h.write(f"===== {datetime.now().isoformat(timespec='seconds')} étape {etape.nom} : code {code} ({detail}), {res.duree_s:.0f} s\n")
        for j in jouees:
            h.write(f"arrêt propre : {j}\n")
        h.write("----- stdout\n" + res.stdout.rstrip() + "\n----- stderr\n" + res.stderr.rstrip() + "\n")
    return f


def journaliser(racine: Path, perimetre: str, commit: str, code: int) -> None:
    passages.ajouter(racine, passages.ligne(AGENT_JOURNAL, perimetre, 0, 0, commit, code))


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
    plus fiable), lot `perimees` (D64-bis) et entrées à commenter des lots ordinaires."""
    sys.path.insert(0, str(racine / "scripts"))
    from deltalib.contexte import deprecies as deprecies_contexte, empreintes as empreintes_sections
    from deltalib.kb import catalogue as cat
    entrees = cat.charger(racine, perimetre)
    dues = adoptions_en_attente(racine, perimetre, entrees)
    if not cat.PERIMEES_SUSPENDU:
        dues += len(cat.perimees_detail(entrees, empreintes_sections(racine), deprecies_contexte(racine), maximum=None))
    dues += sum(l["a_commenter"] for l in cat.lots(entrees, perimetre))
    return dues


# ------------------------------------------------------------------------------------------------------------ chaîne

class Chaine:
    def __init__(self, racine: Path, cfg: dict, etapes: list[Etape], jour: date | None = None, distant: bool = True,
                 compte_lots=lots_dus) -> None:
        self.racine, self.cfg, self.etapes = racine, cfg, etapes
        self.jour = jour or date.today()
        self.distant = distant
        self.compte_lots = compte_lots
        self.issues: list[Issue] = []

    def _fin(self, etape: Etape, code: int, ok: bool, arret: bool, detail: str, commit: str = "aucun") -> Issue:
        journaliser(self.racine, etape.nom, commit, code)
        issue = Issue(etape.nom, code, ok, arret, detail, commit)
        self.issues.append(issue)
        return issue

    def executer_etape(self, etape: Etape) -> Issue:
        racine = self.racine
        env = environnement(self.cfg, etape.supervision, etape.env_extra)
        if etape.garde:
            code, motif = garde(racine, etape, self.jour, env)
            if code in CODES_GARDE_SAUTEE:
                return self._fin(etape, code, True, False, f"sautée par la garde (code {code}) : {motif}")
            if code != 0:
                return self._fin(etape, code, False, True, f"arrêtée par la garde (code {code}) : {motif}")
        if etape.kb and self.compte_lots(racine, etape.kb) == 0:
            return self._fin(etape, CODE_SANS_LOT, True, False, "aucun lot dû")
        avant = tete_courte(racine)
        git_avant = empreinte_git(racine)
        res = lancer(etape, racine, env, self.cfg["chaine"]["arret_delai_s"])
        code, detail = evaluer(etape, res)
        jouees: list[str] = []
        etat = etat_depot(racine, self.distant)
        stop = False
        if etat["index_lock"]:  # D21 : jamais supprimé par l'orchestrateur
            code, detail, stop = CODE_ETAT, ".git/index.lock présent après l'étape : non supprimé (D21)", True
        else:
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
        modifies = differences_git(git_avant, empreinte_git(racine))
        if modifies:  # priorité sur tout autre motif : l'intégrité de git ne se rétablit pas automatiquement
            code, stop = CODE_ETAT, True
            detail = "hooks ou config git modifiés pendant l'étape : " + ", ".join(modifies[:8]) + " ; rien n'est rétabli, la chaîne s'arrête"
        if code != 0 and not stop and not etape.supervision:
            stop = True  # une étape en échec arrête la chaîne (la supervision, elle, reste lancée)
        ecrire_sortie(racine, self.cfg, self.jour, etape, res, code, detail, jouees)
        apres = tete_courte(racine)
        return self._fin(etape, code, code == 0, stop, detail, apres if apres != avant else "aucun")

    def executer(self) -> int:
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
        echec = any(not i.ok for i in self.issues)
        journaliser(self.racine, "chaine", "aucun", 1 if echec else 0)
        return 1 if echec else 0


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
    if a.etapes:
        voulues = [x.strip() for x in a.etapes.split(",") if x.strip()]
        inconnues = [x for x in voulues if x not in {e.nom for e in etapes}]
        if inconnues:
            print(f"orchestrateur.py : étape(s) inconnue(s) {inconnues}", file=sys.stderr)
            return 2
        etapes = [e for e in etapes if e.nom in voulues]
    if a.liste:
        for e in etapes:
            print(f"{e.nom} (délai {e.delai_s / 60:g} min) : " + " ".join(
                (c if len(c) < 80 else c[:77] + "...") for c in e.commande))
        return 0
    ecrire_pid(a.racine, cfg)
    return Chaine(a.racine, cfg, etapes).executer()


if __name__ == "__main__":
    sys.exit(main())
