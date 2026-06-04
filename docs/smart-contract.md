# Smart Contract Design

The Ethereum smart contract is the security core of the BB-DD-FTC framework.
It embeds the detection, identification, and reconfiguration logic in immutable bytecode.
Once deployed to the private PoA network, threshold values cannot be altered — this
directly addresses the threshold manipulation vulnerability in conventional DD-IDS.

---

## Three Functions (Algorithm 3 from Thesis)

### DETECTION(T²_k, Q_k)

Compares incoming statistics against globally defined thresholds:

```solidity
function DETECTION(int256 T2_k, int256 Q_k) internal returns (int256 I_k) {
    if (T2_k > J_T2 && Q_k > J_Q) {
        return 1;   // Attack detected
    }
    return 0;
}
```

`J_T2` and `J_Q` are set at contract deployment from offline training and are **immutable**.

---

### IDENT(y_k, ŷ_k for R_L, R_P, R_T)

Computes residuals and checks against per-sensor thresholds:

```solidity
function IDENT(
    int256[3] memory y_k,
    int256[3] memory y_hat_k
) internal returns (bool[3] memory Q_flags) {
    for (uint i = 0; i < 3; i++) {
        int256 residual = y_k[i] - y_hat_k[i];
        if (abs(residual) > epsilon[i]) {
            Q_flags[i] = true;   // Sensor i compromised
        }
    }
    return Q_flags;
}
```

---

### RECON(I_k, Q_flags, residuals, y_k)

Computes true sensor measurements:

```solidity
function RECON(
    int256 I_k,
    bool[3] memory Q_flags,
    int256[3] memory residuals,
    int256[3] memory y_k
) internal returns (int256[3] memory y_true) {
    for (uint i = 0; i < 3; i++) {
        if (I_k == 1 && Q_flags[i]) {
            // Compromised: use observer prediction (y - residual * flag)
            y_true[i] = y_k[i] - residuals[i];
        } else {
            // Intact: use measured value
            y_true[i] = y_k[i];
        }
    }
    return y_true;
}
```

---

## Deployment Configuration

- **Network:** Private Ethereum testnet (Clique PoA)
- **Language:** Solidity
- **Compiler:** Remix / Hardhat
- **Key limitation:** Smart contracts cannot natively handle floating-point values.
  All values are scaled by `10^6` before submission and rescaled on retrieval.
  (See `blockchain_api.py` for the conversion logic.)

---

## Security Properties Provided by Smart Contract

| Property | How achieved |
|----------|-------------|
| Immutable thresholds | J_T², J_Q, ε_i set at deployment, no setter functions |
| Data integrity | keccak256 encrypted + digitally signed transactions |
| Non-repudiation | Each transaction carries sender's digital signature (SK_i) |
| Replay resistance | Unique transaction ID + timestamp per sample instant |
| Auditability | All transactions permanently recorded on blockchain ledger |
| Spoof resistance | Private permissioned network — identities defined in genesis block |
