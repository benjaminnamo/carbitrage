# election.py
import requests
import time
import json
import os
import atexit
from datetime import datetime, timedelta
from config import CLUSTER_NODES, NODE_REGISTRY
from state import NODE_ID, nodes, last_election, set_leader, get_leader

# Ensure node is marked offline on exit
@atexit.register
def mark_node_offline():
    try:
        if os.path.exists(NODE_REGISTRY):
            with open(NODE_REGISTRY, 'r') as f:
                registry = json.load(f)
            if str(NODE_ID) in registry:
                registry[str(NODE_ID)]["online"] = False
                registry[str(NODE_ID)]["role"] = "replica"
                registry[str(NODE_ID)]["candidate"] = False
                with open(NODE_REGISTRY, 'w') as f:
                    json.dump(registry, f, indent=2)
    except Exception as e:
        print(f"[Registry Shutdown Error] {e}")

def update_node_registry(node_id, is_online, is_leader, is_candidate=False):
    try:
        if not os.path.exists(NODE_REGISTRY):
            with open(NODE_REGISTRY, 'w') as f:
                json.dump({}, f)

        with open(NODE_REGISTRY, 'r') as f:
            try:
                registry = json.load(f)
            except json.JSONDecodeError:
                registry = {}

        if not isinstance(registry, dict):
            registry = {}

        if str(node_id) not in registry:
            registry[str(node_id)] = {}

        registry[str(node_id)]["id"] = node_id
        registry[str(node_id)]["online"] = is_online
        registry[str(node_id)]["role"] = "leader" if is_leader else "replica"
        registry[str(node_id)]["candidate"] = is_candidate

        with open(NODE_REGISTRY, 'w') as f:
            json.dump(registry, f, indent=2)
    except Exception as e:
        print(f"[Registry Error] Could not update registry: {e}")

def discover_leader():
    time.sleep(2)  # Wait for full app startup
    print(f"[Startup] Node {NODE_ID} attempting to discover leader...")
    try:
        if not os.path.exists(NODE_REGISTRY):
            return False
        with open(NODE_REGISTRY, 'r') as f:
            registry = json.load(f)
        for nid_str, info in registry.items():
            nid = int(nid_str)
            if info.get("role") == "leader" and info.get("online") and nid != NODE_ID:
                port = CLUSTER_NODES.get(nid)
                if port:
                    try:
                        res = requests.get(f"http://localhost:{port}/health", timeout=2)
                        if res.status_code == 200:
                            set_leader(nid)
                            nodes[nid] = datetime.now()
                            print(f"[Discovery] Leader confirmed alive: Node {nid}")
                            return True
                    except:
                        registry[str(nid)]["online"] = False
                        registry[str(nid)]["role"] = "replica"
                        with open(NODE_REGISTRY, 'w') as f:
                            json.dump(registry, f, indent=2)
                        continue
    except Exception as e:
        print(f"[Discovery Error] {e}")
    print("[Discovery] No reachable leader found.")
    return False

def initiate_bully_election():
    global last_election
    print(f"[Election] Node {NODE_ID} initiating election...")

    # Delay based on ID to give priority to higher nodes
    delay = (max(CLUSTER_NODES.keys()) - NODE_ID) * 0.005
    print(f"[Election] Node {NODE_ID} waiting {delay:.1f}s before starting election...")
    time.sleep(delay)

    update_node_registry(NODE_ID, True, False, True)  # mark self as candidate

    try:
        with open(NODE_REGISTRY, 'r') as f:
            registry = json.load(f)
    except:
        registry = {}

    higher_ids = [nid for nid in CLUSTER_NODES if nid > NODE_ID]

    for nid in higher_ids:
        try:
            port = CLUSTER_NODES[nid]
            res = requests.get(f"http://localhost:{port}/health", timeout=2)
            if res.status_code == 200:
                remote_is_leader = registry.get(str(nid), {}).get("role") == "leader"
                if remote_is_leader:
                    print(f"[Election] Node {NODE_ID} found Node {nid} alive and higher. Node {NODE_ID} is dropping out of the election.")
                    update_node_registry(NODE_ID, True, False, False)
                    set_leader(nid)
                    return
        except:
            continue

    set_leader(NODE_ID)
    last_election = datetime.now()
    update_node_registry(NODE_ID, True, True, False)
    print(f"[Election] Node {NODE_ID} became the leader.")

    for nid, port in CLUSTER_NODES.items():
        if nid != NODE_ID:
            try:
                res = requests.post(f"http://localhost:{port}/set-leader", json={"leader_id": NODE_ID}, timeout=2)
                if res.status_code == 200:
                    print(f"[Leader Update] New leader set to Node {NODE_ID} for Node {nid}")
            except:
                continue

def heartbeat_loop():
    global last_election

    update_node_registry(NODE_ID, True, False)
    if not discover_leader():
        initiate_bully_election()

    while True:
        now = datetime.now()
        stale = [nid for nid, ts in nodes.items() if now - ts > timedelta(seconds=5)]
        for nid in stale:
            del nodes[nid]

        current_leader = get_leader()
        if current_leader and current_leader != NODE_ID:
            port = CLUSTER_NODES.get(current_leader)
            if port:
                try:
                    res = requests.get(f"http://localhost:{port}/health", timeout=2)
                    if res.status_code == 200:
                        if current_leader not in nodes:
                            print(f"[Leader Update] Node {current_leader} is now considered alive.")
                        nodes[current_leader] = datetime.now()
                        print(f"[Heartbeat] Leader {current_leader} is alive.")
                        time.sleep(3)
                        continue
                except:
                    print(f"[Heartbeat FAIL] Leader {current_leader} did not respond.")

        leader_is_stale = (
            current_leader not in nodes or
            datetime.now() - nodes.get(current_leader, datetime.min) > timedelta(seconds=5)
        ) and current_leader != NODE_ID

        if leader_is_stale and (not last_election or datetime.now() - last_election > timedelta(seconds=6)):
            set_leader(None)
            initiate_bully_election()

        time.sleep(3)
