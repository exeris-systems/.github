#!/usr/bin/env node
// Golden file for an MCP server's tool surface — the TS analogue of a japicmp /
// api-extractor report for a server whose public API is `tools/list`, not its
// TypeScript exports. Writes a canonical JSON (sorted tools, sorted keys) of
// every tool's name, description and inputSchema, then compares it with the
// committed golden.
//
//   node mcp-tool-surface.mjs --server dist/server.js --golden api/tools.api.json          # CI: fail on drift
//   node mcp-tool-surface.mjs --server dist/server.js --golden api/tools.api.json --accept # local: rewrite golden
//
// Exit 0 = identical; 2 = drift (diff printed); 3 = golden missing (run --accept).
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname } from "node:path";

const args = Object.fromEntries(process.argv.slice(2).map((a, i, all) => a.startsWith("--") ? [a.slice(2), all[i + 1]?.startsWith("--") || all[i + 1] === undefined ? true : all[i + 1]] : []).filter(Boolean));
const serverPath = args.server ?? "dist/server.js";
const goldenPath = args.golden ?? "api/tools.api.json";

const canon = (v) => Array.isArray(v) ? v.map(canon) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canon(v[k])])) : v;

const client = new Client({ name: "exeris-tool-surface", version: "0" });
await client.connect(new StdioClientTransport({ command: process.execPath, args: [serverPath], env: { ...process.env, ...(args.env ? Object.fromEntries(args.env.split(",").map((kv) => kv.split("="))) : {}) } }));
const { tools } = await client.listTools();
await client.close();

const surface = canon({
  tools: tools.map((t) => ({ name: t.name, description: t.description ?? "", inputSchema: t.inputSchema, ...(t.annotations ? { annotations: t.annotations } : {}) })).sort((a, b) => a.name.localeCompare(b.name)),
});
const next = JSON.stringify(surface, null, 2) + "\n";

if (args.accept) { mkdirSync(dirname(goldenPath), { recursive: true }); writeFileSync(goldenPath, next); console.log(`accepted ${surface.tools.length} tools → ${goldenPath}`); process.exit(0); }
if (!existsSync(goldenPath)) { console.error(`no golden at ${goldenPath}; run with --accept`); process.exit(3); }
const prev = readFileSync(goldenPath, "utf8");
if (prev === next) { console.log(`tool surface unchanged (${surface.tools.length} tools)`); process.exit(0); }

const a = JSON.parse(prev).tools, b = surface.tools;
const names = (x) => new Set(x.map((t) => t.name));
for (const n of names(a)) if (!names(b).has(n)) console.error(`- removed tool: ${n}   ← breaking (MAJOR)`);
for (const n of names(b)) if (!names(a).has(n)) console.error(`+ added tool:   ${n}   ← additive (MINOR)`);
for (const t of b) { const o = a.find((x) => x.name === t.name); if (o && JSON.stringify(o) !== JSON.stringify(t)) {
  const req = (s) => new Set(s.inputSchema?.required ?? []);
  const newlyRequired = [...req(t)].filter((r) => !req(o).has(r));
  console.error(`~ changed tool: ${t.name}${newlyRequired.length ? `   ← new required input(s) ${newlyRequired.join(",")} — breaking (MAJOR)` : ""}`);
} }
console.error(`\ntool surface drifted from ${goldenPath}. If intended: re-run with --accept, commit the golden, and classify the change in the PR (pr-conventions.md).`);
process.exit(2);
