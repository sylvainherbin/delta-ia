// Format public v2 : données communes par modèle, un enregistrement par couple.
// Lecture pure partagée par le site et le MCP ; aucun HTML ni requête réseau.
export function developperModeles(doc) {
  if (doc.schema_version !== 2 || !doc.modeles || Array.isArray(doc.modeles)) throw new Error("format modèles inattendu");
  return doc.entrees.map((e) => {
    const m = doc.modeles[e.modele];
    if (!m) throw new Error(`modèle absent : ${e.modele}`);
    const { aliases_effort, aliases_defaut, description_commune, ...commun } = m;
    const aliases = [...new Set([...(aliases_effort || []).map((a) => a.replaceAll("{effort}", e.effort)), ...(e.effort_defaut ? aliases_defaut || [] : [])])];
    return { ...commun, ...e, aliases, description: `${e.description}\n\n${description_commune}` };
  });
}
