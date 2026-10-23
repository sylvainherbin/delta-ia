"""Capteur de la liste X officielle (décisions de Sylvain du 22/10/2026) : relevé par l'API X et identifiants publics pour les intégrations officielles.

La liste (six comptes officiels d'Anthropic et d'OpenAI) est lue par `GET /2/lists/{id}/tweets`. L'endpoint n'a ni `since_id` ni
`start_time` : le capteur lit la page la plus récente, s'arrête dès qu'elle contient un post déjà vu (identifiants `x-<id>` de
`state/*.json`, sans leur texte) et ne pagine que si la page est faite de posts tous nouveaux. Facturation de X : 0,005 $ par
post lu, 0,010 $ par utilisateur lu (crédits prépayés) ; chaque nuit ajoute une ligne de comptes à `raw/x-cout.jsonl`.

Jeton : `secret-tool lookup service x compte delta` (trousseau du K8), lu au moment de l'appel ; jamais écrit sur disque, jamais
journalisé, jamais dans le dépôt, un message ou une erreur.

Le brut est écrit dans `raw/x-liste.json` (ignoré par git) ; l'analyseur `x_liste` en tire les éléments, et le texte des posts est
purgé à la fin du passage (`purger`) : Delta-IA garde les conclusions, les références et les pistes, jamais le texte.
Seuls `maj` et les 30 identifiants les plus récents sont publiés dans `docs/data/actu/x-ids.json` ; X rend les posts chez le visiteur.

Jamais d'exception vers l'appelant : un jeton absent, une erreur 401, des crédits ou un plafond épuisés (402, 429) donnent un brut
avec un statut et un message clair, que l'analyseur remonte dans `sources_en_echec` sans bloquer le passage.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

LISTE_ID = "2113336377958084762"
LISTE_URL = f"https://x.com/i/lists/{LISTE_ID}"
API_URL = f"https://api.x.com/2/lists/{LISTE_ID}/tweets"
USAGE_URL = "https://api.x.com/2/usage/tweets"   # compteur de lectures de posts du cycle (essai du 22/10/2026 : 200, non facturé)
FICHIER_BRUT = Path("raw") / "x-liste.json"
FICHIER_COUT = Path("raw") / "x-cout.jsonl"
FICHIER_IDS = Path("docs/data/actu/x-ids.json")
FICHIER_IDS_ATTENTE = Path("raw/x-ids.json")
EPOCH_X_MS = 1288834974657   # origine des identifiants « snowflake » de X : la date d'un post se lit dans son identifiant
STATUTS = ("ok", "jeton_absent", "jeton_refuse", "acces_refuse", "credits_epuises", "limite_atteinte", "illisible", "erreur")
TARIF_POST_USD = 0.005       # docs.x.com/x-api/getting-started/pricing, lu le 22/10/2026 (« Posts: Read », par ressource retournée)
TARIF_UTILISATEUR_USD = 0.010
MAX_RESULTS = 30             # ≈ 2 jours des six comptes (≈ 15 posts par jour le 22/10/2026) : une nuit tient dans une page
MAX_PAGES = 4
DELAI_S = 30
MESSAGES_HTTP = {
    401: ("jeton_refuse", "X refuse le jeton (401) : il est expiré ou révoqué ; à régénérer dans console.x.com puis à remettre dans le trousseau"),
    403: ("acces_refuse", "X refuse l'accès à la liste (403) : l'application n'a plus le droit de lecture ou la liste n'est plus accessible"),
    402: ("credits_epuises", "crédits X épuisés ou plafond de cycle atteint (402) : à recharger dans console.x.com"),
    429: ("limite_atteinte", "limite de X atteinte (429) : limite de débit ou plafond mensuel de lectures"),
}


# ------------------------------------------------------------------------------------------------ jeton

def lire_jeton() -> str | None:
    """Jeton du trousseau. `secret-tool` a besoin du bus de session : sous la chaîne (environnement construit), XDG_RUNTIME_DIR
    manque parfois ; on le rétablit à son emplacement standard. Retourne None si le jeton est absent ou illisible."""
    uid = os.getuid()
    env = {"HOME": os.path.expanduser("~"), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
           "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")}
    env["DBUS_SESSION_BUS_ADDRESS"] = os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    try:
        r = subprocess.run(["secret-tool", "lookup", "service", "x", "compte", "delta"], env=env, capture_output=True, text=True,
                           timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    jeton = r.stdout.strip()
    return jeton if r.returncode == 0 and jeton else None


# ------------------------------------------------------------------------------------------------ lecture et contrôle

def date_du_snowflake(ident: str) -> datetime:
    return datetime.fromtimestamp(((int(ident) >> 22) + EPOCH_X_MS) / 1000, timezone.utc)


def identifiants_connus(racine: Path) -> set[str]:
    """Identifiants de posts déjà vus (`x-<id>` dans `vus` des états), jamais leur texte."""
    connus: set[str] = set()
    for chemin in (racine / "state").glob("*.json"):
        try:
            vus = json.loads(chemin.read_text(encoding="utf-8")).get("vus", {})
        except (OSError, ValueError, AttributeError):
            continue
        connus.update(k[2:] for k in vus if isinstance(k, str) and k.startswith("x-"))
    return connus


def poste_depuis_api(t: dict, comptes: dict[str, str]) -> dict | None:
    """Un post de l'API en entrée de brut, ou None s'il est mal formé. `type` : original, reponse_a_soi (suite d'un fil du même
    compte), reponse (à un autre compte), citation, repost. La date vient de l'identifiant, jamais devinée."""
    ident, auteur = str(t.get("id") or ""), str(t.get("author_id") or "")
    if not re.fullmatch(r"\d{15,22}", ident) or auteur not in comptes:
        return None
    refs = {r.get("type") for r in t.get("referenced_tweets") or [] if isinstance(r, dict)}
    if "retweeted" in refs:
        genre = "repost"
    elif "replied_to" in refs:
        genre = "reponse_a_soi" if str(t.get("in_reply_to_user_id") or "") == auteur else "reponse"
    elif "quoted" in refs:
        genre = "citation"
    else:
        genre = "original"
    compte = "@" + comptes[auteur]
    return {"compte": compte, "id": ident, "date_iso": date_du_snowflake(ident).isoformat().replace("+00:00", "Z"),
            "url": f"https://x.com/{comptes[auteur]}/status/{ident}", "texte": str(t.get("text") or "").strip(), "type": genre}


