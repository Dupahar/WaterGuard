"""Tamper-evident reports: two Merkle roots per run, plus the proofs that go with them.

    python -m waterguard.ledger build <run_id>      write data/runs/<run_id>/proof.json
    python -m waterguard.ledger check <run_id>      recompute both roots from the files on disk

reportRoot  commits to every output file byte for byte (facts.json, impact.tif, every layer), so a copy
            of a report anywhere can be checked against the one number anchored on-chain.
claimsRoot  commits to one leaf per settlement: where it is, its road status and how many people are
            stranded. It contains only what the pipeline derives from open data, so an independent
            party who re-runs the same code gets the same root. Relief payouts are proven against it.

Everything is SHA-256 with sorted-pair inner nodes (see contracts/WaterGuardLedger.sol), which a browser
can rebuild with WebCrypto alone (web/proof.js).
"""
import hashlib
import json
import os
import subprocess
import sys

from .config import ROOT
from .pipeline import RUNS_DIR

REPORT_SUFFIXES = (".json", ".geojson", ".tif", ".png")
NOT_IN_REPORT = {"proof.json", "evidence.tif", "inspection.json"}   # analysis caches / later layers
STATUS_CODE = {"partly cut": 1, "cut off": 2}       # everything else ("ok", "no mapped road", ...) is 0


