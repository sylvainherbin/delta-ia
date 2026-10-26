// Codes fermés seulement : jamais le message d'exception, ses variables ou un argument du client.
import { TEXTES, ErreurTexte } from "./textes.js";

export const CAUSES_ERREURS = new Set([
  ...Object.keys(TEXTES.en).filter(c => /^(param|lecture|couche|local|modeles)\./.test(c)), "interne",
]);

export function causeErreur(e) {
  if (!(e instanceof ErreurTexte)) return "interne";
  const raison = e.cle === "lecture.message" && e.vars.raison instanceof ErreurTexte ? e.vars.raison : e;
  return CAUSES_ERREURS.has(raison.cle) ? raison.cle : "interne";
}
