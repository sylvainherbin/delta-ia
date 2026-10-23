// Classement lexical, sans service externe. Les noms exacts D105 restent traités par le serveur.
export const MOTS_VIDES = new Set(['de', 'la', 'le', 'les', 'du', 'des', 'et', 'ou', 'en', 'the', 'a', 'of', 'to', 'for',
  'un', 'une', 'dans', 'avec', 'pour', 'sur', 'au', 'aux', 'ce', 'ces', 'son', 'sa', 'ses', 'comment', 'je', 'mon', 'ma', 'mes']);
export const sansAccents = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
// Petites familles lexicales bilingues pour les descriptions du catalogue ; pas de priorité par identifiant.
const familles = new Map([
  ...['reduire', 'reduit', 'reduction', 'liberer', 'libere'].map(m => [m, 'liber']),
  ...['compacter', 'compact', 'compaction'].map(m => [m, 'compact']),
  ...['contexte', 'context'].map(m => [m, 'context']),
  ...['conversation', 'chat'].map(m => [m, 'conversation']),
  ...['memoire', 'memory'].map(m => [m, 'memoire']),
  ...['reprendre', 'resume', 'reprend'].map(m => [m, 'reprendre']),
]);
const radical = m => familles.get(m) || (m.length > 4 ? m.replace(/s$/, '') : m);
export const motsLexicaux = s => (String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').match(/[a-zA-Z0-9_]+/g) || [])
  .flatMap(m => /[a-z][A-Z]/.test(m) ? [m, ...m.replace(/([a-z])([A-Z])/g, '$1 $2').split(' ')] : [m])
  .map(m => m.toLowerCase()).filter(m => m.length >= 2 && !MOTS_VIDES.has(m)).map(radical);
export function indexer(texte) {
  const tokens = motsLexicaux(texte);
  return { brut: sansAccents(texte), tokens, termes: new Set(tokens) };
}
export function presence(texte, mot, repli = false) {
  const index = typeof texte === 'string' ? indexer(texte) : texte;
  // Les options gardent leurs préfixes : --delta ne doit pas se confondre avec -delta.
  if (/^[-/]/.test(mot)) return index.brut.includes(mot) || (repli && index.brut.includes(mot.slice(1)));
  // Identifiants, alias et chemins restent littéraux : ne pas découper un couple modèle × effort.
  if (/[._:=]/.test(mot) || /-\d/.test(mot)) return index.brut.includes(mot);
  const recherches = motsLexicaux(mot);
  return recherches.length > 0 && recherches.every(m => index.termes.has(m));
}
export function pertinence(nom, texte, mots, repli = false) {
  const trouves = mots.filter(m => presence(texte, m, repli));
  const titre = mots.filter(m => presence(nom, m, repli)).length;
  const tokens = typeof texte === 'string' ? motsLexicaux(texte) : texte.tokens;
  const groupes = trouves.map(m => new Set(motsLexicaux(m))).filter(g => g.size);
  // Plus petite fenêtre couvrant tous les termes présents, sans dépendre de leur ordre.
  let proximite = 0;
  if (groupes.length > 1) {
    const compte = groupes.map(() => 0);
    let gauche = 0, couverts = 0, meilleur = Infinity;
    for (let droite = 0; droite < tokens.length; droite++) {
      groupes.forEach((g, i) => { if (g.has(tokens[droite]) && compte[i]++ === 0) couverts++; });
      while (couverts === groupes.length) {
        meilleur = Math.min(meilleur, droite - gauche + 1);
        groupes.forEach((g, i) => { if (g.has(tokens[gauche]) && --compte[i] === 0) couverts--; });
        gauche++;
      }
    }
    if (Number.isFinite(meilleur)) proximite = 80 / meilleur;
  }
  // Une longue page ne gagne pas mécaniquement parce qu'elle contient tous les mots une fois.
  const longueur = 0.25 + 0.75 * tokens.length / 120;
  return { trouves: trouves.length, poids: trouves.length * 50 + trouves.length * 120 / (1 + longueur) + titre * 160 + proximite };
}