def sha(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _node(a: bytes, b: bytes) -> bytes:
    return sha(a + b) if a < b else sha(b + a)


def merkle(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
    """Root and one proof per leaf (same order as `leaves`). An odd node is carried up unchanged."""
    if not leaves:
        return b"\x00" * 32, []
    level = list(leaves)
    pos = list(range(len(leaves)))        # index of each original leaf in the current level
    proofs = [[] for _ in leaves]
    while len(level) > 1:
        for i, p in enumerate(pos):
            sib = p ^ 1
            if sib < len(level):
                proofs[i].append(level[sib])
        level = [_node(level[j], level[j + 1]) if j + 1 < len(level) else level[j] for j in range(0, len(level), 2)]
        pos = [p // 2 for p in pos]
    return level[0], proofs


def verify(proof: list[bytes], root: bytes, leaf: bytes) -> bool:
    h = leaf
    for p in proof:
        h = _node(h, p)
    return h == root


def report_key(run_id: str, version: str | None = None) -> bytes:
    """On-chain id of a report: the run (area + event time) AND the code that produced it, so a corrected
    pipeline publishes a new record instead of colliding with (or silently replacing) an old one, and a
    verifier only lands on the same record if it runs the same code."""
    return sha(f"{run_id}@{(version or code_version())[:12]}".encode())


def e5(v: float) -> int:
    return int(round(v * 1e5))


def _word(v: int | bytes) -> bytes:
    """One ABI word: 32-byte value, signed ints two's complement (abi.encode of int32/uint*)."""
    if isinstance(v, bytes):
        return v.rjust(32, b"\x00")
    return (v % (1 << 256)).to_bytes(32, "big")


def settlement_leaf(key: bytes, sid: bytes, lon_e5: int, lat_e5: int, status: int, buildings: int,
                    people: int) -> bytes:
    """Must equal ReliefFund.leafOf(...)."""
    return sha(sha(b"".join(_word(x) for x in (key, sid, lon_e5, lat_e5, status, buildings, people))))


def file_leaf(name: str, data: bytes) -> bytes:
    return sha(sha(sha(name.encode()) + sha(data)))


# modules whose code decides the numbers in a report; a change to anything else (dashboard, ledger,
# docs) must not change a report's identity
ANALYSIS_CODE = ["waterguard/pipeline.py", "waterguard/detect.py", "waterguard/sar.py", "waterguard/optical.py",
                 "waterguard/terrain.py", "waterguard/access.py", "waterguard/damage.py", "waterguard/osm.py",
                 "waterguard/grid.py", "waterguard/readers.py", "waterguard/config.py", "waterguard/providers"]


def code_version() -> str:
    """The commit that last changed the analysis code (WATERGUARD_VERSION overrides, e.g. in a container)."""
    v = os.getenv("WATERGUARD_VERSION")
    if v:
        return v
    try:
        return subprocess.run(["git", "log", "-1", "--format=%H", "--", *ANALYSIS_CODE], cwd=ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "0" * 40
    except Exception:
        return "0" * 40


def settlements(run_dir) -> list[dict]:
    """Claims leaves, in a canonical order (by settlement id)."""
    p = run_dir / "settlements.geojson"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
        pr, (lon, lat) = f["properties"], f["geometry"]["coordinates"][:2]
        lon_e5, lat_e5 = e5(lon), e5(lat)
        name = pr.get("name") or ""
        out.append({
            "name": name or f"unnamed {pr.get('kind', 'settlement')} ({int(pr.get('buildings') or 0)} buildings)",
            "name_ne": pr.get("name_ne"),
            "settlement_id": "0x" + sha(f"{name}|{lon_e5}|{lat_e5}".encode()).hex(),
            "lon_e5": lon_e5, "lat_e5": lat_e5,
            "status": STATUS_CODE.get(pr.get("vehicle_status"), 0),
            "status_text": pr.get("vehicle_status"),
            "buildings": int(pr.get("buildings") or 0),
            "people_stranded": int(round((pr.get("people_est") or 0) * (pr.get("vehicle_stranded_share") or 0))),
        })
    return sorted(out, key=lambda s: s["settlement_id"])


def files(run_dir) -> list[dict]:
    out = []
    for p in sorted(run_dir.iterdir()):
        if p.is_file() and p.suffix in REPORT_SUFFIXES and p.name not in NOT_IN_REPORT:
            data = p.read_bytes()
            out.append({"name": p.name, "sha256": sha(data).hex(), "bytes": len(data),
                        "leaf": "0x" + file_leaf(p.name, data).hex()})
    return out


def build(run_id: str, write: bool = True) -> dict:
    """Both trees for a finished run. Keeps any on-chain receipt already recorded in proof.json."""
    d = RUNS_DIR / run_id
    facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    version = code_version()
    key = report_key(run_id, version)

    fl = files(d)
    report_root, _ = merkle([bytes.fromhex(f["leaf"][2:]) for f in fl])

    st = settlements(d)
    leaves = [settlement_leaf(key, bytes.fromhex(s["settlement_id"][2:]), s["lon_e5"], s["lat_e5"], s["status"],
                              s["buildings"], s["people_stranded"]) for s in st]
    claims_root, proofs = merkle(leaves)
    for s, leaf, pf in zip(st, leaves, proofs):
        s["leaf"] = "0x" + leaf.hex()
        s["proof"] = ["0x" + x.hex() for x in pf]

    old = {}
    if (d / "proof.json").exists():
        old = json.loads((d / "proof.json").read_text(encoding="utf-8"))
    out = {
        "run_id": run_id,
        "key": "0x" + key.hex(),
        "report_root": "0x" + report_root.hex(),
        "claims_root": "0x" + claims_root.hex(),
        "bbox_e5": [e5(v) for v in facts["area"]["bbox"]],
        "event_time_utc": facts["event_time_utc"],
        "code_version": version,
        "files": fl,
        "settlements": st,
        "anchors": old.get("anchors", []),
    }
    if old and (old.get("key"), old.get("report_root"), old.get("claims_root")) != (out["key"], out["report_root"], out["claims_root"]):
        out["anchors"] = []   # the files changed since they were anchored: old receipts no longer apply
    if write:
        (d / "proof.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def load(run_id: str) -> dict | None:
    p = RUNS_DIR / run_id / "proof.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def check(run_id: str) -> dict:
    """Recompute from disk and compare with proof.json (what was anchored)."""
    saved = load(run_id)
    now = build(run_id, write=False)
    return {"report_root_matches": bool(saved) and saved["report_root"] == now["report_root"],
            "claims_root_matches": bool(saved) and saved["claims_root"] == now["claims_root"],
            "changed_files": [f["name"] for f in now["files"]
                              if f not in (saved or {}).get("files", [])],
            "report_root": now["report_root"], "claims_root": now["claims_root"]}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("build", "check"):
        sys.exit(__doc__)
    cmd, rid = sys.argv[1:]
    res = build(rid) if cmd == "build" else check(rid)
    if cmd == "build":
        res = {k: res[k] for k in ("key", "report_root", "claims_root")} | {
            "files": len(res["files"]), "settlements": len(res["settlements"])}
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
