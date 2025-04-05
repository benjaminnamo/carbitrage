import os
import threading
import uvicorn
from fastapi import FastAPI
import time
import requests

from state import NODE_PORT, NODE_ID, CACHE_DIR
from config import NODE_REGISTRY, CLUSTER_NODES
from raft_instance import raft_node
from routes import router
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from datetime import datetime

# Track first-node startup
FIRST_NODE_STARTUP = False

# Initialize FastAPI app
app = FastAPI(title="Distributed Car Arbitrage Node")

# Add CORS support
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)

# Ensure cache dir exists
os.makedirs(CACHE_DIR, exist_ok=True)

# Initialize node in registry
raft_node.update_node_registry(NODE_ID, True, False)

@app.post("/reconcile")
async def reconcile():
    # Leader reconciliation with replicas
    print(f"[Reconcile] Leader {NODE_ID} initiating reconciliation with replicas...")
    for nid, port in CLUSTER_NODES.items():
        if nid == NODE_ID:
            continue
        try:
            health = requests.get(f"http://localhost:{port}/health", timeout=2)
            if health.status_code != 200:
                print(f"[Reconcile Skipped] Node {nid} is not healthy.")
                continue
        except requests.exceptions.RequestException:
            print(f"[Reconcile Skipped] Node {nid} is offline.")
            continue

        try:
            res = requests.get(f"http://localhost:{port}/list-cache", timeout=5)
            if res.status_code != 200:
                print(f"[Reconcile] Could not list files on Node {nid}.")
                continue

            their_files = res.json().get("files", [])
            for filename in their_files:
                try:
                    meta = requests.get(f"http://localhost:{port}/cache-meta", params={"filename": filename}, timeout=5)
                    if meta.status_code != 200:
                        continue
                    replica_data = meta.json()
                    replica_mtime = replica_data.get("mtime", 0)
                    local_path = os.path.join(CACHE_DIR, filename)
                    leader_mtime = os.path.getmtime(local_path) if os.path.exists(local_path) else 0
                    if replica_mtime > leader_mtime or not os.path.exists(local_path):
                        file_res = requests.get(f"http://localhost:{port}/get-cache-file", params={"filename": filename}, timeout=10)
                        if file_res.status_code == 200:
                            with open(local_path, "wb") as f:
                                f.write(file_res.content)
                            print(f"[Reconcile] Pulled {filename} from Node {nid}")
                        else:
                            print(f"[Reconcile] Failed to pull {filename} from Node {nid}")
                except Exception as e:
                    print(f"[Reconcile] Error processing {filename} from Node {nid}: {e}")
        except Exception as e:
            print(f"[Reconcile Error] Failed to fetch from Node {nid}: {e}")
    return {"status": "done"}

def sync_cache_from_leader():
    # Sync cache from leader node
    from state import get_leader
    leader_id = get_leader()
    if leader_id is None or leader_id == NODE_ID:
        global FIRST_NODE_STARTUP
        FIRST_NODE_STARTUP = True
        return
    leader_port = CLUSTER_NODES[leader_id]
    print(f"[Sync] Attempting to sync cache from Leader Node {leader_id}...")
    try:
        res = requests.get(f"http://localhost:{leader_port}/list-cache", timeout=5)
        files = res.json().get("files", [])
        for filename in files:
            local_path = os.path.join(CACHE_DIR, filename)
            if os.path.exists(local_path):
                continue
            file_res = requests.get(f"http://localhost:{leader_port}/get-cache-file", params={"filename": filename}, timeout=10)
            if file_res.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(file_res.content)
                print(f"[Sync] Downloaded {filename} from leader")
    except requests.exceptions.ConnectionError:
        print("[Sync Warning] Leader is unreachable. Skipping cache sync.")
    except Exception as e:
        print(f"[Sync Error] {e}")

def attempt_leader_reconciliation():
    # Trigger reconciliation if this node is leader
    from state import get_leader
    current_leader = get_leader()
    if current_leader != NODE_ID:
        return
    print(f"[Reconcile Trigger] Node {NODE_ID} is confirmed leader. Triggering reconciliation...")
    try:
        requests.post(f"http://localhost:{NODE_PORT}/reconcile", timeout=10)
    except Exception as e:
        print(f"[Reconcile Error] Failed to initiate: {e}")

def periodic_replica_discovery():
    # Background thread for replica discovery
    def check_for_new_nodes():
        while True:
            time.sleep(10)
            if not FIRST_NODE_STARTUP:
                continue
            print("[Watchdog] Checking for new replicas to reconcile with...")
            attempt_leader_reconciliation()
    threading.Thread(target=check_for_new_nodes, daemon=True).start()

if __name__ == "__main__":
    time.sleep(1)
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT)
