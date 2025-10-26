# {repo_name}

This repository contains a Python-based simulation of a cross-chain bridge event listener. It is designed as a robust, architecturally-sound component that demonstrates how to monitor events on a source blockchain and trigger corresponding actions on a destination blockchain.

## Concept

Cross-chain bridges are essential for blockchain interoperability, allowing assets and data to move between different networks. A critical component of any bridge is the **oracle** or **listener** network. These listeners monitor a `Bridge` smart contract on one chain (the "source chain") for specific events, such as `TokensLocked`.

When a `TokensLocked` event is detected, it signifies that a user has deposited assets into the bridge, intending to receive an equivalent "wrapped" asset on another chain (the "destination chain"). The listener's job is to:

1.  Securely verify this event.
2.  Wait for a sufficient number of block confirmations to mitigate the risk of a chain reorganization (reorg).
3.  Construct, sign, and broadcast a transaction on the destination chain to a corresponding `Bridge` contract, typically calling a function like `mintTokens` to issue the wrapped assets to the user's recipient address.

This script simulates this entire workflow in a modular and extensible way.

## Code Architecture

The script is designed with a clear separation of concerns, using several classes to handle distinct responsibilities:

-   `ConfigManager`: Responsible for loading and validating all necessary configuration parameters (RPC URLs, contract addresses, private keys) from a `.env` file. This keeps sensitive data and settings separate from the core logic.

-   `BlockchainConnector`: A reusable utility class that manages the connection to a blockchain node via an RPC endpoint using the `web3.py` library. It handles connection setup, verification, and reconnection logic.

-   `EventScanner`: The core of the listening mechanism. It takes a blockchain connection and contract details, and its primary method `scan_blocks` polls a range of blocks for a specific event (e.g., `TokensLocked`). It is designed to be resilient to RPC errors.

-   `TransactionProcessor`: This class acts on the events detected by the `EventScanner`. It is responsible for constructing, signing, and (in this simulation) logging the details of the transaction that would be sent to the destination chain. It encapsulates the logic for interacting with the destination bridge contract.

-   `BridgeOrchestrator`: The main conductor that ties all the other components together. It initializes the system, manages the main application loop, maintains state (like the last block scanned), and coordinates the flow of information from the `EventScanner` to the `TransactionProcessor`.

The main execution flow is straightforward:

```python
# script.py
if __name__ == "__main__":
    config = ConfigManager()
    orchestrator = BridgeOrchestrator(config)
    orchestrator.run()
```

```
+-----------------------+
|   BridgeOrchestrator  | (Main Loop, State Management)
+-----------------------+
        |         ^
        |         | (Events)
        v         |
+-----------------------+     +------------------------+
|     EventScanner      |---->|  TransactionProcessor  |
| (Scans Source Chain)  |     | (Acts on Dest. Chain)  |
+-----------------------+     +------------------------+
        |                               |
        v                               v
+-----------------------+     +------------------------+
| BlockchainConnector   |     |  BlockchainConnector   |
| (Source Chain RPC)    |     | (Dest. Chain RPC)      |
+-----------------------+     +------------------------+

```

## How it Works

The script follows a continuous, stateful process:

1.  **Initialization**: The `BridgeOrchestrator` is created. It instantiates the `ConfigManager` to load settings, sets up `BlockchainConnector` instances for both source and destination chains, and initializes the `EventScanner` and `TransactionProcessor`.

2.  **State Management**: The orchestrator loads its state from a local file (`scanner_state.json`). This file stores the last successfully scanned block number. This ensures that if the script is stopped and restarted, it can resume where it left off without missing events or reprocessing old ones.

3.  **The Main Loop**: The orchestrator enters an infinite loop to continuously monitor the source chain.

4.  **Event Scanning**: In each iteration, it determines the range of blocks to scan. It starts from the `last_processed_block + 1` up to the latest block on the chain, minus a configurable number of `BLOCK_CONFIRMATIONS_REQUIRED`. This delay ensures that any detected event is on a finalized block, protecting against reorgs. The scan is performed in batches to avoid overwhelming the RPC node.

5.  **Confirmation & Processing**: If the `EventScanner` finds any `TokensLocked` events, the orchestrator iterates through them. For each event, it confirms it has not been processed before (by checking against a list of processed transaction hashes) and then passes it to the `TransactionProcessor`.

6.  **Transaction Simulation**: The `TransactionProcessor` takes the event data (recipient, amount, etc.), builds a `mintTokens` transaction for the destination chain, signs it with the listener's private key, and logs the details. **In this simulation, the transaction is NOT broadcast to the network.**

