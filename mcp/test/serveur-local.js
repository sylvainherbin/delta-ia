// Sert le gestionnaire Vercel en local : node test/serveur-local.js [port]
import http from "node:http";
import handler from "../api/mcp.js";
const port = Number(process.argv[2] || 8799);
http.createServer((req, res) => handler(req, res)).listen(port, "127.0.0.1", () => console.log(`MCP Delta local : http://127.0.0.1:${port}/`));
