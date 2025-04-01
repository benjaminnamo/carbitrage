# state.py
import os
import random
import sys
from config import CLUSTER_NODES

# Assign or verify node identity
if len(sys.argv) > 1:
    NODE_ID = int(sys.argv[1])
    if NODE_ID not in CLUSTER_NODES:
        raise ValueError(f"NODE_ID {NODE_ID} not in CLUSTER_NODES")
else:
    NODE_ID = random.choice(list(CLUSTER_NODES.keys()))

NODE_PORT = CLUSTER_NODES[NODE_ID]

# Set up node-specific cache directory
CACHE_DIR = f"cache/node_{NODE_ID}"
os.makedirs(CACHE_DIR, exist_ok=True)

# Leader state
leader_id = None
nodes = {}
last_election = None

def set_leader(new_id):
    global leader_id
    from main import NODE_ID, attempt_leader_reconciliation  # Safe local import to avoid circular import
    leader_id = new_id
    if new_id == NODE_ID:
        print(f"[Leadership] Node {NODE_ID} is now the leader. Initiating reconciliation...")
        attempt_leader_reconciliation()


def get_leader():
    return leader_id
