# Carbitrage - Distributed Car Arbitrage System

## Overview

This project is a distributed vehicle arbitrage system designed to find the best vehicle deals across multiple cities, based on either **lowest price** or **best price-per-kilometer ratio**. It operates as a fault-tolerant, leader-based cluster of nodes using the **RAFT Consensus Algorithm**, file replication, and reconciliation strategies to ensure consistency and reliability.

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

### 1. Leader Election (RAFT Implementation)

- **Algorithm**: [RAFT Consensus](https://raft.github.io/)
- **Terms**: Time is divided into terms, each beginning with an election
- **Election Process**: 
  - Nodes start as followers
  - If no heartbeat received within timeout (2-4 seconds), become candidate
  - Candidates request votes from other nodes
  - First candidate to receive majority votes becomes leader
  - Leaders maintain authority through periodic heartbeats

Each node:
- Maintains a current term number
- Votes for at most one candidate per term
- Steps down if it discovers a higher term
- Replicates log entries when leader

Implemented in `raft.py` and coordinated through `raft_instance.py`.

### 2. Log Replication & Consensus

- Leaders maintain a log of commands (file operations, leader changes)
- Each log entry contains:
  - Command data
  - Term number when entry was received
  - Index in the log
- Leaders replicate entries to followers through AppendEntries RPCs
- Entries become committed when replicated to majority of nodes
- State machine executes committed entries in order

### 3. Safety Properties

- **Election Safety**: At most one leader per term
- **Leader Append-Only**: Leaders never overwrite or delete entries
- **Log Matching**: If logs contain an entry with same index and term, logs are identical up to that point
- **Leader Completeness**: Committed entries survive leader changes
- **State Machine Safety**: All nodes execute same commands in same order

### 4. RAFT RPCs

- **RequestVote**: Used by candidates during elections
- **AppendEntries**: Used by leader for log replication and heartbeats
- Both include term numbers for maintaining consistency

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
- `POST /raft/append_entries`: Handles log replication and heartbeats
- `POST /raft/request_vote`: Handles vote requests during elections

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

It communicates with the backend leader node through JavaScript's `fetch()`.

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
2. Initializes as RAFT follower
3. Participates in leader election if no heartbeat received
4. If elected leader:
   - Begins sending heartbeats
   - Handles client requests
   - Manages log replication
5. If follower:
   - Responds to RPCs from leader
   - Monitors for leader timeout
   - Syncs cache from leader

---

## Technologies Used

- Python 3.10+
- FastAPI (REST API)
- Uvicorn (ASGI server)
- JavaScript (Frontend)
- RAFT Consensus Algorithm (Custom Implementation)
- JSON file-based coordination (`active_nodes.txt`)
- MarketCheck API (for car data)

---

## Example Usage

To start three nodes (minimum for fault tolerance):
```bash
python main.py 217
python main.py 536
python main.py 657
```

To start a client:
```bash
python client.py
```

To run the frontend:
Open `index.html` in a browser (requires local cluster nodes running).

---

## Implementation Details

### Term Persistence
- Terms are persisted to disk in `term_<node_id>.txt`
- Prevents term reset on node restart
- Maintains RAFT safety properties

### Timeout Configuration
- Election timeout: 2-4 seconds (randomized)
- Heartbeat interval: 0.5 seconds
- Configurable in `raft.py`