# ------------------------------------------------------------------------------------------------ relevé

def lire_usage(session, en_tete: dict) -> dict:
    """Lectures de posts comptées par X pour le cycle et plafond du cycle : le chiffre réel, déduplication comprise (les crédits
    restants ne sont lisibles que dans la console). Jamais bloquant : {} si l'appel échoue."""
    try:
        r = session.get(USAGE_URL, headers=en_tete, params={"days": 1}, timeout=DELAI_S)
        d = r.json()["data"] if r.status_code == 200 else {}
        return {"cycle_posts_lus": int(d["project_usage"]), "plafond_posts": int(d["project_cap"]), "jour_remise": int(d["cap_reset_day"])}
    except Exception:
        return {}


def _brut(statut: str, message: str | None, posts: list[dict] | None = None, lectures: dict | None = None,
          partiel: str | None = None) -> dict:
    assert statut in STATUTS
    return {"statut": statut, "message": message, "partiel": partiel,
            "releve_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "liste": LISTE_URL,
            "posts": posts or [], "lectures": lectures or {}}


def _message_http(r: requests.Response) -> tuple[str, str]:
    if r.status_code in MESSAGES_HTTP:
        return MESSAGES_HTTP[r.status_code]
    detail = ""
    try:
        d = r.json()
        detail = str(d.get("detail") or d.get("title") or "")[:160]
    except ValueError:
        pass
    return "erreur", f"X répond HTTP {r.status_code}" + (f" : {detail}" if detail else "")


