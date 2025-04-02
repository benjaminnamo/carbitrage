# state.py
import os
import random
import sys
from config import CLUSTER_NODES
from raft import NodeState

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

def get_leader():
    from raft_instance import raft_node
    if raft_node.state == NodeState.LEADER:
        return NODE_ID
    # If we're a follower and have received append entries, return the known leader
    if hasattr(raft_node, 'current_leader'):
        return raft_node.current_leader
    return None

def set_leader(new_id):
    from raft_instance import raft_node
    if raft_node.state == NodeState.LEADER:
        raft_node.append_command({
            "type": "set_leader",
            "leader_id": new_id
        })
