// Delta — compteur agrégé et anonyme du serveur MCP (amende D66), stocké dans Upstash Redis par son API REST.
// Seuls des comptes par jour UTC : jamais d'argument, de requête de recherche, d'adresse IP, de User-Agent, de session
// ni de version de client. Sans KV_REST_API_URL et KV_REST_API_TOKEN, rien n'est compté et /stats répond « inactif ».
// Aucune dépendance : un simple fetch.

const DELAI_MS = 500;
const EXPIRATION_S = 400 * 86400;
const JOURS_MAX = 90;
const JOURS_DEFAUT = 30;
const CLIENTS_MAX = 50;  // clients lus par jour : le champ est fourni par le client, la lecture reste bornée

export const stockage = () => {
  const url = process.env.KV_REST_API_URL, jeton = process.env.KV_REST_API_TOKEN;
  return url && jeton ? { url: url.replace(/\/$/, ""), jeton } : null;
};

const jourUtc = (d = new Date()) => d.toISOString().slice(0, 10);
export const cleJour = (jour) => `mcp:j:${jour}`;

// clientInfo.name : 40 caractères au plus, caractères sûrs seulement ; vide après nettoyage = non compté
export const nomClient = (v) => (typeof v === "string" ? v.normalize("NFKD").replace(/[^A-Za-z0-9._ -]/g, "").trim().slice(0, 40) : "");

// Champs du hash du jour pour une requête, tous dérivés de la ligne du journal D66 (ligneJournal).
export function champs(ligne) {
  const f = [`req:${ligne.methode}`];
  const nom = ligne.outil ?? ligne.methode;
  if (ligne.outil) f.push(`outil:${ligne.outil}`);
  if (ligne.outil && ligne.nb_resultats === 0) f.push(`zero:${ligne.outil}`);
  if (ligne.statut !== "ok") f.push(`erreur:${nom}`);
  const client = ligne.client ? nomClient(ligne.client.name) : "";
  if (client) f.push(`client:${client}`);
  return f;
}

async function pipeline(s, commandes, delai = DELAI_MS) {
  const r = await fetch(`${s.url}/pipeline`, { method: "POST", signal: AbortSignal.timeout(delai),
    headers: { Authorization: `Bearer ${s.jeton}`, "Content-Type": "application/json" }, body: JSON.stringify(commandes) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const rep = await r.json();
  if (!Array.isArray(rep) || rep.some((x) => x && x.error)) throw new Error("réponse de stockage invalide");
  return rep;
}

const enCours = new Set();
// Résout quand les écritures lancées sont terminées (tests ; jamais attendu par le gestionnaire).
export const compteursEnCours = () => Promise.all([...enCours]);

// Un seul appel pipeline par requête MCP (lot compris). Lancé sans attendre ; toute erreur est avalée.
export function compter(lignes, maintenant = new Date()) {
  const s = stockage();
  if (!s || !lignes.length) return null;
  const cle = cleJour(jourUtc(maintenant));
  const commandes = lignes.flatMap(champs).map((f) => ["HINCRBY", cle, f, 1]);
  commandes.push(["EXPIRE", cle, EXPIRATION_S]);
  const p = pipeline(s, commandes).then(() => {}, () => { console.log(JSON.stringify({ compteur: "echec" })); });
  enCours.add(p);
  p.finally(() => enCours.delete(p));
  // Vercel : prolonge l'exécution après la réponse, sans dépendance (même mécanisme que @vercel/functions)
  try { globalThis[Symbol.for("@vercel/request-context")]?.get?.()?.waitUntil?.(p); } catch { /* hors Vercel */ }
  return p;
}

// ---------------------------------------------------------------------------------------------- lecture

const GROUPES = { req: "req", outil: "outils", zero: "zero", erreur: "erreurs", client: "clients" };
// objets sans prototype : un nom de client comme « __proto__ » reste une simple clé
const vide = () => ({ req: Object.create(null), outils: Object.create(null), zero: Object.create(null), erreurs: Object.create(null), clients: Object.create(null) });

function aplatir(r) {  // HGETALL REST : tableau [champ, valeur, ...] (ou objet selon le format)
  if (Array.isArray(r)) { const o = {}; for (let i = 0; i + 1 < r.length; i += 2) o[r[i]] = r[i + 1]; return o; }
  return r && typeof r === "object" ? r : {};
}

function ajouter(cible, hash) {
  for (const [champ, valeur] of Object.entries(hash)) {
    const i = champ.indexOf(":");
    const groupe = GROUPES[champ.slice(0, i)];
    const n = Number(valeur);
    if (i < 1 || !groupe || !Number.isFinite(n)) continue;
    cible[groupe][champ.slice(i + 1)] = (cible[groupe][champ.slice(i + 1)] || 0) + n;
  }
  return cible;
}

const plusFrequents = (o, max) => Object.fromEntries(Object.entries(o).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, max));

export function joursDemandes(valeur) {
  const n = Number.parseInt(valeur, 10);
  return Number.isFinite(n) ? Math.max(1, Math.min(JOURS_MAX, n)) : JOURS_DEFAUT;
}

export async function lireStats(jours, maintenant = new Date()) {
  const s = stockage();
  if (!s) return { statut: "inactif" };
  const liste = Array.from({ length: jours }, (_, i) => jourUtc(new Date(maintenant.getTime() - (jours - 1 - i) * 864e5)));
  const rep = await pipeline(s, liste.map((j) => ["HGETALL", cleJour(j)]), 2000);
  const total = vide();
  const detail = liste.map((jour, i) => {
    const j = ajouter(vide(), aplatir(rep[i]?.result));
    j.clients = plusFrequents(j.clients, CLIENTS_MAX);
    for (const g of Object.keys(total)) for (const [k, v] of Object.entries(j[g])) total[g][k] = (total[g][k] || 0) + v;
    return { jour, ...j };
  });
  total.clients = plusFrequents(total.clients, CLIENTS_MAX);
  return { statut: "ok", genere_le: maintenant.toISOString(), jours: detail, total };
}