7.  **State Update**: After scanning a block range, the orchestrator updates its `last_processed_block` state and saves it back to the `scanner_state.json` file. The loop then pauses for a configured interval before starting the next cycle.

## Getting Started

### 1. Prerequisites

*   Python 3.8+
*   Git

### 2. Clone the Repository

```bash
git clone <your-repo-url> {repo_name}
cd {repo_name}
```

### 3. Environment Setup

The script uses a `.env` file for configuration. Create one in the root directory by copying the example file:

```bash
cp .env.example .env
```

Now, edit the `.env` file with your specific details. You will need RPC endpoint URLs for two different chains (e.g., from Infura, Alchemy, or a local node).

```dotenv
# .env file

# RPC endpoint for the source chain (e.g., Ethereum Sepolia Testnet)
SOURCE_CHAIN_RPC_URL="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"

# RPC endpoint for the destination chain (e.g., Polygon Mumbai Testnet)
DESTINATION_CHAIN_RPC_URL="https://polygon-mumbai.g.alchemy.com/v2/YOUR_ALCHEMY_API_KEY"

# Address of the bridge contract on the source chain
SOURCE_BRIDGE_CONTRACT_ADDRESS="0x..."

# Address of the bridge contract on the destination chain
DESTINATION_BRIDGE_CONTRACT_ADDRESS="0x..."

# Private key of the account that will submit transactions on the destination chain
# IMPORTANT: Use a key for a test account with no real value.
LISTENER_PRIVATE_KEY="0x..."

# Number of blocks to wait for before considering an event confirmed
BLOCK_CONFIRMATIONS_REQUIRED=12

# Number of blocks to scan in a single RPC request
SCAN_BATCH_SIZE=500

# Seconds to wait between polling for new blocks
POLL_INTERVAL_SECONDS=15
```

### 4. Install Dependencies

It's recommended to use a virtual environment to manage project dependencies.

```bash
# Create a virtual environment
python3 -m venv venv

# Activate it (on macOS/Linux)
source venv/bin/activate
# Or on Windows
# venv\Scripts\activate

# Install the required libraries
pip install -r requirements.txt
```

### 5. Run the Script

Execute the main script from your terminal:

```bash
python script.py
```

**Example Output:**

```
2023-10-27 10:30:00,123 - INFO - [config_manager:31] - Configuration loaded and validated successfully.
2023-10-27 10:30:01,456 - INFO - [blockchain_connector:39] - Successfully connected to RPC endpoint: https://sepolia.infura.io/v3/... (Chain ID: 11155111)
2023-10-27 10:30:01,457 - INFO - [event_scanner:63] - EventScanner initialized for event 'TokensLocked' at 0x...
2023-10-27 10:30:02,789 - INFO - [blockchain_connector:39] - Successfully connected to RPC endpoint: https://polygon-mumbai.g.alchemy.com/v2/... (Chain ID: 80001)
2023-10-27 10:30:02,790 - INFO - [transaction_processor:87] - TransactionProcessor initialized for account 0xYourListenerAccountAddress
2023-10-27 10:30:02,791 - INFO - [bridge_orchestrator:215] - Starting Bridge Orchestrator...
2023-10-27 10:30:02,792 - INFO - [bridge_orchestrator:184] - Loaded state from scanner_state.json: {'last_processed_block': 4500100, 'processed_transactions': []}
2023-10-27 10:30:05,100 - INFO - [bridge_orchestrator:233] - Waiting for new blocks to be confirmed. Current head: 4500110
...
2023-10-27 10:30:20,500 - INFO - [event_scanner:79] - Found 1 'TokensLocked' event(s) between blocks 4500101-4500112
2023-10-27 10:30:20,501 - INFO - [bridge_orchestrator:245] - New confirmed event detected in block 4500105 (Tx: 0x...)
2023-10-27 10:30:20,502 - INFO - [transaction_processor:99] - Processing lock event: Recipient=0x..., Amount=1000000000000000000, SourceTxHash=0x...
2023-10-27 10:30:21,800 - INFO - [transaction_processor:130] - [SIMULATION] Prepared and signed transaction to mint tokens:
2023-10-27 10:30:21,801 - INFO - [transaction_processor:131] -   - To: 0x...
2023-10-27 10:30:21,801 - INFO - [transaction_processor:132] -   - From: 0xYourListenerAccountAddress
2023-10-27 10:30:21,801 - INFO - [transaction_processor:133] -   - Nonce: 42
2023-10-27 10:30:21,801 - INFO - [transaction_processor:134] -   - Data: 0x...
```