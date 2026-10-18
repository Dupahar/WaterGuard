// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Proofs over WaterGuard's Merkle trees. Leaves and inner nodes use SHA-256 so that the same tree can be
/// rebuilt in any browser (WebCrypto) without a crypto library. Inner nodes hash the sorted pair.
library ShaMerkle {
    function verify(bytes32[] calldata proof, bytes32 root, bytes32 leaf) internal pure returns (bool) {
        bytes32 h = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            h = h < p ? sha256(abi.encodePacked(h, p)) : sha256(abi.encodePacked(p, h));
        }
        return h == root;
    }
}

/// Public record of flood-impact reports.
///
/// A report is identified by `key` = sha256(run_id). Its publisher anchors two roots:
///   reportRoot: Merkle root over the hashes of every output file (facts, impact raster, layers),
///               so any copy of the report can be checked byte for byte;
///   claimsRoot: Merkle root over one leaf per settlement (position, road status, people stranded),
///               which is what relief payouts are proven against.
/// Independent verifiers re-run the open pipeline on the same open satellite data and confirm only if
/// they get the same claimsRoot. A report becomes final after `quorum` confirmations and a challenge
/// window with no dispute.
contract ReportRegistry {
    struct Report {
        bytes32 reportRoot;
        bytes32 claimsRoot;
        int32[4] bboxE5;        // west, south, east, north in 1e-5 degrees
        uint64 eventTime;       // unix seconds
        uint64 publishedAt;
        bytes20 codeVersion;    // git commit of the pipeline that produced it
        address publisher;
        uint16 confirmations;   // publisher counts as the first
        bool disputed;
        string uri;             // where the files can be fetched
    }

    address public owner;
    uint16 public quorum;
    uint64 public challengeWindow;
    mapping(address => bool) public isVerifier;
    mapping(bytes32 => Report) private reports;
    mapping(bytes32 => mapping(address => bool)) public confirmedBy;
    bytes32[] public keys;

    event VerifierSet(address indexed verifier, bool allowed);
    event Published(bytes32 indexed key, bytes32 reportRoot, bytes32 claimsRoot, address indexed publisher, string uri);
    event Confirmed(bytes32 indexed key, address indexed verifier, uint16 confirmations);
    event Disputed(bytes32 indexed key, address indexed by, bytes32 theirClaimsRoot, string reason);

    modifier onlyOwner() { require(msg.sender == owner, "not owner"); _; }
    modifier onlyVerifier() { require(isVerifier[msg.sender], "not a verifier"); _; }

    constructor(uint16 quorum_, uint64 challengeWindow_) {
        require(quorum_ >= 1, "quorum");
        owner = msg.sender;
        quorum = quorum_;
        challengeWindow = challengeWindow_;
        isVerifier[msg.sender] = true;
        emit VerifierSet(msg.sender, true);
    }

    function setVerifier(address v, bool allowed) external onlyOwner {
        isVerifier[v] = allowed;
        emit VerifierSet(v, allowed);
    }

    function setRules(uint16 quorum_, uint64 challengeWindow_) external onlyOwner {
        require(quorum_ >= 1, "quorum");
        quorum = quorum_;
        challengeWindow = challengeWindow_;
    }

    function publish(bytes32 key, bytes32 reportRoot, bytes32 claimsRoot, int32[4] calldata bboxE5,
                     uint64 eventTime, bytes20 codeVersion, string calldata uri) external onlyVerifier {
        require(reports[key].publishedAt == 0, "already published");
        require(bboxE5[0] < bboxE5[2] && bboxE5[1] < bboxE5[3], "bbox");
        Report storage r = reports[key];
        r.reportRoot = reportRoot;
        r.claimsRoot = claimsRoot;
        r.bboxE5 = bboxE5;
        r.eventTime = eventTime;
        r.publishedAt = uint64(block.timestamp);
        r.codeVersion = codeVersion;
        r.publisher = msg.sender;
        r.confirmations = 1;
        r.uri = uri;
        confirmedBy[key][msg.sender] = true;
        keys.push(key);
        emit Published(key, reportRoot, claimsRoot, msg.sender, uri);
    }

    /// An independent re-run agrees: same settlements, same statuses, same counts.
    function confirm(bytes32 key, bytes32 claimsRoot) external onlyVerifier {
        Report storage r = reports[key];
        require(r.publishedAt != 0, "unknown report");
        require(!confirmedBy[key][msg.sender], "already confirmed");
        require(claimsRoot == r.claimsRoot, "claims differ: dispute instead");
        confirmedBy[key][msg.sender] = true;
        r.confirmations += 1;
        emit Confirmed(key, msg.sender, r.confirmations);
    }

    /// An independent re-run disagrees. Blocks finality (and so every payout) until the owner resolves it.
    function dispute(bytes32 key, bytes32 theirClaimsRoot, string calldata reason) external onlyVerifier {
        Report storage r = reports[key];
        require(r.publishedAt != 0, "unknown report");
        r.disputed = true;
        emit Disputed(key, msg.sender, theirClaimsRoot, reason);
    }

    function resolveDispute(bytes32 key, bool upheld) external onlyOwner {
        Report storage r = reports[key];
        require(r.disputed, "not disputed");
        if (upheld) {
            r.claimsRoot = bytes32(0);   // the report can never back a payout
        } else {
            r.disputed = false;
        }
    }

    function isFinal(bytes32 key) public view returns (bool) {
        Report storage r = reports[key];
        return r.publishedAt != 0 && !r.disputed && r.claimsRoot != bytes32(0)
            && r.confirmations >= quorum && block.timestamp >= r.publishedAt + challengeWindow;
    }

    /// Static-only view, easy to decode from a browser with a raw eth_call.
    function status(bytes32 key) external view returns (bytes32 reportRoot, bytes32 claimsRoot, uint64 eventTime,
        uint64 publishedAt, uint16 confirmations, bool disputed, bool final_, bytes20 codeVersion) {
        Report storage r = reports[key];
        return (r.reportRoot, r.claimsRoot, r.eventTime, r.publishedAt, r.confirmations, r.disputed,
                isFinal(key), r.codeVersion);
    }

    function report(bytes32 key) external view returns (Report memory) {
        return reports[key];
    }

    function count() external view returns (uint256) {
        return keys.length;
    }

    function verifySettlement(bytes32 key, bytes32 leaf, bytes32[] calldata proof) external view returns (bool) {
        bytes32 root = reports[key].claimsRoot;
        return root != bytes32(0) && ShaMerkle.verify(proof, root, leaf);
    }
}

