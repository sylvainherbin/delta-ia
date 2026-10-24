"""Dictionnaires d'interface du site (docs/assets/textes.js, lot L3), lus par les tests du site."""

import json
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
TEXTES_JS = RACINE / "docs" / "assets" / "textes.js"
PREFIXE = "window.DELTA_TEXTES = "


def charger() -> dict:
    """{"en": {...}, "fr": {...}} : JSON pur entre `window.DELTA_TEXTES = ` et le `;` final."""
    s = TEXTES_JS.read_text(encoding="utf-8")
    debut = s.index(PREFIXE) + len(PREFIXE)
    fin = s.rindex(";")
    return json.loads(s[debut:fin])


TEXTES = charger()
FR = TEXTES["fr"]
EN = TEXTES["en"]

# t() d'app.js pour les harnais Node : même interpolation `{nom}`, dictionnaire choisi par `langue`
T_JS = r"""
const DICO = %s;
function t(cle, vars) {
  let s = DICO[cle];
  if (typeof s !== "string") throw new Error("texte manquant : " + cle);
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m));
  return s;
}
"""


def t_js(langue: str = "fr") -> str:
    return T_JS % json.dumps(TEXTES[langue], ensure_ascii=False)
