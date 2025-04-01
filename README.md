
# Carbitrage - Distributed Car Arbitrage System

## Overview

This project is a distributed vehicle arbitrage system designed to find the best vehicle deals across multiple cities, based on either **lowest price** or **best price-per-kilometer ratio**. It operates as a fault-tolerant, leader-based cluster of nodes using the **Bully Election Algorithm**, file replication, and reconciliation strategies to ensure consistency and reliability.

The system consists of:
- A frontend web interface and CLI client
- A distributed backend with leader election
- A shared API for fetching, caching, and comparing car listings
- Replication and reconciliation between cluster nodes

---

## Distributed Architecture

### Cluster Composition

Each node in the cluster is assigned a unique ID and port from the `CLUSTER_NODES` dictionary. Nodes can be started independently and will attempt to:

    1. Discover an existing leader
    2. Join the cluster
    3. Synchronize cache from the current leader

Nodes are tracked in a registry (`active_nodes.txt`) with their:
- Online status
- Role (leader or replica)
- Candidacy status

```json
{
  "217": {
    "id": 217,
    "online": true,
    "role": "leader",
    "candidate": false
  },
  ...
}
```
---

## Core Distributed Systems Components

### 1. Leader Election

- **Algorithm**: [Bully Algorithm](https://en.wikipedia.org/wiki/Bully_algorithm)
- **Trigger**: When no leader is found or the leader becomes unresponsive
- **Priority**: Nodes with higher IDs have higher priority

Each node can:
- Initiate an election if it doesn't detect a valid leader
- Ping higher-ID nodes before declaring itself as leader
- Accept the higher-ID node as leader if it responds
- Notify all other nodes upon becoming leader

Implemented in [`election.py`](./election.py) and orchestrated during node startup in [`main.py`](./main.py).

---

### 2. Heartbeat & Fault Detection

- Nodes continuously check if the current leader is alive via periodic `GET /health` requests
- If the leader is unresponsive for more than 5 seconds, an election is triggered
- Heartbeats are tracked using the `nodes` dictionary with timestamps

This loop runs in a background thread started in `main.py` and managed by `election.heartbeat_loop()`.

---

### 3. Data Replication

- The leader replicates fetched car listings to all replicas by sending `.csv` files via HTTP POST to `/replicate`
- Replicas store these files in their local `cache/node_<id>` directories
- New nodes sync the full cache from the current leader using `/list-cache` and `/get-cache-file` APIs

See `car_fetching.replicate_to_followers()` and `main.sync_cache_from_leader()`.

---

### 4. Reconciliation

- To maintain consistency, the leader periodically initiates a reconciliation process
- Each node is asked to list its cache contents and provide modification times
- The leader pulls any newer or missing files from replicas

Leader-triggered reconciliation is exposed via:
- `POST /reconcile` endpoint
- Periodic background thread (`periodic_replica_discovery`)

All logic lives in `main.py` and `routes.py`.

---

### 5. Fault Tolerance & Shutdown

- Nodes are marked offline and reset to replica in the registry via `atexit.register()` on shutdown
- Leader state is reset if the leader becomes unreachable or crashes

---

## API Endpoints (FastAPI)

- `GET /health`: Node liveness check
- `GET /leader`: Returns the current leader
- `POST /client`: Main entry point for user search queries (must be called on leader)
- `POST /replicate`: Used by leader to replicate cache files
- `GET /list-cache`, `GET /cache-meta`, `GET /get-cache-file`: Support cache introspection
- `POST /set-leader`: Informs replicas of new leader
- `POST /reconcile`: Leader pulls newer files from replicas

---

## Client Interfaces

### 1. Command Line Interface

In `client.py`, CLI clients can:
- Discover the current leader
- Perform vehicle comparison by price or price-per-km
- Recommend the better purchase location

### 2. Web Interface

In `index.html`, the user can:
- Select cities, make, and model
- Choose between cheapest or arbitrage mode
- View the best vehicle listings from both cities
- See visual highlights and purchase recommendations

It communicates with the backend leader node through JavaScript’s `fetch()`.

---

## Caching

- All listings are cached as CSV files
- Cache expires after 24 hours (adjustable)
- Prevents redundant API calls to MarketCheck

Check logic: `car_fetching.is_recent()`  
Save/load: `save_to_csv`, `load_from_csv`

---

## Node Startup Flow

    1. Node boots and selects its ID (via command line or randomly)
    2. Checks for an existing leader using `discover_leader()`
    3. If none found, initiates election using `initiate_bully_election()`
    4. If elected leader, begins cache reconciliation
    5. If replica, syncs cache from leader

---

## Technologies Used

- Python 3.10+
- FastAPI (REST API)
- Uvicorn (ASGI server)
- JavaScript (Frontend)
- Bully Algorithm (Custom Implementation)
- JSON file-based coordination (`active_nodes.txt`)
- MarketCheck API (for car data)

---

## Example Usage

To start a node:
```bash
python main.py 217
```

To start a client:
```bash
python client.py
```

To run the frontend:
Open `index.html` in a browser (requires local cluster nodes running).

---

## Future Improvements

- Upgrade to RAFT
