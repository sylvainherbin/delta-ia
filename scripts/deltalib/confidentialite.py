"""Motifs interdits dans un fichier publiable : secrets (REGLES §5) et traces opérationnelles OPÉRER (D77).

Partagés par `valider.py` et par la projection commune des deux couches (`deltalib.couches`).
"""

import re

RE_SECRETS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "jeton GitHub (ghp_)"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "jeton GitHub (github_pat_)"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "clé API (sk-)"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "clé AWS (AKIA)"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|-----BEGIN"), "clé privée (-----BEGIN)"),
    (re.compile(r"https?://[^\s\"'<>]*[?&/;#](?:[A-Za-z_-]*(?:token|key|secret)[A-Za-z_-]*)=[^\s\"'<>&]+", re.I), "URL contenant token, key ou secret"),
]
RE_ORGANISATION_PRIVEE = [re.compile(motif) for motif in (rb"m-[0-9a-f]{12}", rb"cc-socks")]
