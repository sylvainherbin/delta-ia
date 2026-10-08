// Delta — lecture publique et anonyme du compteur agrégé du serveur MCP : GET /stats?jours=N (N ≤ 90, défaut 30).
// Lecture seule ; sans stockage Upstash, répond {"statut":"inactif"}.
import { joursDemandes, lireStats } from "../lib/compteur.js";

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "content-type");
  if (req.method === "OPTIONS") { res.statusCode = 204; return res.end(); }
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") {
    res.statusCode = 405; res.setHeader("Allow", "GET, OPTIONS");
    return res.end(JSON.stringify({ statut: "erreur", raison: "GET uniquement" }));
  }
  let corps, code = 200;
  try {
    corps = await lireStats(joursDemandes(new URL(req.url, "http://x").searchParams.get("jours")));
  } catch {
    corps = { statut: "erreur", raison: "stockage illisible" }; code = 502;
  }
  res.statusCode = code;
  res.setHeader("Cache-Control", corps.statut === "ok" ? "public, max-age=300" : "no-store");
  res.end(JSON.stringify(corps));
}
