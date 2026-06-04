"""
Blockchain Interface — Python API for Ethereum Smart Contract
BB-DD-FTC Framework

Handles communication between edge server (MATLAB/Python) and the
private Ethereum blockchain (Clique PoA) using web3py via JSON-RPC.

Reference:
    Masood et al., "A Blockchain-Based Data-Driven Fault-Tolerant Control System
    for Smart Factories in Industry 4.0", Computer Communications, vol. 204, 2023.
"""

from web3 import Web3
import json


# ── Blockchain connection parameters ─────────────────────────────────────────
# Replace with your private testnet configuration
RPC_URL       = "http://127.0.0.1:8545"   # geth RPC port
CHAIN_ID      = 1337                        # Private testnet chain ID
GAS_LIMIT     = 3_000_000
CONTRACT_ADDR = "0x..."                     # Deployed smart contract address
CONTRACT_ABI  = []                          # Load from compiled contract JSON


class BlockchainInterface:
    """
    Python API for the BB-DD-FTC Ethereum smart contract.

    Responsibilities:
    - Convert floating-point data vectors to integers (smart contract limitation)
    - Encrypt data vectors via keccak256 and create signed transactions
    - Submit data vectors to the blockchain at each sampling instant
    - Retrieve true (reconfigured) sensor measurements from the smart contract
    """

    SCALE_FACTOR = 1_000_000   # Multiply floats by this before sending (6 decimal places)

    def __init__(self, rpc_url: str, contract_address: str, contract_abi: list,
                 private_key: str, chain_id: int = 1337):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to Ethereum node at {rpc_url}")

        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=contract_abi,
        )
        self.private_key = private_key
        self.account = self.w3.eth.account.from_key(private_key)
        self.chain_id = chain_id

    # ── Data type conversion ──────────────────────────────────────────────────

    def floats_to_ints(self, values: list[float]) -> list[int]:
        """Scale floats to integers for smart contract compatibility."""
        return [int(v * self.SCALE_FACTOR) for v in values]

    def ints_to_floats(self, values: list[int]) -> list[float]:
        """Reverse scaling after receiving from smart contract."""
        return [v / self.SCALE_FACTOR for v in values]

    # ── Transaction submission ────────────────────────────────────────────────

    def submit_data_vector(
        self,
        T2_k: float,
        Q_k: float,
        u_k: list[float],
        y_k: list[float],
        y_hat_k: list[float],
    ) -> str:
        """
        Submit measurement data vector to the smart contract.

        The data vector contains:
            [T²_k, Q_k, u1_k, u2_k, u3_k, y_RL, y_RP, y_RT, ŷ_RL, ŷ_RP, ŷ_RT]

        Returns transaction hash.
        """
        # Convert all floats to integers
        T2_int = int(T2_k * self.SCALE_FACTOR)
        Q_int  = int(Q_k  * self.SCALE_FACTOR)
        u_ints = self.floats_to_ints(u_k)
        y_ints = self.floats_to_ints(y_k)
        y_hat_ints = self.floats_to_ints(y_hat_k)

        # Build transaction
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        txn = self.contract.functions.submitDataVector(
            T2_int, Q_int, u_ints, y_ints, y_hat_ints
        ).build_transaction({
            "chainId": self.chain_id,
            "gas": GAS_LIMIT,
            "gasPrice": self.w3.to_wei("1", "gwei"),
            "nonce": nonce,
        })

        # Sign and send
        signed = self.w3.eth.account.sign_transaction(txn, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

        return receipt.transactionHash.hex()

    # ── Retrieve reconfigured measurements ────────────────────────────────────

    def get_true_measurements(self) -> dict:
        """
        Retrieve reconfigured sensor measurements from the smart contract.

        The smart contract has:
        1. Detected an attack (or not)
        2. Identified the compromised sensor
        3. Computed the reconfigured measurement

        Returns dict with:
            I         : int        — detection flag
            Q_flags   : list[int]  — per-sensor identification flags
            y_true    : list[float]— reconfigured sensor values
        """
        result = self.contract.functions.getTrueMeasurements().call()

        return {
            "I":       result[0],
            "Q_flags": result[1],
            "y_true":  self.ints_to_floats(result[2]),
        }


# ── Smart contract ABI template ───────────────────────────────────────────────
# Load your compiled contract ABI from Remix or Hardhat:
#
# with open("contracts/BBDDFTC.json") as f:
#     contract_data = json.load(f)
#     CONTRACT_ABI = contract_data["abi"]
#
# Example contract functions (see docs/smart-contract.md for full Solidity source):
#   submitDataVector(T2, Q, u[], y[], yhat[]) → txHash
#   getTrueMeasurements() → (I, Q_flags[], y_true[])
#   getThresholds() → (JT2, JQ, epsilon[])   # Read-only — immutable after deploy
