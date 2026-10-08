#!/usr/bin/env python3
"""Relais local « Envoyer à Delta » (mission m-944fab565b10) : le bouton d'une carte de l'onglet Référence passe la
référence au Core, qui juge sa pertinence et, le cas échéant, l'oriente vers un workflow ou un agent.

Le site est statique (GitHub Pages) et le serveur MCP reste en lecture seule (D61) : le bouton parle à ce relais, sur
127.0.0.1 seulement, depuis le navigateur de la machine de Sylvain.

  POST /reference {"id": "<id de l'entrée>"}
    1. l'origine de la page doit être le site publié ou un aperçu local (http://localhost, http://127.0.0.1) ;
    2. seul l'id est lu dans la requête : l'entrée est relue dans la base locale (docs/data/kb/*/*.json), jamais
       recopiée depuis la page ;
    3. l'entrée devient une idée (texte_idee) remise à la porte des idées du bureau, idee.py (palier 3 de
       delta-system-experience : juger détaché, le Core choisit le mode PERTINENCE) ; la suite est celle de toute idée :
       jugement, puis mission de conception OPÉRER sur branche si l'idée est retenue ;
    4. une ligne JSON par envoi dans ~/.local/state/delta-ia/envois-reference.jsonl.
  GET /etat   le relais répond (sert à l'installation et au contrôle).

Réponses : JSON {"ok": bool, "etape": ..., "detail": ...}, même forme que idee.py.

  relais_reference.py [--port 47613] [--kb DOSSIER] [--idee CHEMIN]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PORT = 47613
KB = RACINE / "docs" / "data" / "kb"
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
IDEE = Path(os.environ.get("DELTA_IDEE") or STATE.parent / "share" / "delta-system-experience" / "palier-3" / "idee.py")
JOURNAL = STATE / "delta-ia" / "envois-reference.jsonl"
SITE = "https://sylvainherbin.github.io"
APERCU = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")
CORPS_MAX = 2048
IDEE_MAX = 4000      # plafond de idee.py
PRODUITS = {"claude": "Claude", "claude-code": "Claude Code", "chatgpt": "ChatGPT", "codex": "Codex"}
CATEGORIES = {"fonctionnalites": "fonctionnalité", "commandes": "commande", "skills": "skill", "plugins": "plugin",
              "mcp": "MCP", "parametres": "paramètre", "raccourcis": "raccourci"}


def origine_admise(origine):
    return origine == SITE or bool(APERCU.match(origine or ""))


def trouver(kb, ident):
    """L'entrée publiée d'id `ident`, relue dans les fichiers de la base ; None si elle n'y est pas."""
    for f in sorted(Path(kb).glob("*/*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in d.get("entrees") or []:
            if isinstance(e, dict) and e.get("id") == ident:
                return e
    return None


def _un(v, n):
    """Une ligne, au plus n caractères."""
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def texte_idee(e):
    """L'idée remise au Core : ce qu'est la référence, ce qu'en dit Delta-IA, et la question posée."""
    produit = PRODUITS.get(e.get("produit"), e.get("produit") or "produit inconnu")
    categorie = CATEGORIES.get(e.get("categorie"), e.get("categorie") or "référence")
    reco = e.get("recommandation") if isinstance(e.get("recommandation"), dict) else {}
    description = e.get("description") if e.get("commentee") and e.get("description") else e.get("description_source")
    sources = [s.get("url") for s in e.get("sources") or [] if isinstance(s, dict) and str(s.get("url", "")).startswith("http")]
    parties = [
        f"idée : intégrer la référence Delta-IA « {_un(e.get('nom'), 120)} » ({produit}, {categorie}, id {e.get('id')}) "
        "dans un workflow ou chez un agent de Delta. Juge sa pertinence pour mes projets et, si elle l'est, dis dans "
        "quel workflow ou chez quel agent elle entre et ce que ça change.",
        f"Ce qu'elle fait : {_un(description, 900)}" if description else None,
        f"{'Accès' if e.get('usage_nature') == 'etapes' else 'Syntaxe'} : {_un(e.get('usage'), 400)}" if e.get("usage") else None,
        f"Avis de Delta-IA : {reco.get('verdict')}, {_un(reco.get('pourquoi'), 900)}" if reco.get("verdict") else None,
        f"Disponibilité : {_un(e.get('disponibilite'), 200)}" if e.get("disponibilite") else None,
        f"Source : {sources[0]}" if sources else None,
    ]
    return _un(" ".join(p for p in parties if p), IDEE_MAX)


def remettre(idee_py, texte):
    """idee.py lit l'idée sur son entrée standard et rend une ligne JSON {ok, etape, detail} (≈ 2 s au plus)."""
    if not Path(idee_py).is_file():
        return {"ok": False, "etape": "outils", "detail": f"porte des idées introuvable : {idee_py}"}
    try:
        p = subprocess.run([sys.executable, str(idee_py)], input=texte + "\n", capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "etape": "idee", "detail": f"idee.py : {exc}"}
    try:
        r = json.loads(p.stdout.strip().splitlines()[-1])
        if isinstance(r, dict) and "ok" in r:
            return r
    except (IndexError, ValueError):
        pass
    return {"ok": False, "etape": "idee", "detail": f"idee.py sans réponse lisible (code {p.returncode})"}


def journaliser(journal, ligne):
    try:
        Path(journal).parent.mkdir(parents=True, exist_ok=True)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError:
        pass  # le journal suit l'envoi, il ne le conditionne pas


class Relais(BaseHTTPRequestHandler):
    server_version = "delta-relais/1"
    kb = KB
    idee = IDEE
    journal = JOURNAL

    def _repondre(self, code, corps=None):
        origine = self.headers.get("Origin")
        self.send_response(code)
        if origine and origine_admise(origine):
            self.send_header("Access-Control-Allow-Origin", origine)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")   # Chrome : page publique → 127.0.0.1
        if corps is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        b = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self._repondre(204 if origine_admise(self.headers.get("Origin")) else 403)

    def do_GET(self):
        if self.path != "/etat":
            return self._repondre(404, {"ok": False, "etape": "chemin", "detail": self.path})
        self._repondre(200, {"ok": True, "etape": "pret", "detail": "relais Référence → Delta"})

    def do_POST(self):
        if self.path != "/reference":
            return self._repondre(404, {"ok": False, "etape": "chemin", "detail": self.path})
        origine = self.headers.get("Origin")
        if not origine_admise(origine):
            return self._repondre(403, {"ok": False, "etape": "origine", "detail": f"origine refusée : {origine}"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 < n <= CORPS_MAX:
            return self._repondre(400, {"ok": False, "etape": "requete", "detail": "corps absent ou trop long"})
        try:
            ident = json.loads(self.rfile.read(n).decode("utf-8")).get("id")
        except (ValueError, AttributeError, UnicodeDecodeError):
            ident = None
        if not isinstance(ident, str) or not ident or len(ident) > 300:
            return self._repondre(400, {"ok": False, "etape": "requete", "detail": "id manquant"})
        e = trouver(self.kb, ident)
        if e is None:
            return self._repondre(404, {"ok": False, "etape": "reference", "detail": f"référence inconnue de la base locale : {ident}"})
        r = remettre(self.idee, texte_idee(e))
        journaliser(self.journal, {"date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "id": ident, "nom": e.get("nom"),
                                   "ok": r.get("ok"), "etape": r.get("etape")})
        self._repondre(200 if r.get("ok") else 502, r)

    def log_message(self, fmt, *args):
        sys.stderr.write("relais %s\n" % (fmt % args))


def main(argv=None):
    a = argparse.ArgumentParser(description="Relais local : le bouton « Envoyer à Delta » de l'onglet Référence.")
    a.add_argument("--port", type=int, default=PORT)
    a.add_argument("--kb", default=str(KB), help="dossier de la base (défaut : docs/data/kb du dépôt)")
    a.add_argument("--idee", default=str(IDEE), help="porte des idées du bureau (idee.py)")
    a.add_argument("--journal", default=str(JOURNAL))
    o = a.parse_args(argv)
    Relais.kb, Relais.idee, Relais.journal = Path(o.kb), Path(o.idee), Path(o.journal)
    serveur = ThreadingHTTPServer(("127.0.0.1", o.port), Relais)
    print(f"relais Référence → Delta sur http://127.0.0.1:{o.port}", flush=True)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