/// Pre-arranged relief money that moves on evidence instead of paperwork.
///
/// A donor (government, NGO, insurer) opens a fund for an area and a time window, says how much each
/// stranded person is worth in emergency supplies, caps each settlement, and names the relief partner
/// that receives the money (a district office or NGO, optionally one per settlement). When a final
/// report shows a settlement inside the area cut off, anyone can submit its Merkle proof and the
/// payment goes straight to the partner. Each settlement is paid at most once per fund.
contract ReliefFund {
    struct Fund {
        address steward;
        int32[4] bboxE5;
        uint64 windowStart;
        uint64 windowEnd;
        uint8 minStatus;            // 1 = partly cut, 2 = cut off
        uint128 weiPerPerson;
        uint128 capPerSettlement;
        address defaultPartner;
        uint256 balance;
        uint256 paid;
    }

    ReportRegistry public immutable registry;
    Fund[] public funds;
    mapping(uint256 => mapping(bytes32 => address)) public partnerOf;
    mapping(uint256 => mapping(bytes32 => bool)) public paidOut;

    event FundOpened(uint256 indexed fundId, address indexed steward, uint128 weiPerPerson, uint128 capPerSettlement);
    event Donated(uint256 indexed fundId, address indexed from, uint256 amount);
    event PartnerSet(uint256 indexed fundId, bytes32 indexed settlementId, address partner);
    event Paid(uint256 indexed fundId, bytes32 indexed reportKey, bytes32 indexed settlementId, address partner,
               uint256 amount, uint32 peopleStranded);
    event Closed(uint256 indexed fundId, uint256 refunded);

    constructor(ReportRegistry registry_) {
        registry = registry_;
    }

    function open(int32[4] calldata bboxE5, uint64 windowStart, uint64 windowEnd, uint8 minStatus,
                  uint128 weiPerPerson, uint128 capPerSettlement, address defaultPartner)
                  external payable returns (uint256 fundId) {
        require(bboxE5[0] < bboxE5[2] && bboxE5[1] < bboxE5[3], "bbox");
        require(windowStart < windowEnd, "window");
        require(minStatus == 1 || minStatus == 2, "minStatus");
        require(defaultPartner != address(0), "partner");
        fundId = funds.length;
        funds.push(Fund(msg.sender, bboxE5, windowStart, windowEnd, minStatus, weiPerPerson, capPerSettlement,
                        defaultPartner, msg.value, 0));
        emit FundOpened(fundId, msg.sender, weiPerPerson, capPerSettlement);
        if (msg.value > 0) emit Donated(fundId, msg.sender, msg.value);
    }

    function donate(uint256 fundId) external payable {
        require(fundId < funds.length, "fund");
        funds[fundId].balance += msg.value;
        emit Donated(fundId, msg.sender, msg.value);
    }

    function setPartner(uint256 fundId, bytes32 settlementId, address partner) external {
        require(msg.sender == funds[fundId].steward, "not steward");
        partnerOf[fundId][settlementId] = partner;
        emit PartnerSet(fundId, settlementId, partner);
    }

    /// The leaf WaterGuard commits to for each settlement (double-hashed against second-preimage tricks).
    function leafOf(bytes32 reportKey, bytes32 settlementId, int32 lonE5, int32 latE5, uint8 status,
                    uint32 buildings, uint32 peopleStranded) public pure returns (bytes32) {
        return sha256(abi.encodePacked(sha256(abi.encode(reportKey, settlementId, lonE5, latE5, status,
                                                           buildings, peopleStranded))));
    }

    function quote(uint256 fundId, uint32 peopleStranded) public view returns (uint256) {
        Fund storage f = funds[fundId];
        uint256 amount = uint256(f.weiPerPerson) * peopleStranded;
        if (amount > f.capPerSettlement) amount = f.capPerSettlement;
        if (amount > f.balance) amount = f.balance;
        return amount;
    }

    function claim(uint256 fundId, bytes32 reportKey, bytes32 settlementId, int32 lonE5, int32 latE5,
                   uint8 status, uint32 buildings, uint32 peopleStranded, bytes32[] calldata proof) external {
        Fund storage f = funds[fundId];
        require(!paidOut[fundId][settlementId], "already paid");
        require(registry.isFinal(reportKey), "report not final");
        require(status >= f.minStatus, "not cut off");
        require(lonE5 >= f.bboxE5[0] && lonE5 <= f.bboxE5[2] && latE5 >= f.bboxE5[1] && latE5 <= f.bboxE5[3],
                "outside fund area");
        (, , uint64 eventTime, , , , , ) = registry.status(reportKey);
        require(eventTime >= f.windowStart && eventTime <= f.windowEnd, "event outside window");
        bytes32 leaf = leafOf(reportKey, settlementId, lonE5, latE5, status, buildings, peopleStranded);
        require(registry.verifySettlement(reportKey, leaf, proof), "bad proof");

        uint256 amount = quote(fundId, peopleStranded);
        require(amount > 0, "nothing to pay");
        address partner = partnerOf[fundId][settlementId];
        if (partner == address(0)) partner = f.defaultPartner;
        paidOut[fundId][settlementId] = true;
        f.balance -= amount;
        f.paid += amount;
        (bool ok, ) = partner.call{value: amount}("");
        require(ok, "transfer failed");
        emit Paid(fundId, reportKey, settlementId, partner, amount, peopleStranded);
    }

    /// Reports need time to be confirmed, so claims stay open this long after the event window.
    uint64 public constant CLAIM_PERIOD = 30 days;

    /// After the claim period the steward can take back what was not needed.
    function close(uint256 fundId) external {
        Fund storage f = funds[fundId];
        require(msg.sender == f.steward, "not steward");
        require(block.timestamp > f.windowEnd + CLAIM_PERIOD, "claims still open");
        uint256 left = f.balance;
        f.balance = 0;
        (bool ok, ) = f.steward.call{value: left}("");
        require(ok, "transfer failed");
        emit Closed(fundId, left);
    }

    function fundCount() external view returns (uint256) {
        return funds.length;
    }
}