def releve(racine: Path, jeton: str | None, session=None, connus: set[str] | None = None, max_results: int = MAX_RESULTS,
           max_pages: int = MAX_PAGES) -> dict:
    """Lit la liste et retourne le brut (sans l'écrire). Ne lève jamais ; ne contient ni le jeton ni ses traces."""
    if not jeton:
        return _brut("jeton_absent", "jeton X introuvable dans le trousseau : `secret-tool lookup service x compte delta` ne rend rien "
                                     "(trousseau verrouillé ou jeton non enregistré)")
    session = session or requests
    connus = identifiants_connus(racine) if connus is None else connus
    pages_max = max_pages if connus else 1     # premier relevé : une seule page, l'amorçage n'a pas à tout remonter
    en_tete = {"Authorization": f"Bearer {jeton}", "User-Agent": "Delta-veille/0.1 (liste X officielle, interne)"}
    posts: list[dict] = []
    comptes: dict[str, str] = {}
    lus = pages = 0
    suite: str | None = None
    partiel = None
    restant = None
    while pages < pages_max:
        params = {"max_results": max_results, "tweet.fields": "created_at,referenced_tweets,in_reply_to_user_id",
                  "expansions": "author_id", "user.fields": "username"}
        if suite:
            params["pagination_token"] = suite
        try:
            r = session.get(API_URL, headers=en_tete, params=params, timeout=DELAI_S)
        except requests.RequestException as e:
            erreur = f"{type(e).__name__} : appel de l'API X impossible"
            if pages:
                partiel = f"page {pages + 1} non lue ({erreur})"
                break
            return _brut("erreur", erreur)
        if r.status_code != 200:
            statut, message = _message_http(r)
            if pages:
                partiel = f"page {pages + 1} non lue : {message}"
                break
            return _brut(statut, message)
        restant = r.headers.get("x-rate-limit-remaining")
        try:
            d = r.json()
            page = d.get("data") or []
            for u in (d.get("includes") or {}).get("users") or []:
                comptes[str(u["id"])] = str(u["username"])
            meta = d.get("meta") or {}
        except (ValueError, KeyError, TypeError, AttributeError):
            if pages:
                partiel = f"page {pages + 1} illisible"
                break
            return _brut("illisible", "réponse de l'API X illisible (pas le JSON attendu)")
        pages += 1
        lus += len(page)
        posts.extend(p for p in (poste_depuis_api(t, comptes) for t in page if isinstance(t, dict)) if p)
        suite = meta.get("next_token")
        if not page or not suite or any(str(t.get("id")) in connus for t in page if isinstance(t, dict)):
            break
    sans_fin = bool(suite) and pages == pages_max and connus and not any(p["id"] in connus for p in posts)
    if sans_fin:   # pas de post connu dans toutes les pages lues : des posts plus anciens ont pu échapper au relevé
        partiel = (partiel + " ; " if partiel else "") + f"aucun post déjà vu dans {pages} pages : des posts plus anciens ont pu échapper"
    lectures = {"pages": pages, "posts": lus, "utilisateurs": len(comptes),
                "cout_estime_usd": round(lus * TARIF_POST_USD + len(comptes) * TARIF_UTILISATEUR_USD, 4),
                "limite_restante": restant, **lire_usage(session, en_tete)}
    posts.sort(key=lambda p: p["id"], reverse=True)
    if not posts:
        return _brut("illisible", "l'API répond mais aucun post exploitable (liste vide ou comptes non résolus)", lectures=lectures,
                     partiel=partiel)
    return _brut("ok", None, posts, lectures, partiel)


def identifiants_publics(brut: dict) -> dict:
    """Projection sans contenu de post : IDs uniques, numériques, du plus récent au plus ancien, 30 au plus."""
    ids = {p.get("id") for p in brut["posts"] if isinstance(p, dict) and isinstance(p.get("id"), str)
           and re.fullmatch(r"[0-9]{1,25}", p["id"])}
    return {"maj": brut["releve_le"], "ids": sorted(ids, key=int, reverse=True)[:30]}


def ecrire_ids(racine: Path, brut: dict, fichier: Path = FICHIER_IDS) -> None:
    """Remplace atomiquement les seuls IDs après un relevé réussi ; tout échec garde le fichier précédent."""
    if brut["statut"] != "ok":
        return
    chemin = racine / fichier
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(identifiants_publics(brut), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, chemin)
    finally:
        tmp.unlink(missing_ok=True)


