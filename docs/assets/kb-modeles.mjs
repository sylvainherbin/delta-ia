// Fiches modèles × efforts : données communes par modèle, un enregistrement par couple.
// Lecture pure partagée par le site et le MCP ; aucun HTML ni requête réseau.
// Deux formats lus : l'ancienne route (`schema_version: 2`, encore mixte) et la génération commune (`delta.commun` v1,
// `version_source: 2`, sans textes rédigés). L3 : la sortie publique ne porte ni constats internes ni recommandation
// OPÉRER, même lus dans un ancien JSON mixte (champs retirés, section et ligne retirées des descriptions).
export const CHAMPS_PRIVES_MODELE = ["constats_internes", "recommandation_operer"];
const SECTION_CONSTATS = /(^|\n)### Constats internes datés(\n[\s\S]*?)?(?=\n### |$)/g;
const LIGNE_OPERER = /(^|\n)- \*\*Recommandation OPÉRER[^\n]*/g;

export function sansPrive(texte) {
  if (typeof texte !== "string") return texte ?? null;
  return texte.replace(SECTION_CONSTATS, "").replace(LIGNE_OPERER, "").replace(/\n{3,}/g, "\n\n").trim();
}

const estCommun = (doc) => doc && doc.schema === "delta.commun" && doc.schema_version === 1;

export function developperModeles(doc) {
  const commun = estCommun(doc);
  if (commun ? doc.version_source !== 2 : doc.schema_version !== 2) throw new Error("format modèles inattendu");
  if (!doc.modeles || Array.isArray(doc.modeles) || !Array.isArray(doc.entrees)) throw new Error("format modèles inattendu");
  return doc.entrees.map((e) => {
    const m = doc.modeles[e.modele];
    if (!m) throw new Error(`modèle absent : ${e.modele}`);
    const { aliases_effort, aliases_defaut, description_commune, ...partage } = m;
    // la génération commune ne publie pas les alias internes : seuls `modèle:effort` et, pour le défaut, le modèle seul
    const aliases = commun
      ? [`${e.modele}:${e.effort}`, ...(e.effort_defaut ? [e.modele] : [])]
      : [...new Set([...(aliases_effort || []).map((a) => a.replaceAll("{effort}", e.effort)), ...(e.effort_defaut ? aliases_defaut || [] : [])])];
    const fiche = { ...partage, ...e, aliases };
    for (const k of CHAMPS_PRIVES_MODELE) delete fiche[k];
    // la recommandation d'un couple est celle d'OPÉRER (`verdict_operer`, natures, pourquoi) : retirée avec elle
    delete fiche.recommandation;
    fiche.description = commun ? null : sansPrive(`${e.description}\n\n${description_commune}`);
    return fiche;
  });
}
