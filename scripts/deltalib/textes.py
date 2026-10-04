"""D76 : normalisation commune aux empreintes des pages et aux comparaisons de texte."""

import re
from html import unescape
from urllib.parse import parse_qsl, urlsplit, urlunsplit


_URL = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)
_SIGNATURES = {"expires", "expiry", "signature", "sig", "req", "policy", "key-pair-id",
               "awsaccesskeyid", "token", "hdnts", "hdnea"}


def normaliser_contenu(texte: str, *, reduire_blancs: bool = False) -> str:
    """Retire toute la requête des URL signées, en gardant le chemin et le fragment.

    La réduction des blancs est réservée au diff : les empreintes sans URL volatile doivent
    rester strictement compatibles avec les états antérieurs à D76 (y compris dans la base).
    Les liens non signés gardent leurs paramètres fonctionnels.
    """
    def nettoyer(m):
        url = m.group()
        try:
            parties = urlsplit(url)
            cles = {k.lower() for k, _ in parse_qsl(unescape(parties.query), keep_blank_values=True)}
        except ValueError:
            return url
        if cles & _SIGNATURES or any(k.startswith(("x-amz-", "x-goog-")) for k in cles):
            return urlunsplit(parties._replace(query=""))
        return url

    texte = _URL.sub(nettoyer, texte or "")
    return " ".join(texte.split()) if reduire_blancs else texte
