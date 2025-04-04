import random
import time
import threading
import json
import os
from enum import Enum
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import requests
from config import CLUSTER_NODES, NODE_REGISTRY

class NodeState(Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"

class LogEntry:
    def __init__(self, term: int, command: dict, index: int):
        self.term = term
        self.command = command
        self.index = index

class RaftNode:
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.current_term = 0
        self.voted_for = None
        self.log: List[LogEntry] = []
        
        # Volatile state
        self.state = NodeState.FOLLOWER
        self.commit_index = 0
        self.last_applied = 0
        
        # Leader state
        self.next_index: Dict[int, int] = {nid: 1 for nid in CLUSTER_NODES.keys()}
        self.match_index: Dict[int, int] = {nid: 0 for nid in CLUSTER_NODES.keys()}
        
        # Election timeout
        self.MIN_TIMEOUT = 2.0  # seconds
        self.MAX_TIMEOUT = 4.0  # seconds
        self.HEARTBEAT_INTERVAL = 0.5  # seconds
        
        # Add heartbeat timer
        self.heartbeat_timer = None
        
        # Persist term number
        self.term_file = f"term_{node_id}.txt"
        self.load_persistent_state()
        
        # Initialize node registry
        self.initialize_node_registry()
        
        # Initialize last_heartbeat
        self.last_heartbeat = datetime.now()
        self.election_timeout = self.get_random_timeout()
        
        # Start election timer
        self.election_timer = threading.Thread(target=self._run_election_timer, daemon=True)
        self.election_timer.start()
        
        # Start commit checker
        self.commit_checker = threading.Thread(target=self._check_commits, daemon=True)
        self.commit_checker.start()

    def initialize_node_registry(self):
        """Initialize or load the node registry file"""
        if not os.path.exists(NODE_REGISTRY):
            with open(NODE_REGISTRY, 'w') as f:
                json.dump({}, f)
        self.update_node_registry(self.node_id, True, False)

    def update_node_registry(self, node_id: int, is_online: bool, is_leader: bool, is_candidate: bool = False):
        """Update the node registry with node status"""
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

    def load_persistent_state(self):
        """Load persistent state from disk"""
        try:
            if os.path.exists(self.term_file):
                with open(self.term_file, 'r') as f:
                    self.current_term = int(f.read().strip())
        except:
            self.current_term = 0

    def save_term(self):
        """Save term to persistent storage"""
        with open(self.term_file, 'w') as f:
            f.write(str(self.current_term))

    def get_random_timeout(self) -> float:
        """Get a random election timeout"""
        return random.uniform(self.MIN_TIMEOUT, self.MAX_TIMEOUT)

    def _run_election_timer(self):
        while True:
            time.sleep(0.1)  # Check every 100ms
            if self.state == NodeState.LEADER:
                continue
            
            time_since_last_heartbeat = (datetime.now() - self.last_heartbeat).total_seconds()
            if time_since_last_heartbeat > self.election_timeout:
                # Only start election if we have potential voters
                active_nodes = self.get_active_nodes()
                if len(active_nodes) > 1:  # More than just ourselves
                    self.start_election()
                else:
                    # Reset timer if we're alone
                    self.last_heartbeat = datetime.now()

    def start_election(self):
        if self.state == NodeState.LEADER:
            return

        self.state = NodeState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.last_heartbeat = datetime.now()
        self.election_timeout = self.get_random_timeout()

        votes_received = 1  # Vote for self
        print(f"\n[RAFT] Node {self.node_id} starting election for term {self.current_term}")
        print(f"[RAFT] Node {self.node_id} voting for self (1 vote)")
        
        # Request votes from all other nodes
        for nid, port in CLUSTER_NODES.items():
            if nid == self.node_id:
                continue

            try:
                last_log_index = len(self.log)
                last_log_term = self.log[-1].term if self.log else 0

                data = {
                    "term": self.current_term,
                    "candidate_id": self.node_id,
                    "last_log_index": last_log_index,
                    "last_log_term": last_log_term
                }

                response = requests.post(
                    f"http://localhost:{port}/raft/request_vote",
                    json=data,
                    timeout=0.5
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("vote_granted"):
                        votes_received += 1
                        print(f"[RAFT] Node {nid} voted for Node {self.node_id} ({votes_received} votes)")
                    else:
                        print(f"[RAFT] Node {nid} rejected vote for Node {self.node_id}")

            except Exception as e:
                print(f"[RAFT] Node {nid} unreachable")

        # Check if we won the election
        needed_votes = (len(CLUSTER_NODES) // 2) + 1
        print(f"[RAFT] Node {self.node_id} received {votes_received} votes (need {needed_votes} to win)")
        
        if votes_received >= needed_votes:
            print(f"[RAFT] Node {self.node_id} won election for term {self.current_term}!")
            self.become_leader()
        else:
            print(f"[RAFT] Node {self.node_id} lost election for term {self.current_term}")
            self.state = NodeState.FOLLOWER

    def become_leader(self):
        if self.state != NodeState.CANDIDATE:
            return

        print(f"\n[RAFT] Node {self.node_id} has become the leader for term {self.current_term}!\n")
        self.state = NodeState.LEADER
        self.next_index = {nid: len(self.log) + 1 for nid in CLUSTER_NODES.keys()}
        self.match_index = {nid: 0 for nid in CLUSTER_NODES.keys()}
        
        # Start regular heartbeat
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
        self.heartbeat_timer = threading.Timer(self.HEARTBEAT_INTERVAL, self._heartbeat_loop)
        self.heartbeat_timer.daemon = True
        self.heartbeat_timer.start()

    def _heartbeat_loop(self):
        """Continuous heartbeat loop for leader"""
        while self.state == NodeState.LEADER:
            self.send_heartbeat()
            time.sleep(self.HEARTBEAT_INTERVAL)

    def send_heartbeat(self):
        if self.state != NodeState.LEADER:
            return

        active_nodes = set()  # Track responsive nodes
        for nid, port in CLUSTER_NODES.items():
            if nid == self.node_id:
                continue

            try:
                # First check if node is alive
                health_check = requests.get(f"http://localhost:{port}/health", timeout=0.1)
                if health_check.status_code != 200:
                    continue

                active_nodes.add(nid)
                next_idx = self.next_index[nid]
                prev_log_index = next_idx - 1
                prev_log_term = self.log[prev_log_index - 1].term if prev_log_index > 0 else 0

                entries = self.log[next_idx-1:] if next_idx <= len(self.log) else []

                data = {
                    "term": self.current_term,
                    "leader_id": self.node_id,
                    "prev_log_index": prev_log_index,
                    "prev_log_term": prev_log_term,
                    "entries": [{"term": e.term, "command": e.command} for e in entries],
                    "leader_commit": self.commit_index
                }

                response = requests.post(
                    f"http://localhost:{port}/raft/append_entries",
                    json=data,
                    timeout=0.2
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        if entries:
                            self.match_index[nid] = prev_log_index + len(entries)
                            self.next_index[nid] = self.match_index[nid] + 1
                    else:
                        self.next_index[nid] = max(1, self.next_index[nid] - 1)

            except requests.exceptions.RequestException:
                # Silently ignore connection errors for known inactive nodes
                continue
            except Exception as e:
                print(f"[RAFT] Unexpected error with node {nid}: {e}")

    def handle_append_entries(self, data: dict) -> dict:
        term = data.get("term", 0)
        
        # If we see a higher term, step down
        if term > self.current_term:
            self.current_term = term
            self.save_term()
            self.state = NodeState.FOLLOWER
            self.voted_for = None
            if self.heartbeat_timer:
                self.heartbeat_timer.cancel()
        
        # Reset election timeout if we get a valid append entries
        if term >= self.current_term:
            self.last_heartbeat = datetime.now()
        
        leader_id = data.get("leader_id")
        
        # Track current leader
        if leader_id is not None:
            self.current_leader = leader_id
        
        # Reply false if term < currentTerm
        if term < self.current_term:
            return {"term": self.current_term, "success": False}

        # Update term if needed
        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
            self.state = NodeState.FOLLOWER

        self.last_heartbeat = datetime.now()
        
        prev_log_index = data.get("prev_log_index", 0)
        prev_log_term = data.get("prev_log_term", 0)

        # Reply false if log doesn't contain an entry at prevLogIndex whose term matches prevLogTerm
        if prev_log_index > 0:
            if len(self.log) < prev_log_index:
                return {"term": self.current_term, "success": False}
            if self.log[prev_log_index - 1].term != prev_log_term:
                return {"term": self.current_term, "success": False}

        # Process entries
        entries = data.get("entries", [])
        for i, entry in enumerate(entries):
            log_index = prev_log_index + i + 1
            
            # If an existing entry conflicts with a new one, delete it and all that follow
            if log_index <= len(self.log):
                if self.log[log_index - 1].term != entry["term"]:
                    self.log = self.log[:log_index - 1]
            
            # Append any new entries not already in the log
            if log_index > len(self.log):
                self.log.append(LogEntry(entry["term"], entry["command"], log_index))

        # Update commit index
        leader_commit = data.get("leader_commit", 0)
        if leader_commit > self.commit_index:
            self.commit_index = min(leader_commit, len(self.log))

        return {"term": self.current_term, "success": True}

    def handle_request_vote(self, data: dict) -> dict:
        term = data.get("term", 0)
        candidate_id = data.get("candidate_id")
        
        if term < self.current_term:
            print(f"[RAFT] Node {self.node_id} rejecting vote: candidate term {term} < current term {self.current_term}")
            return {"term": self.current_term, "vote_granted": False}

        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
            self.state = NodeState.FOLLOWER

        last_log_index = data.get("last_log_index", 0)
        last_log_term = data.get("last_log_term", 0)

        # Check if candidate's log is at least as up-to-date as receiver's log
        my_last_log_index = len(self.log)
        my_last_log_term = self.log[-1].term if self.log else 0

        log_is_up_to_date = (
            last_log_term > my_last_log_term or
            (last_log_term == my_last_log_term and last_log_index >= my_last_log_index)
        )

        if (self.voted_for is None or self.voted_for == candidate_id) and log_is_up_to_date:
            self.voted_for = candidate_id
            self.last_heartbeat = datetime.now()  # Reset election timeout
            print(f"[RAFT] Node {self.node_id} voting for Node {candidate_id} in term {term}")
            return {"term": self.current_term, "vote_granted": True}

        print(f"[RAFT] Node {self.node_id} rejecting vote: already voted for Node {self.voted_for}")
        return {"term": self.current_term, "vote_granted": False}

    def _check_commits(self):
        while True:
            time.sleep(0.1)
            if self.state == NodeState.LEADER:
                # Find highest N that majority of matchIndex[i] ≥ N
                for N in range(self.commit_index + 1, len(self.log) + 1):
                    if self.log[N-1].term == self.current_term:
                        match_count = 1  # Count self
                        for nid in CLUSTER_NODES:
                            if nid != self.node_id and self.match_index.get(nid, 0) >= N:
                                match_count += 1
                        if match_count > len(CLUSTER_NODES) // 2:
                            self.commit_index = N

            # Apply committed entries to state machine
            while self.last_applied < self.commit_index:
                self.last_applied += 1
                self._apply_log_entry(self.log[self.last_applied - 1])

    def _apply_log_entry(self, entry: LogEntry):
        """Apply a log entry to the state machine"""
        command = entry.command
        # Handle different command types
        if command.get("type") == "set_leader":
            from state import set_leader
            set_leader(command.get("leader_id"))
        elif command.get("type") == "replicate_file":
            self._handle_file_replication(command)

    def _handle_file_replication(self, command: dict):
        """Handle file replication commands"""
        filename = command.get("filename")
        file_data = command.get("data")
        if filename and file_data:
            from state import CACHE_DIR
            import os
            filepath = os.path.join(CACHE_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(file_data.encode())

    def append_command(self, command: dict) -> bool:
        """Append a new command to the log if leader"""
        if self.state != NodeState.LEADER:
            return False
        
        entry = LogEntry(self.current_term, command, len(self.log) + 1)
        self.log.append(entry)
        return True 

    def get_active_nodes(self):
        """Return set of currently active node IDs"""
        active = {self.node_id}  # Include self
        for nid, port in CLUSTER_NODES.items():
            if nid == self.node_id:
                continue
            try:
                response = requests.get(f"http://localhost:{port}/health", timeout=0.1)
                if response.status_code == 200:
                    active.add(nid)
            except:
                continue
        return active 