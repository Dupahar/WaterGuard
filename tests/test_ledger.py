"""Ledger end to end on an in-memory EVM: anchor, confirm, dispute, pay relief.

    python -m pytest tests/test_ledger.py -q
"""
import json

import pytest

web3 = pytest.importorskip("web3")
pytest.importorskip("eth_tester")

from eth_account import Account  # noqa: E402
from web3 import EthereumTesterProvider, Web3  # noqa: E402

from waterguard import chain, ledger  # noqa: E402

RID = "testrun001"
BBOX = [85.30, 28.20, 85.40, 28.30]
ETH = 10**18


def _settlement(name, lon, lat, status, people, share):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "kind": "village", "buildings": people // 4, "people_est": people,
                           "vehicle_status": status, "vehicle_stranded_share": share}}


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "RUNS_DIR", tmp_path)
    d = tmp_path / RID
    d.mkdir()
    (d / "facts.json").write_text(json.dumps({"area": {"bbox": BBOX}, "event_time_utc": "2026-08-25T22:00:00Z"}))
    (d / "impact.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    feats = [_settlement("Timure", 85.36667, 28.25285, "cut off", 905, 1.0),
             _settlement("Rasuwa Gadhi", 85.37778, 28.27777, "cut off", 415, 1.0),
             _settlement("Syafru", 85.32, 28.22, "partly cut", 400, 0.5),
             _settlement("Dhunche", 85.31, 28.21, "ok", 2000, 0.0),
             _settlement("Far away", 86.5, 28.25, "cut off", 100, 1.0)]       # outside the fund area
    (d / "settlements.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return d


@pytest.fixture
def net():
    w3 = Web3(EthereumTesterProvider())
    accts = [Account.create() for _ in range(4)]          # operator, verifier, donor, partner
    for a in accts:
        w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": a.address, "value": 100 * ETH})
    op = chain.Ledger(w3, accts[0].key.hex(), deployment={})
    op.deploy(quorum=2, window_s=3600, save=False)
    as_ = lambda a: chain.Ledger(w3, a.key.hex(), deployment=op.dep)
    return {"w3": w3, "op": op, "verifier": as_(accts[1]), "donor": as_(accts[2]), "partner": accts[3],
            "accts": accts, "as": as_}


def _travel(w3, seconds):
    t = w3.provider.ethereum_tester
    t.time_travel(w3.eth.get_block("latest")["timestamp"] + seconds)
    t.mine_blocks(1)


def test_merkle_proofs_roundtrip():
    for n in range(1, 12):
        leaves = [ledger.sha(bytes([i])) for i in range(n)]
        root, proofs = ledger.merkle(leaves)
        assert all(ledger.verify(p, root, lf) for p, lf in zip(proofs, leaves))
        assert not ledger.verify(proofs[0], root, ledger.sha(b"forged"))


def test_leaf_matches_contract(run_dir, net):
    p = ledger.build(RID)
    s = p["settlements"][0]
    onchain = net["op"].relief.functions.leafOf(
        chain.b32(p["key"]), chain.b32(s["settlement_id"]), s["lon_e5"], s["lat_e5"], s["status"],
        s["buildings"], s["people_stranded"]).call()
    assert "0x" + onchain.hex() == s["leaf"]


def test_tampering_is_detected(run_dir):
    ledger.build(RID)
    assert ledger.check(RID)["report_root_matches"]
    (run_dir / "impact.geojson").write_text('{"type":"FeatureCollection","features":[{"edited":1}]}')
    c = ledger.check(RID)
    assert not c["report_root_matches"] and c["changed_files"] == ["impact.geojson"]
    assert c["claims_root_matches"]          # settlement claims were not touched


def test_publish_confirm_and_relief(run_dir, net):
    op, ver, donor, w3 = net["op"], net["verifier"], net["donor"], net["w3"]
    op.add_verifier(ver.acct.address)
    op.publish(RID)
    assert op.status(RID)["published"] and not op.status(RID)["final"]

    fund = donor.open_fund(BBOX, "2026-08-01", "2026-09-30", per_person_wei=10**15, cap_wei=ETH // 2,
                           partner=net["partner"].address, deposit_wei=5 * ETH)["fund_id"]
    assert all("skipped" in r for r in donor.claim(RID, fund))          # not final: nothing moves

    ver.confirm(RID)
    assert op.status(RID)["confirmations"] == 2
    assert all("skipped" in r for r in donor.claim(RID, fund))          # quorum met, challenge window still open
    _travel(w3, 3601)
    assert op.status(RID)["final"]

    before = w3.eth.get_balance(net["partner"].address)
    out = {r["settlement"]: r for r in donor.claim(RID, fund)}
    assert out["Timure"]["amount_wei"] == ETH // 2                      # 905 people x 0.001 capped at 0.5
    assert out["Rasuwa Gadhi"]["amount_wei"] == 415 * 10**15
    assert "skipped" in out["Syafru"]                                   # partly cut, fund pays cut-off only
    assert "outside fund area" in out["Far away"]["skipped"]
    assert "Dhunche" not in out                                         # status ok: never claimed
    assert w3.eth.get_balance(net["partner"].address) - before == ETH // 2 + 415 * 10**15
    assert donor.claim(RID, fund) == [{"settlement": "Far away", "skipped": out["Far away"]["skipped"]},
                                      {"settlement": "Syafru", "skipped": out["Syafru"]["skipped"]}] or \
        all("skipped" in r for r in donor.claim(RID, fund))             # paid once only


def test_forged_claim_rejected(run_dir, net):
    op, ver, w3 = net["op"], net["verifier"], net["w3"]
    op.add_verifier(ver.acct.address)
    p = op.publish(RID) and ledger.load(RID)
    ver.confirm(RID)
    _travel(w3, 3601)
    fund = op.open_fund(BBOX, "2026-08-01", "2026-09-30", 10**15, ETH, net["partner"].address, 5 * ETH)["fund_id"]
    s = next(x for x in p["settlements"] if x["name"] == "Timure")
    f = op.relief.functions
    with pytest.raises(Exception, match="bad proof"):     # inflate the head count
        f.claim(fund, chain.b32(p["key"]), chain.b32(s["settlement_id"]), s["lon_e5"], s["lat_e5"], 2,
                s["buildings"], 50000, [chain.b32(x) for x in s["proof"]]).call({"from": op.acct.address})


def test_disagreeing_verifier_blocks_payout(run_dir, net):
    op, ver, w3 = net["op"], net["verifier"], net["w3"]
    op.add_verifier(ver.acct.address)
    op.publish(RID)
    # the verifier's own re-run finds Timure still reachable
    gj = json.loads((run_dir / "settlements.geojson").read_text())
    gj["features"][0]["properties"].update(vehicle_status="ok", vehicle_stranded_share=0.0)
    (run_dir / "settlements.geojson").write_text(json.dumps(gj))
    assert ver.confirm(RID)["kind"] == "disputed"
    _travel(w3, 3601)
    st = op.status(RID)
    assert st["disputed"] and not st["final"]


def test_only_verifiers_publish(run_dir, net):
    stranger = net["as"](net["accts"][2])
    with pytest.raises(Exception):
        stranger.publish(RID)
