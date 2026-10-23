// D64-bis : même comparaison que badgeContexte dans le site ; jamais déduire « actuelle » d'une date seule.
export function validiteFiche(e, document = {}) {
  const courantes = document.contexte_sections;
  const deprecies = Array.isArray(document.contexte_deprecies) ? document.contexte_deprecies : [];
  const references = e.contexte_sections;
  let validite = "inconnue", perimee = null, sections_perimees = [];
  if (e.commentee === false) validite = "non_commentee";
  else if (e.commentee && courantes && typeof courantes === "object" && !Array.isArray(courantes)) {
    if (references == null) validite = "anterieure_d64";
    else if (typeof references === "object" && !Array.isArray(references)) {
      sections_perimees = Object.keys(references).filter(k => deprecies.includes(k) ||
        !references[k] || typeof references[k] !== "object" || typeof references[k].sha1 !== "string" ||
        !Object.hasOwn(courantes, k) || courantes[k] !== references[k].sha1);
      perimee = sections_perimees.length > 0;
      validite = perimee ? "perimee" : "actuelle";
    }
  }
  const revisions = (Array.isArray(e.historique) ? e.historique : []).filter(h => h &&
    ["commentée", "commentaire révisé", "réévaluée"].includes(h.changement) && /^\d{4}-\d{2}-\d{2}$/.test(h.date || ""))
    .map(h => h.date).sort();
  return { validite, perimee, sections_perimees, verifie_le: e.verifie_le ?? revisions.at(-1) ?? null };
}
