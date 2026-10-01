"""Pages d'état au format Statuspage : `/api/v2/incidents.json` (étape 2b, 01/10/2026).

Atlassian Statuspage (status.claude.com) et incident.io (status.openai.com, qui expose le même schéma) servent
`{"page": {...}, "incidents": [{id, name, status, impact, created_at, resolved_at?, incident_updates: [...]}]}`.
Un incident est un élément ; sa date est celle de l'ouverture (`created_at`, UTC), jamais celle de la dernière mise
à jour. Le contenu reprend l'impact, le statut et toutes les mises à jour dans l'ordre chronologique : avec l'option
`suivre_revisions` (désactivée pour les deux pages d'état, 01/10 : un incident ne remonte qu'une fois, à son ouverture),
un nouveau message ou un passage à « resolved » reviendrait en révision.

Options :
- `url_publique` : base des permaliens (`<base>/incidents/<id>`) ; sinon `page.url`, sinon l'URL de la source ;
- `produits_par_mot` : `{produit: [mots]}` testés dans l'ordre sur le nom de l'incident (minuscules) ; sans
  correspondance, le produit de la source ;
- `ignorer_impacts` : impacts dont l'incident n'est pas un élément (ex. `[none]`) ; l'impact est lu à chaque passage,
  un incident ouvert à `none` puis aggravé arrive donc, une fois, au passage où son impact change. La date la plus
  ancienne (détection de trou, D4) reste celle de tous les incidents lus.

Endpoint hors documentation de l'éditeur pour incident.io : toute dérive de structure est une erreur explicite.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ..dates import analyser_date
from ..modeles import Element, FormatInattendu, ResultatSource

CHAMPS_OBLIGATOIRES = ("id", "name", "status", "created_at")


def produit_de(nom: str, source) -> str:
    bas = (nom or "").lower()
    for produit, mots in (source.options.get("produits_par_mot") or {}).items():
        if any(str(m).lower() in bas for m in mots):
            return produit
    return source.produit


def _base(donnees: dict, source) -> str:
    base = source.options.get("url_publique") or (donnees.get("page") or {}).get("url")
    if not base:
        u = urlparse(source.url)
        base = f"{u.scheme}://{u.netloc}"
    return str(base).rstrip("/")


def _contenu(it: dict) -> str:
    entete = f"Impact : {it.get('impact') or 'inconnu'} ; statut : {it['status']} ; ouvert le {it['created_at']}"
    if it.get("resolved_at"):
        entete += f" ; résolu le {it['resolved_at']}"
    lignes = [entete]
    maj = it.get("incident_updates") or []
    if not isinstance(maj, list):
        raise FormatInattendu(f"`incident_updates` n'est pas une liste (incident {it['id']!r})")
    for u in sorted((u for u in maj if isinstance(u, dict)), key=lambda u: str(u.get("created_at") or "")):
        corps = str(u.get("body") or "").strip()
        lignes.append(f"[{u.get('created_at') or '?'}] {u.get('status') or '?'} : {corps}")
    composants = [str(c.get("name")) for c in (it.get("components") or []) if isinstance(c, dict) and c.get("name")]
    if composants:
        lignes.append("Composants : " + ", ".join(composants))
    return "\n".join(lignes)


def parser_statuspage(donnees, source) -> tuple[list[Element], str | None]:
    if not isinstance(donnees, dict):
        raise FormatInattendu("la racine n'est pas un objet JSON")
    incidents = donnees.get("incidents")
    if not isinstance(incidents, list):
        raise FormatInattendu("clé `incidents` absente ou pas une liste : format Statuspage attendu")
    if not incidents:
        raise FormatInattendu("liste `incidents` vide : jamais un résultat vide silencieux")
    base = _base(donnees, source)
    ignores = {str(i).lower() for i in (source.options.get("ignorer_impacts") or [])}
    elements: list[Element] = []
    dates: list[str] = []
    for it in incidents:
        if not isinstance(it, dict):
            raise FormatInattendu("incident qui n'est pas un objet")
        manquants = [c for c in CHAMPS_OBLIGATOIRES if not it.get(c)]
        if manquants:
            raise FormatInattendu(f"champs manquants dans l'incident {it.get('id', '?')!r} : {manquants}")
        date_iso = analyser_date(str(it["created_at"]))
        if date_iso is None:
            raise FormatInattendu(f"`created_at` illisible dans l'incident {it['id']!r} : {it['created_at']!r}")
        dates.append(date_iso)
        if str(it.get("impact") or "").lower() in ignores:
            continue
        elements.append(Element(
            id=f"{source.id}-{it['id']}",
            produit=produit_de(str(it["name"]), source),
            titre=str(it["name"]).strip(),
            version=None,
            date_publication=date_iso,
            url=f"{base}/incidents/{it['id']}",
            contenu=_contenu(it),
            source_id=source.id,
            officielle=source.officielle,
        ))
    return elements, min(dates)


def analyser_json(donnees, source) -> ResultatSource:
    elements, plus_ancienne = parser_statuspage(donnees, source)
    return ResultatSource(elements, plus_ancienne=plus_ancienne)
