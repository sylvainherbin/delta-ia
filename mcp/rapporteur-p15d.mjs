// Événements du même lancement que le TAP ; entryFile vient du runner Node.
export default async function* (source) {
  for await (const evenement of source) {
    if (evenement.type === 'test:pass' || evenement.type === 'test:fail')
      yield JSON.stringify(evenement) + '\n';
  }
}
