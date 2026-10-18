// Independent report check, entirely in the browser: hash every file, rebuild the Merkle roots,
// and compare them with what the public ledger says, read straight from a public RPC node
// (not through the WaterGuard server). Mirrors waterguard/ledger.py and contracts/WaterGuardLedger.sol.
const hex = (b) => "0x" + [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
const unhex = (h) => Uint8Array.from(h.slice(2).match(/../g).map((x) => parseInt(x, 16)));
const sha = async (b) => new Uint8Array(await crypto.subtle.digest("SHA-256", b));
const cat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let i = 0; for (const x of a) { o.set(x, i); i += x.length; } return o; };
const less = (a, b) => { for (let i = 0; i < 32; i++) if (a[i] !== b[i]) return a[i] < b[i]; return false; };
const node = (a, b) => sha(less(a, b) ? cat(a, b) : cat(b, a));

async function merkleRoot(leaves) {
  if (!leaves.length) return new Uint8Array(32);
  let level = leaves;
  while (level.length > 1) {
    const next = [];
    for (let j = 0; j < level.length; j += 2) next.push(j + 1 < level.length ? await node(level[j], level[j + 1]) : level[j]);
    level = next;
  }
  return level[0];
}
async function verifyProof(proof, root, leaf) {
  let h = leaf;
  for (const p of proof) h = await node(h, unhex(p));
  return hex(h) === root;
}
const word = (v) => { // one ABI word (int32 two's complement, uints, bytes32)
  if (typeof v === "string") return unhex(v);
  let n = BigInt(v); if (n < 0n) n += 1n << 256n;
  return unhex("0x" + n.toString(16).padStart(64, "0"));
};
async function settlementLeaf(key, s) {
  const enc = cat(...[key, s.settlement_id, s.lon_e5, s.lat_e5, s.status, s.buildings, s.people_stranded].map(word));
  return sha(await sha(enc));
}

async function readLedger(chain, key) {
  const r = await fetch(chain.rpc, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call",
      params: [{ to: chain.registry, data: chain.status_selector + key.slice(2) }, "latest"] }) }).then((r) => r.json());
  if (!r.result || r.result === "0x") throw new Error(r.error?.message || "empty answer from RPC");
  const w = (i) => "0x" + r.result.slice(2 + 64 * i, 2 + 64 * (i + 1));
  return { report_root: w(0), claims_root: w(1), published_at: parseInt(w(3), 16), confirmations: parseInt(w(4), 16),
           disputed: parseInt(w(5), 16) === 1, final: parseInt(w(6), 16) === 1 };
}

async function verifyInBrowser(runId, proof, chain, log) {
  const ok = (b) => (b ? "✓" : "✗");
  log(`Hashing ${proof.files.length} files in your browser…`);
  const leaves = [];
  let filesOk = true;
  for (const f of proof.files) {
    const data = new Uint8Array(await fetch(`/runs/${runId}/${f.name}`).then((r) => r.arrayBuffer()));
    const h = hex(await sha(data));
    filesOk &&= h.slice(2) === f.sha256;
    leaves.push(await sha(cat(await sha(new TextEncoder().encode(f.name)), await sha(data))).then(sha));
  }
  const reportRoot = hex(await merkleRoot(leaves));
  const claimLeaves = [];
  let claimsOk = true;
  for (const s of proof.settlements) {
    const leaf = await settlementLeaf(proof.key, s);
    claimsOk &&= hex(leaf) === s.leaf && await verifyProof(s.proof, proof.claims_root, leaf);
    claimLeaves.push(leaf);
  }
  const claimsRoot = hex(await merkleRoot(claimLeaves));
  log(`${ok(reportRoot === proof.report_root)} files → report root ${reportRoot.slice(0, 18)}…`);
  log(`${ok(claimsRoot === proof.claims_root && claimsOk)} ${proof.settlements.length} settlement claims → claims root ${claimsRoot.slice(0, 18)}…`);
  if (!chain?.registry) { log("No public ledger configured on this server: roots checked locally only."); return; }
  log(`Asking ${chain.network} directly (${new URL(chain.rpc).host})…`);
  try {
    const L = await readLedger(chain, proof.key);
    if (!L.published_at) { log("✗ This report has not been anchored yet."); return; }
    const same = L.report_root === reportRoot && L.claims_root === claimsRoot;
    log(`${ok(same)} roots ${same ? "match" : "DO NOT match"} the ledger (anchored ${new Date(L.published_at * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC)`);
    log(`${L.disputed ? "⚠ disputed by a verifier" : L.final ? "✓ final" : "… awaiting independent confirmation"} · ${L.confirmations} independent confirmation${L.confirmations === 1 ? "" : "s"} (${chain.quorum} needed)`);
    return same;
  } catch (e) { log("Could not reach the public RPC: " + e.message); }
}
window.WGProof = { verifyInBrowser };
