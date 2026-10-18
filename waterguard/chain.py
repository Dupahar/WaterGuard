"""Anchor reports on an EVM chain and pay relief against them.

    python -m waterguard.chain compile                         contracts/WaterGuardLedger.sol -> contracts/build/
    python -m waterguard.chain wallet                          make a new key for .env (prints the address to fund)
    python -m waterguard.chain deploy [--quorum 2] [--window 3600]
    python -m waterguard.chain publish <run_id>                anchor both roots (builds proof.json first)
    python -m waterguard.chain confirm <run_id> [--rerun] [--as-verifier]
                                         as an independent verifier: re-run from the on-chain record, then
                                         confirm if the claims match (dispute if they do not)
    python -m waterguard.chain status <run_id>
    python -m waterguard.chain add-verifier <address>
    python -m waterguard.chain open-fund --bbox W S E N --from 2026-08-01 --to 2026-09-30 --per-person-wei N
                                         --cap-wei N --partner 0x.. [--deposit-wei N] [--min-status 1|2]
    python -m waterguard.chain claim <run_id> <fund_id>        pay every eligible settlement in the run
    python -m waterguard.chain resolve <report_key> upheld|rejected   owner settles a dispute

.env:  WATERGUARD_CHAIN_RPC   (default: Ethereum Sepolia public RPC)
       WATERGUARD_LEDGER_KEY  private key of the publishing account
       WATERGUARD_VERIFIER_KEY  (optional) a second party's key, used with --as-verifier
Contract addresses live in contracts/deployments/<chain_id>.json once deployed.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

from . import ledger
from .config import ROOT

BUILD = ROOT / "contracts" / "build" / "WaterGuardLedger.json"
DEPLOYMENTS = ROOT / "contracts" / "deployments"
NETWORKS = {
    80002: {"name": "Polygon Amoy", "explorer": "https://amoy.polygonscan.com", "rpc": "https://polygon-amoy-bor-rpc.publicnode.com"},
    11155111: {"name": "Ethereum Sepolia", "explorer": "https://sepolia.etherscan.io",
               "rpc": "https://ethereum-sepolia-rpc.publicnode.com"},
    84532: {"name": "Base Sepolia", "explorer": "https://sepolia.basescan.org", "rpc": "https://sepolia.base.org"},
}
DEFAULT_RPC = NETWORKS[11155111]["rpc"]     # where the contracts are deployed (contracts/deployments/)


def compile_contracts() -> dict:
    import solcx
    solcx.install_solc("0.8.26")
    src = ROOT / "contracts" / "WaterGuardLedger.sol"
    out = solcx.compile_standard({
        "language": "Solidity",
        "sources": {src.name: {"content": src.read_text(encoding="utf-8")}},
        "settings": {"optimizer": {"enabled": True, "runs": 200}, "evmVersion": "paris", "viaIR": True,
                     "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}}},
    }, solc_version="0.8.26")
    art = {name: {"abi": c["abi"], "bytecode": "0x" + c["evm"]["bytecode"]["object"]}
           for name, c in out["contracts"][src.name].items() if name in ("ReportRegistry", "ReliefFund")}
    BUILD.parent.mkdir(parents=True, exist_ok=True)
    BUILD.write_text(json.dumps(art, indent=1), encoding="utf-8")
    return art


def artifacts() -> dict:
    return json.loads(BUILD.read_text(encoding="utf-8")) if BUILD.exists() else compile_contracts()


def _ts(s: str) -> int:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp())


def b32(h: str) -> bytes:
    return bytes.fromhex(h[2:] if h.startswith("0x") else h)


class Ledger:
    """Thin client around the two contracts. `w3` may be any Web3 (tests pass an in-memory chain)."""

    def __init__(self, w3=None, key: str | None = None, deployment: dict | None = None):
        from web3 import Web3
        self.w3 = w3 or Web3(Web3.HTTPProvider(os.getenv("WATERGUARD_CHAIN_RPC", DEFAULT_RPC),
                                               request_kwargs={"timeout": 30}))
        self.chain_id = self.w3.eth.chain_id
        key = key if key is not None else os.getenv("WATERGUARD_LEDGER_KEY")
        self.acct = self.w3.eth.account.from_key(key) if key else None
        self.art = artifacts()
        self.dep = deployment if deployment is not None else self._load_deployment()
        self.registry = self._contract("ReportRegistry")
        self.relief = self._contract("ReliefFund")

    # -- plumbing ---------------------------------------------------------------------------------------
    def _load_deployment(self):
        p = DEPLOYMENTS / f"{self.chain_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _contract(self, name):
        addr = self.dep.get(name)
        return self.w3.eth.contract(address=addr, abi=self.art[name]["abi"]) if addr else None

    @property
    def network(self):
        return NETWORKS.get(self.chain_id, {"name": f"chain {self.chain_id}", "explorer": None})

    def tx_url(self, tx):
        ex = self.network.get("explorer")
        return f"{ex}/tx/{tx}" if ex else None

    def address_url(self, addr):
        ex = self.network.get("explorer")
        return f"{ex}/address/{addr}" if ex else None

    def _send(self, fn, value=0):
        if self.acct is None:
            raise RuntimeError("WATERGUARD_LEDGER_KEY is not set")
        tx = fn.build_transaction({"from": self.acct.address, "value": value,
                                   "nonce": self.w3.eth.get_transaction_count(self.acct.address, "pending"),
                                   "chainId": self.chain_id})
        signed = self.acct.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        rc = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
        if rc.status != 1:
            raise RuntimeError(f"transaction reverted: {h.hex()}")
        return rc

    def _deploy(self, name, *args):
        c = self.w3.eth.contract(abi=self.art[name]["abi"], bytecode=self.art[name]["bytecode"])
        return self._send(c.constructor(*args)).contractAddress

    # -- setup ------------------------------------------------------------------------------------------
    def deploy(self, quorum=2, window_s=3600, save=True):
        reg = self._deploy("ReportRegistry", quorum, window_s)
        rel = self._deploy("ReliefFund", reg)
        self.dep = {"chain_id": self.chain_id, "network": self.network["name"], "ReportRegistry": reg,
                    "ReliefFund": rel, "deployer": self.acct.address, "quorum": quorum, "challenge_window_s": window_s,
                    "deployed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if save:
            DEPLOYMENTS.mkdir(parents=True, exist_ok=True)
            (DEPLOYMENTS / f"{self.chain_id}.json").write_text(json.dumps(self.dep, indent=1), encoding="utf-8")
        self.registry, self.relief = self._contract("ReportRegistry"), self._contract("ReliefFund")
        return self.dep

    def resolve(self, key: str, upheld: bool) -> dict:
        """Owner settles a dispute. upheld=True: the report can never back a payout."""
        rc = self._send(self.registry.functions.resolveDispute(b32(key), upheld))
        return {"tx": rc.transactionHash.to_0x_hex(), "tx_url": self.tx_url(rc.transactionHash.to_0x_hex())}

    def add_verifier(self, addr, allowed=True):
        return self._send(self.registry.functions.setVerifier(addr, allowed))

    # -- reports ----------------------------------------------------------------------------------------
    def status(self, run_id_or_key: str) -> dict:
        key = b32(run_id_or_key) if run_id_or_key.startswith("0x") else ledger.report_key(run_id_or_key)
        rr, cr, ev, pub, conf, disp, fin, ver = self.registry.functions.status(key).call()
        return {"key": "0x" + key.hex(), "published": pub > 0, "report_root": "0x" + rr.hex(),
                "claims_root": "0x" + cr.hex(), "event_time": ev, "published_at": pub, "confirmations": conf,
                "quorum": self.registry.functions.quorum().call(), "disputed": disp, "final": fin,
                "code_version": "0x" + ver.hex()}

    def _record(self, run_id, proof, kind, rc):
        a = {"kind": kind, "chain_id": self.chain_id, "network": self.network["name"],
             "registry": self.registry.address, "by": self.acct.address, "tx": rc.transactionHash.to_0x_hex(),
             "block": rc.blockNumber, "tx_url": self.tx_url(rc.transactionHash.to_0x_hex()),
             "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        proof["anchors"] = [x for x in proof.get("anchors", [])
                            if not (x["chain_id"] == self.chain_id and x["kind"] == kind and x["by"] == a["by"])] + [a]
        (ledger.RUNS_DIR / run_id / "proof.json").write_text(json.dumps(proof, indent=1, ensure_ascii=False),
                                                              encoding="utf-8")
        return a

    def publish(self, run_id: str, skip_review: bool = False) -> dict:
        from . import inspector
        ok, why = inspector.ready_to_publish(run_id)
        if not ok and not skip_review:
            raise RuntimeError(f"not publishing: {why} (review them in the dashboard's Inspect tab)")
        p = ledger.build(run_id)
        st = self.status(run_id)
        if st["published"]:
            if st["report_root"] != p["report_root"] or st["claims_root"] != p["claims_root"]:
                raise RuntimeError("a different version of this report is already anchored")
            return {"already": True} | st
        ev = int(datetime.strptime(p["event_time_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
        uri = f"{os.getenv('WATERGUARD_PUBLIC_URL', 'https://d1sgb39rsg0dlm.cloudfront.net')}/api/runs/{run_id}/proof"
        rc = self._send(self.registry.functions.publish(
            b32(p["key"]), b32(p["report_root"]), b32(p["claims_root"]), p["bbox_e5"], ev,
            bytes.fromhex(p["code_version"][:40].ljust(40, "0")), uri))
        a = self._record(run_id, p, "published", rc)
        ins = inspector.load(run_id)
        if not ok and ins:   # say so wherever the anchor is shown
            a["unreviewed_cells"] = ins["summary"]["pending_review"]
            p = ledger.load(run_id)
            p["anchors"] = [x if x["tx"] != a["tx"] else a for x in p["anchors"]]
            (ledger.RUNS_DIR / run_id / "proof.json").write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
        return a

    def rerun(self, run_id: str) -> dict:
        """Re-derive a report from nothing but its on-chain record (area + event time) and open data."""
        from .pipeline import run, run_id as make_id
        r = self.registry.functions.report(ledger.report_key(run_id)).call()
        bbox = [v / 1e5 for v in r[2]]
        event = datetime.fromtimestamp(r[3], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if make_id(bbox, event) != run_id:
            raise RuntimeError("on-chain area/time do not map back to this run id")
        return run(bbox, event)

    def confirm(self, run_id: str, rerun: bool = False) -> dict:
        """Run by a *different* party on its own machine after re-running the pipeline itself."""
        st = self.status(run_id)
        if not st["published"]:
            raise RuntimeError("not published yet")
        if rerun:
            self.rerun(run_id)
        p = ledger.build(run_id)
        if st["claims_root"] != p["claims_root"]:
            rc = self._send(self.registry.functions.dispute(b32(p["key"]), b32(p["claims_root"]),
                                                            "independent re-run produced different claims"))
            return self._record(run_id, p, "disputed", rc)
        rc = self._send(self.registry.functions.confirm(b32(p["key"]), b32(p["claims_root"])))
        return self._record(run_id, p, "confirmed", rc)

    # -- relief -----------------------------------------------------------------------------------------
    def open_fund(self, bbox, start_utc, end_utc, per_person_wei, cap_wei, partner, deposit_wei=0, min_status=2):
        fid = self.relief.functions.fundCount().call()
        rc = self._send(self.relief.functions.open([ledger.e5(v) for v in bbox], _ts(start_utc), _ts(end_utc),
                                                   min_status, per_person_wei, cap_wei, partner), value=deposit_wei)
        return {"fund_id": fid, "tx": rc.transactionHash.to_0x_hex(), "tx_url": self.tx_url(rc.transactionHash.to_0x_hex())}

    def fund(self, fund_id: int) -> dict:
        f = self.relief.functions.funds(fund_id).call()
        keys = ["steward", "window_start", "window_end", "min_status", "wei_per_person", "cap_per_settlement",
                "default_partner", "balance", "paid"]   # public getter skips the fixed array (bbox)
        return dict(zip(keys, f))

    def claim(self, run_id: str, fund_id: int) -> list[dict]:
        p = ledger.load(run_id) or ledger.build(run_id)
        f = self.relief.functions
        paid = []
        for s in p["settlements"]:
            sid = b32(s["settlement_id"])
            if s["status"] == 0 or f.paidOut(fund_id, sid).call():
                continue
            args = (fund_id, b32(p["key"]), sid, s["lon_e5"], s["lat_e5"], s["status"], s["buildings"],
                    s["people_stranded"], [b32(x) for x in s["proof"]])
            try:
                f.claim(*args).call({"from": self.acct.address})     # dry run: skip what the contract refuses
            except Exception as e:
                paid.append({"settlement": s["name"], "skipped": str(e).split(":")[-1].strip()[:80]})
                continue
            rc = self._send(f.claim(*args))
            ev = self.relief.events.Paid().process_receipt(rc)[0]["args"]
            paid.append({"settlement": s["name"], "people_stranded": s["people_stranded"], "amount_wei": ev["amount"],
                         "partner": ev["partner"], "tx": rc.transactionHash.to_0x_hex(),
                         "tx_url": self.tx_url(rc.transactionHash.to_0x_hex())})
        return paid


_CACHE: dict = {}


def onchain_summary(run_id: str, ttl_s: float = 15) -> dict | None:
    """Best-effort read for the dashboard / copilot. None when no chain is configured or reachable."""
    if not any(DEPLOYMENTS.glob("*.json")):
        return None
    hit = _CACHE.get(run_id)
    if hit and time.time() - hit[0] < ttl_s:
        return hit[1]
    _CACHE[run_id] = (time.time(), _summary(run_id))
    return _CACHE[run_id][1]


def _summary(run_id):
    try:
        lg = Ledger(key="")
        if lg.registry is None:
            return None
        st = lg.status(run_id)
        return st | {"network": lg.network["name"], "chain_id": lg.chain_id, "registry": lg.registry.address,
                     "registry_url": lg.address_url(lg.registry.address),
                     "relief": lg.relief.address if lg.relief else None,
                     "rpc": os.getenv("WATERGUARD_CHAIN_RPC", DEFAULT_RPC)}
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["compile", "wallet", "deploy", "publish", "confirm", "status", "add-verifier",
                                    "open-fund", "claim", "resolve"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--quorum", type=int, default=2)
    ap.add_argument("--window", type=int, default=3600)
    ap.add_argument("--bbox", type=float, nargs=4)
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--per-person-wei", type=int)
    ap.add_argument("--cap-wei", type=int)
    ap.add_argument("--partner")
    ap.add_argument("--deposit-wei", type=int, default=0)
    ap.add_argument("--min-status", type=int, default=2, help="1 = pay partly cut settlements too, 2 = cut off only")
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--skip-review", action="store_true", help="publish although inspected cells await an analyst")
    ap.add_argument("--as-verifier", action="store_true")
    a = ap.parse_args()

    if a.cmd == "compile":
        print("compiled:", ", ".join(compile_contracts()))
        return
    if a.cmd == "wallet":
        from eth_account import Account
        acct = Account.create()
        print(f"address: {acct.address}\nadd to .env:  WATERGUARD_LEDGER_KEY={acct.key.hex()}")
        return
    lg = Ledger(key=os.getenv("WATERGUARD_VERIFIER_KEY") if a.as_verifier else None)
    out = {
        "deploy": lambda: lg.deploy(a.quorum, a.window),
        "publish": lambda: lg.publish(a.args[0], a.skip_review),
        "confirm": lambda: lg.confirm(a.args[0], a.rerun),
        "status": lambda: lg.status(a.args[0]),
        "add-verifier": lambda: {"tx": lg.add_verifier(a.args[0]).transactionHash.to_0x_hex()},
        "open-fund": lambda: lg.open_fund(a.bbox, a.start, a.end, a.per_person_wei, a.cap_wei, a.partner,
                                          a.deposit_wei, a.min_status),
        "claim": lambda: lg.claim(a.args[0], int(a.args[1])),
        "resolve": lambda: lg.resolve(a.args[0], a.args[1] == "upheld"),
    }[a.cmd]()
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
