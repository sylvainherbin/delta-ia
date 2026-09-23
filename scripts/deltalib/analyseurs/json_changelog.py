"""Flux JSON du « ChatGPT & Codex changelog » (learn.chatgpt.com/docs/changelog/*.json).

Endpoint non documenté : toute dérive de structure doit être une erreur explicite, jamais un résultat vide.
Identifiant (D1) : `oa-<id natif>`, commun aux flux general, codex-app et ios, pour dédoublonner.
Produit (D2bis, option `produit_par_entree`) : codex par défaut ; chatgpt si « chatgpt » apparaît dans le titre ou
les sujets sans « codex ».
Option `format: releasebot` : point `__data.json` d'une page releasebot.io (D25), une entrée par date.
"""

from __future__ import annotations

import json
import re

from ..dates import analyser_date
from ..modeles import Element, FormatInattendu, ResultatSource

CHAMPS_OBLIGATOIRES = ("id", "title", "date")
SCHEMA_ATTENDU = 1


def produit_de(it: dict, source) -> str:
    """D2bis : general.json est le changelog Codex. `chatgpt` seulement si « chatgpt » apparaît dans le titre
    ou les sujets et que « codex » n'y apparaît pas ; sinon le produit de la source (`codex`)."""
    if not source.options.get("produit_par_entree"):
        return source.produit
    texte = " ".join([str(it.get("title") or "")] + [str(t) for t in (it.get("topics") or [])]).lower()
    if "chatgpt" in texte and "codex" not in texte:
        return "chatgpt"
    return source.produit


def parser_json(donnees, source) -> list[Element]:
    if not isinstance(donnees, dict):
        raise FormatInattendu("la racine n'est pas un objet JSON")
    if donnees.get("schemaVersion") not in (None, SCHEMA_ATTENDU):
        raise FormatInattendu(f"schemaVersion inattendu : {donnees.get('schemaVersion')!r} (attendu {SCHEMA_ATTENDU})")
    items = donnees.get("items")
    if not isinstance(items, list):
        raise FormatInattendu("clé `items` absente ou pas une liste")
    if not items:
        raise FormatInattendu("liste `items` vide")
    elements: list[Element] = []
    for it in items:
        if not isinstance(it, dict):
            raise FormatInattendu("entrée qui n'est pas un objet")
        manquants = [c for c in CHAMPS_OBLIGATOIRES if not it.get(c)]
        if manquants:
            raise FormatInattendu(f"champs manquants dans l'entrée {it.get('id', '?')!r} : {manquants}")
        titre = str(it["title"]).strip()
        version = it.get("version")
        version = str(version).strip() if version not in (None, "") else None
        if version and version not in titre:
            titre = f"{titre} {version}"
        corps = it.get("bodyMarkdown") or it.get("summary") or ""
        elements.append(Element(
            id=f"oa-{it['id']}",
            produit=produit_de(it, source),
            titre=titre,
            version=version,
            date_publication=analyser_date(str(it["date"])),
            url=it.get("url") or f"{source.options.get('url_publique', 'https://developers.openai.com/codex/changelog')}#{it['id']}",
            contenu=str(corps).strip(),
            source_id=source.id,
            officielle=source.officielle,
        ))
    return elements


# --- Releasebot (D25) : point `__data.json` d'une page SvelteKit, sérialisé « devalue » ------------------------

def _devalue(donnees: list, i: int, profondeur: int = 0):
    """Résout une valeur devalue : les objets et listes référencent des indices du tableau plat."""
    if profondeur > 12:
        raise FormatInattendu("structure devalue trop profonde")
    if not isinstance(i, int) or i < 0 or i >= len(donnees):
        raise FormatInattendu(f"référence devalue invalide : {i!r}")
    v = donnees[i]
    if isinstance(v, dict):
        return {k: _devalue(donnees, j, profondeur + 1) for k, j in v.items()}
    if isinstance(v, list):
        return [_devalue(donnees, j, profondeur + 1) for j in v]
    return v


_RE_H3 = re.compile(r"^###\s+(.+?)\s*$", re.M)


def parser_releasebot(donnees, source) -> tuple[list[Element], str | None]:
    """Releases d'une page releasebot.io : une entrée par date, identifiée `releasebot-<id>`.

    Retourne (éléments, date la plus ancienne). Endpoint non documenté : toute dérive est une erreur explicite.
    """
    if not isinstance(donnees, dict) or not isinstance(donnees.get("nodes"), list):
        raise FormatInattendu("enveloppe SvelteKit attendue : objet avec `nodes`")
    racine = None
    for n in donnees["nodes"]:
        if isinstance(n, dict) and isinstance(n.get("data"), list) and n["data"] and isinstance(n["data"][0], dict) \
                and "releases" in n["data"][0]:
            racine = _devalue(n["data"], 0)
            break
    if racine is None:
        raise FormatInattendu("aucun nœud `releases` dans __data.json : gabarit changé ?")
    releases = racine.get("releases")
    if not isinstance(releases, list) or not releases:
        raise FormatInattendu("liste `releases` absente ou vide")
    page = source.options.get("url_publique") or source.url.rsplit("/__data.json", 1)[0]
    elements: list[Element] = []
    dates: list[str] = []
    for r in releases:
        if not isinstance(r, dict) or not r.get("id") or not r.get("release_date"):
            raise FormatInattendu(f"release sans `id` ou `release_date` : {str(r)[:80]}")
        details = r.get("release_details") or {}
        contenu = str(r.get("formatted_content") or "").strip()
        titres = _RE_H3.findall(contenu)
        titre = " ; ".join(titres) if titres else str(details.get("release_name") or f"ChatGPT — {r['release_date'][:10]}")
        officielle_url = ((r.get("source") or {}).get("source_url") or "").strip()
        d = analyser_date(str(r["release_date"]))
        if d:
            dates.append(d)
        entete = f"Source officielle : {officielle_url}\n\n" if officielle_url else ""
        resume = str(details.get("release_summary") or "").strip()
        elements.append(Element(
            id=f"releasebot-{r['id']}",
            produit=source.produit,
            titre=titre,
            version=None,
            date_publication=d,
            url=page,  # D25 : l'URL de la page consultée, jamais un permalien reconstruit (ils n'existent pas)
            contenu=entete + (resume + "\n\n" if resume else "") + contenu,
            source_id=source.id,
            officielle=source.officielle,
        ))
    return elements, (min(dates) if dates else None)


def analyser(source, client, borne: str | None = None) -> ResultatSource:
    reponse = client.get(source.url, accept="application/json")
    try:
        donnees = json.loads(reponse.texte)
    except ValueError as e:
        raise FormatInattendu(f"JSON invalide ({reponse.content_type or 'type inconnu'}) : {e}") from e
    if source.options.get("format") == "releasebot":
        elements, plus_ancienne = parser_releasebot(donnees, source)
        return ResultatSource(elements, plus_ancienne=plus_ancienne)
    return ResultatSource(parser_json(donnees, source))