def ecrire(racine: Path, brut: dict, fichier_ids: Path = FICHIER_IDS) -> dict:
    """Écrit `raw/x-liste.json` (texte compris, purgé en fin de passage) et ajoute la ligne de comptes de la nuit à
    `raw/x-cout.jsonl` (chiffres seulement, conservée). Publie les seuls IDs si le relevé réussit."""
    chemin = racine / FICHIER_BRUT
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(brut, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, chemin)
    ligne = {"releve_le": brut["releve_le"], "statut": brut["statut"], **brut["lectures"],
             "nouveaux": sum(1 for p in brut["posts"] if p["type"] != "repost")}
    with open(racine / FICHIER_COUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    ecrire_ids(racine, brut, fichier_ids)
    return brut


def lancer(racine: Path, jeton=lire_jeton, session=None, fichier_ids: Path = FICHIER_IDS) -> dict:
    """Relevé complet : jeton, lecture, écriture. Ne lève jamais."""
    try:
        brut = releve(racine, jeton(), session)
    except Exception as e:   # le capteur ne bloque jamais le passage
        brut = _brut("erreur", f"{type(e).__name__} dans le capteur"[:200])
    try:
        return ecrire(racine, brut, fichier_ids)
    except OSError as e:
        return {**brut, "statut": "erreur", "message": f"écriture du brut impossible : {type(e).__name__}"}


# ------------------------------------------------------------------------------------------------ publication

def publier_ids(racine: Path) -> tuple[int, str, str]:
    """Publie le relevé en attente par commit dédié, avant les étapes. Aucun changement local avant push réussi.

    Index temporaire et commit-tree : un push rejeté laisse seulement des objets non référencés, jamais un commit local en
    avance ni un arbre sale. Sans distant, avance locale seulement. L'appelant journalise le résultat sans bloquer la chaîne.
    """
    commit = "aucun"
    try:
        attente = racine / FICHIER_IDS_ATTENTE
        if not attente.exists():
            return 0, commit, "aucun relevé réussi à publier"
        d = json.loads(attente.read_text(encoding="utf-8"))
        if (not isinstance(d, dict) or set(d) != {"maj", "ids"} or not isinstance(d["maj"], str)
                or not isinstance(d["ids"], list) or len(d["ids"]) > 30
                or any(not isinstance(i, str) or not re.fullmatch(r"[0-9]{1,25}", i) for i in d["ids"])
                or len(set(d["ids"])) != len(d["ids"])
                or d["ids"] != sorted(d["ids"], key=int, reverse=True)
                or datetime.fromisoformat(d["maj"].replace("Z", "+00:00")).utcoffset() is None):
            raise ValueError("identifiants publics invalides")
        # Re-sérialise seulement les deux champs autorisés, jamais le brut de l'API.
        contenu = json.dumps({"maj": d["maj"], "ids": d["ids"]}, ensure_ascii=False, indent=1) + "\n"
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        def git(*args, entree=None, index=None):
            r = subprocess.run(["git", "-C", str(racine), *args], input=entree, capture_output=True, text=True,
                               timeout=60, env={**env, **({"GIT_INDEX_FILE": str(index)} if index else {})})
            if r.returncode:
                raise RuntimeError(f"git {args[0]} : code {r.returncode}")
            return r.stdout.strip()

        if git("status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError("arbre non propre, publication X différée")
        avant = git("rev-parse", "HEAD")
        distant = bool(git("remote"))
        if distant:
            if git("branch", "--show-current") != "main":
                raise ValueError("publication X réservée à main")
            git("fetch", "--quiet", "origin", "main")
            if avant != git("rev-parse", "origin/main"):
                raise ValueError("main diffère de origin/main, publication X différée")
        with tempfile.TemporaryDirectory(prefix=".tmp-x-ids-", dir=racine) as tmp:
            index = Path(tmp) / "index"
            git("read-tree", avant, index=index)
            blob = git("hash-object", "-w", "--stdin", entree=contenu)
            git("update-index", "--add", "--cacheinfo", "100644", blob, str(FICHIER_IDS), index=index)
            arbre = git("write-tree", index=index)
            if arbre == git("rev-parse", f"{avant}^{{tree}}"):
                return 0, commit, "identifiants déjà publiés"
            candidat = git("commit-tree", arbre, "-p", avant, "-m", f"delta(x): {d['maj'][:10]} — {len(d['ids'])} identifiants")
        if distant:
            git("push", "origin", f"{candidat}:refs/heads/main")
            commit = candidat[:12]  # Déjà publié, même si le fast-forward local échoue ensuite.
        git("merge", "--ff-only", candidat)
        return 0, candidat[:12], "identifiants publiés"
    except Exception as e:
        # Ni sortie de git, ni contenu de réponse API : ils peuvent contenir des informations privées.
        return 1, commit, f"publication X différée ({type(e).__name__})"


# ------------------------------------------------------------------------------------------------ purge

def purger(racine: Path) -> list[str]:
    """Fin de passage : le texte des posts ne reste pas. Supprime `raw/x-liste.json` et vide le `contenu` des éléments de source
    `x-liste-*` dans les bruts du jour et dans l'historique du brut (D72). `raw/x-cout.jsonl` (chiffres) reste.
    Retourne les chemins touchés."""
    touches: list[str] = []
    brut = racine / FICHIER_BRUT
    if brut.exists():
        brut.unlink()
        touches.append(str(FICHIER_BRUT))
    candidats = list((racine / "raw").glob("*-nouveautes.json")) + list((racine / "raw" / "historique").glob("*/*-nouveautes-*.json"))
    for chemin in candidats:
        try:
            donnees = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        change = False
        for e in donnees.get("nouveautes", []) if isinstance(donnees, dict) else []:
            if isinstance(e, dict) and str(e.get("source_id", "")).startswith("x-liste-") and e.get("contenu"):
                e["contenu"], e["empreinte"] = "", None
                change = True
        if change:
            chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            touches.append(str(chemin.relative_to(racine)))
    return touches
