/**
 * Build step Netlify: gera web/_redirects (proxy /api → backend) e web/runtime-config.js.
 * Defina no painel Netlify: SCHEDULER_API_BASE = https://seu-backend.com  (sem barra final)
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.join(__dirname, "..", "web");

const base = (process.env.SCHEDULER_API_BASE || "").trim().replace(/\/$/, "");

const redirectLines = [];
if (base) {
  redirectLines.push(`# Proxy /api para o backend (mesma origem no browser)`);
  redirectLines.push(`/api/*  ${base}/api/:splat  200`);
}
redirectLines.push(`# SPA`);
redirectLines.push(`/*  /index.html  200`);

fs.writeFileSync(path.join(webDir, "_redirects"), `${redirectLines.join("\n")}\n`, "utf8");

const runtimeConfig = `/* Gerado por scripts/netlify-build-web.mjs — não editar no deploy */
window.__SCHEDULER_API_BASE__ = "";
`;
fs.writeFileSync(path.join(webDir, "runtime-config.js"), runtimeConfig, "utf8");

if (base) {
  console.log(`OK: proxy Netlify /api/* → ${base}/api/*`);
} else {
  console.warn("Aviso: SCHEDULER_API_BASE não definido — /api no Netlify não será proxyado (defina a variável no site).");
}
