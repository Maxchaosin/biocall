import os
import sys
import json
import time
import logging
from typing import Dict, Any, Optional, List

import requests
from web3 import Web3
from web3.exceptions import BlockNotFound
from web3.contract import Contract
from web3.types import LogReceipt
from dotenv import load_dotenv

# --- Basic Configuration ---
STATE_FILE = 'scanner_state.json'
LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s'

# Configure logging
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration loading from environment variables."""

    def __init__(self):
        """Loads environment variables from a .env file."""
        load_dotenv()
        self.source_rpc_url = os.getenv('SOURCE_CHAIN_RPC_URL')
        self.dest_rpc_url = os.getenv('DESTINATION_CHAIN_RPC_URL')
        self.source_bridge_address = os.getenv('SOURCE_BRIDGE_CONTRACT_ADDRESS')
        self.dest_bridge_address = os.getenv('DESTINATION_BRIDGE_CONTRACT_ADDRESS')
        self.listener_private_key = os.getenv('LISTENER_PRIVATE_KEY')
        self.confirmations_required = int(os.getenv('BLOCK_CONFIRMATIONS_REQUIRED', '12'))
        self.scan_batch_size = int(os.getenv('SCAN_BATCH_SIZE', '100'))
        self.poll_interval_seconds = int(os.getenv('POLL_INTERVAL_SECONDS', '10'))

        self.validate()

    def validate(self):
        """Validates that all necessary configuration is present."""
        required_vars = [
            'source_rpc_url', 'dest_rpc_url',
            'source_bridge_address', 'dest_bridge_address',
            'listener_private_key'
        ]
        missing_vars = [var for var in required_vars if not getattr(self, var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.info("Configuration loaded and validated successfully.")

    def get_source_bridge_abi(self) -> List[Dict[str, Any]]:
        """Provides a sample ABI for the source chain bridge contract."""
        # In a real system, this would be loaded from a file.
        return json.loads('''
        [
            {
                "anonymous": false,
                "inputs": [
                    {"indexed": true, "internalType": "address", "name": "sender", "type": "address"},
                    {"indexed": false, "internalType": "address", "name": "recipient", "type": "address"},
                    {"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"indexed": true, "internalType": "uint256", "name": "destinationChainId", "type": "uint256"}
                ],
                "name": "TokensLocked",
                "type": "event"
            }
        ]
        ''')

    def get_dest_bridge_abi(self) -> List[Dict[str, Any]]:
        """Provides a sample ABI for the destination chain bridge contract."""
        return json.loads('''
        [
            {
                "inputs": [
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "bytes32", "name": "sourceTxHash", "type": "bytes32"}
                ],
                "name": "mintTokens",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        ''')

class BlockchainConnector:
    """Manages the connection to a blockchain via a Web3 provider."""

    def __init__(self, rpc_url: str):
        """Initializes the connector with a given RPC URL."""
        self.rpc_url = rpc_url
        self.web3: Optional[Web3] = None

    def connect(self):
        """Establishes and tests the connection to the blockchain node."""
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={'timeout': 60}))
            if self.web3.is_connected():
                chain_id = self.web3.eth.chain_id
                logger.info(f"Successfully connected to RPC endpoint: {self.rpc_url} (Chain ID: {chain_id})")
            else:
                raise ConnectionError(f"Failed to connect to RPC endpoint: {self.rpc_url}")
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request error while connecting to {self.rpc_url}: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during connection to {self.rpc_url}: {e}")
            raise

    def get_web3(self) -> Web3:
        """Returns the Web3 instance, ensuring a connection is established."""
        if not self.web3 or not self.web3.is_connected():
            logger.warning("Web3 connection lost. Attempting to reconnect...")
            self.connect()
        return self.web3

class EventScanner:
    """Scans a blockchain for specific smart contract events."""

    def __init__(self, connector: BlockchainConnector, contract_address: str, abi: List[Dict[str, Any]], event_name: str):
        """Initializes the scanner with connection and contract details."""
        self.web3 = connector.get_web3()
        self.contract_address = self.web3.to_checksum_address(contract_address)
        self.contract: Contract = self.web3.eth.contract(address=self.contract_address, abi=abi)
        self.event = getattr(self.contract.events, event_name)
        self.event_name = event_name
        logger.info(f"EventScanner initialized for event '{event_name}' at {self.contract_address}")

    def scan_blocks(self, from_block: int, to_block: int) -> List[LogReceipt]:
        """Scans a range of blocks for the specified event and handles potential errors."""
        if from_block > to_block:
            return []

        logger.debug(f"Scanning for '{self.event_name}' events from block {from_block} to {to_block}")
        try:
            event_filter = self.event.create_filter(fromBlock=from_block, toBlock=to_block)
            events = event_filter.get_all_entries()
            if events:
                logger.info(f"Found {len(events)} '{self.event_name}' event(s) between blocks {from_block}-{to_block}")
            return events
        except BlockNotFound:
            logger.warning(f"Block range not found ({from_block}-{to_block}). The RPC node might be out of sync. Retrying later.")
            return []
        except requests.exceptions.Timeout:
            logger.error(f"RPC request timed out while scanning blocks {from_block}-{to_block}. Will retry in the next cycle.")
            return []
        except Exception as e:
            # This can catch a variety of issues, like oversized requests to the RPC.
            logger.error(f"Error scanning blocks {from_block}-{to_block}: {e}. Consider reducing SCAN_BATCH_SIZE.")
            return []

class TransactionProcessor:
    """Handles the creation and (simulated) submission of transactions on the destination chain."""

    def __init__(self, connector: BlockchainConnector, contract_address: str, abi: List[Dict[str, Any]], private_key: str):
        """Initializes the processor with destination chain details."""
        self.web3 = connector.get_web3()
        self.contract_address = self.web3.to_checksum_address(contract_address)
        self.contract = self.web3.eth.contract(address=self.contract_address, abi=abi)
        self.account = self.web3.eth.account.from_key(private_key)
        logger.info(f"TransactionProcessor initialized for account {self.account.address}")

    def process_lock_event(self, event: LogReceipt):
        """Processes a 'TokensLocked' event by preparing a 'mintTokens' transaction."""
        args = event['args']
        source_tx_hash = event['transactionHash']
        recipient = args['recipient']
        amount = args['amount']

        logger.info(
            f"Processing lock event: Recipient={recipient}, Amount={amount}, "
            f"SourceTxHash={source_tx_hash.hex()}"
        )

        try:
            nonce = self.web3.eth.get_transaction_count(self.account.address)
            tx_params = {
                'from': self.account.address,
                'nonce': nonce,
                'gas': 200000,  # A reasonable gas limit for a mint function
                'gasPrice': self.web3.eth.gas_price, # In a real system, use a better gas strategy
            }

            # Build the transaction
            mint_tx = self.contract.functions.mintTokens(
                recipient,
                amount,
                source_tx_hash
            ).build_transaction(tx_params)

            # Sign the transaction
            signed_tx = self.web3.eth.account.sign_transaction(mint_tx, self.account.key)

            # --- SIMULATION --- #
            # In a real-world scenario, you would send the raw transaction:
            # tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # logger.info(f"Submitted mint transaction to destination chain. Tx hash: {tx_hash.hex()}")
            # return tx_hash
            
            logger.info("[SIMULATION] Prepared and signed transaction to mint tokens:")
            logger.info(f"  - To: {mint_tx['to']}")
            logger.info(f"  - From: {mint_tx['from']}")
            logger.info(f"  - Nonce: {mint_tx['nonce']}")
            logger.info(f"  - Data: {mint_tx['data'][:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to process event and create transaction for source hash {source_tx_hash.hex()}: {e}")
            return False

class BridgeOrchestrator:
    """Orchestrates the entire cross-chain listening and processing workflow."""

    def __init__(self, config: ConfigManager):
        """Initializes all components of the bridge listener."""
        self.config = config
        self.state = self._load_state()

        # Setup source chain components
        self.source_connector = BlockchainConnector(config.source_rpc_url)
        self.source_connector.connect()
        self.event_scanner = EventScanner(
            self.source_connector,
            config.source_bridge_address,
            config.get_source_bridge_abi(),
            'TokensLocked'
        )

        # Setup destination chain components
        self.dest_connector = BlockchainConnector(config.dest_rpc_url)
        self.dest_connector.connect()
        self.tx_processor = TransactionProcessor(
            self.dest_connector,
            config.dest_bridge_address,
            config.get_dest_bridge_abi(),
            config.listener_private_key
        )

        self.processed_transactions = set(self.state.get('processed_transactions', []))

    def _load_state(self) -> Dict[str, Any]:
        """Loads the last processed block number from a state file."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                    logger.info(f"Loaded state from {STATE_FILE}: {state}")
                    return state
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not read state file {STATE_FILE}, starting fresh. Error: {e}")
        return {"last_processed_block": None, "processed_transactions": []}

    def _save_state(self):
        """Saves the last processed block number to the state file."""
        try:
            with open(STATE_FILE, 'w') as f:
                state_data = {
                    "last_processed_block": self.state.get('last_processed_block'),
                    "processed_transactions": list(self.processed_transactions)
                }
                json.dump(state_data, f, indent=4)
                logger.debug(f"Saved state to {STATE_FILE}")
        except IOError as e:
            logger.error(f"Could not write to state file {STATE_FILE}: {e}")

    def run(self):
        """The main execution loop for the orchestrator."""
        logger.info("Starting Bridge Orchestrator...")
        w3_source = self.source_connector.get_web3()

        if self.state['last_processed_block'] is None:
            # If starting for the first time, begin from the current block to avoid processing history.
            self.state['last_processed_block'] = w3_source.eth.block_number - self.config.confirmations_required
            logger.info(f"No previous state found. Starting scan from block {self.state['last_processed_block']}")

        while True:
            try:
                latest_block = w3_source.eth.block_number
                # The `to_block` is calculated to ensure we only process blocks that are confirmed.
                to_block = latest_block - self.config.confirmations_required
                from_block = self.state['last_processed_block'] + 1

                if from_block > to_block:
                    logger.info(f"Waiting for new blocks to be confirmed. Current head: {latest_block}")
                    time.sleep(self.config.poll_interval_seconds)
                    continue
                
                # Ensure we don't query a massive range in one go
                if to_block > from_block + self.config.scan_batch_size - 1:
                    to_block = from_block + self.config.scan_batch_size - 1

                events = self.event_scanner.scan_blocks(from_block, to_block)

                for event in events:
                    tx_hash_hex = event['transactionHash'].hex()
                    if tx_hash_hex in self.processed_transactions:
                        logger.warning(f"Skipping already processed transaction: {tx_hash_hex}")
                        continue

                    logger.info(f"New confirmed event detected in block {event['blockNumber']} (Tx: {tx_hash_hex})")
                    success = self.tx_processor.process_lock_event(event)
                    if success:
                        self.processed_transactions.add(tx_hash_hex)

                self.state['last_processed_block'] = to_block
                self._save_state()
                
                # If we processed a full batch, check again immediately.
                # Otherwise, wait for the poll interval.
                if to_block - from_block < self.config.scan_batch_size -1 :
                     time.sleep(self.config.poll_interval_seconds)

            except Exception as e:
                logger.error(f"An error occurred in the main loop: {e}", exc_info=True)
                time.sleep(self.config.poll_interval_seconds * 2) # Longer sleep on error

def main():
    """Main entry point of the script."""
    try:
        config = ConfigManager()
        orchestrator = BridgeOrchestrator(config)
        orchestrator.run()
    except ValueError as e:
        logger.critical(f"Configuration error: {e}")
        sys.exit(1)
    except ConnectionError as e:
        logger.critical(f"Blockchain connection error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Shutting down listener gracefully.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"An unhandled exception occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()

# @-internal-utility-start
def validate_payload_3156(payload: dict):
    """Validates incoming data payload on 2025-10-21 19:37:49"""
    if not isinstance(payload, dict):
        return False
    required_keys = ['id', 'timestamp', 'data']
    return all(key in payload for key in required_keys)
# @-internal-utility-end


# @-internal-utility-start
def validate_payload_7052(payload: dict):
    """Validates incoming data payload on 2025-10-21 19:39:03"""
    if not isinstance(payload, dict):
        return False
    required_keys = ['id', 'timestamp', 'data']
    return all(key in payload for key in required_keys)
# @-internal-utility-end

