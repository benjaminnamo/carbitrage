# routes.py
import os
from fastapi import APIRouter, Request, UploadFile, File, Form
from config import CLUSTER_NODES
from models import FetchRequest, ClientRequest
from car_fetching import fetch_cars, save_to_csv
from state import NODE_ID, get_leader, set_leader, CACHE_DIR
from raft_instance import raft_node

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "node_id": NODE_ID}

@router.get("/leader")
def get_leader_route():
    return {"leader_id": get_leader(), "this_node": NODE_ID}

@router.post("/fetch")
def fetch(data: FetchRequest):
    cars = fetch_cars(
        country=data.country,
        city=data.city,
        make=data.make,
        model_keyword=data.model,
    )
    return {"num_cars": len(cars), "city": data.city, "model": data.model}

@router.post("/client")
def client_entry(data: ClientRequest):
    if NODE_ID != get_leader():
        return {"error": "This node is not the leader", "leader_id": get_leader()}

    cars1 = fetch_cars(data.country, data.city1, data.make, data.model)
    cars2 = fetch_cars(data.country, data.city2, data.make, data.model)

    return {
        "leader_id": get_leader(),
        "results": {
            data.city1: cars1,
            data.city2: cars2
        }
    }

@router.post("/set-leader")
async def set_leader_route(request: Request):
    body = await request.json()
    new_leader = body.get("leader_id")
    set_leader(new_leader)
    print(f"[Leader Update] New leader set to Node {new_leader}")
    return {"message": f"Leader updated to {new_leader}"}


@router.post("/replicate")
async def replicate_cache(file: UploadFile = File(...), filename: str = Form(...)):
    try:
        contents = await file.read()
        os.makedirs(CACHE_DIR, exist_ok=True)
        filepath = os.path.join(CACHE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(contents)

        print(f"[Replication] Saved replicated cache to {filepath}")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/list-cache")
def list_cache_files():
    files = [f for f in os.listdir(CACHE_DIR) if f.endswith(".csv")]
    return {"files": files}

@router.get("/get-cache-file")
def get_cache_file(filename: str):
    from fastapi.responses import FileResponse
    filepath = os.path.join(CACHE_DIR, filename)
    if os.path.exists(filepath):
        return FileResponse(filepath, media_type='text/csv', filename=filename)
    return {"error": "File not found"}, 404

@router.get("/cache-meta")
def get_cache_meta(filename: str):
    filepath = os.path.join(CACHE_DIR, filename)
    if os.path.exists(filepath):
        return {"filename": filename, "mtime": os.path.getmtime(filepath)}
    return {"error": "File not found"}, 404

@router.post("/reconcile")
async def reconcile_route(request: Request):
    import requests
    from fastapi.responses import JSONResponse

    if NODE_ID != get_leader():
        return {"error": "Only the leader can perform reconciliation."}

    leader_files = {
        f: os.path.getmtime(os.path.join(CACHE_DIR, f))
        for f in os.listdir(CACHE_DIR)
        if f.endswith(".csv")
    }

    updates = []

    for nid, port in CLUSTER_NODES.items():
        if nid == NODE_ID:
            continue

        try:
            health = requests.get(f"http://localhost:{port}/health", timeout=2)
            if health.status_code != 200:
                print(f"[Reconcile Skipped] Node {nid} is not healthy.")
                continue
        except Exception:
            print(f"[Reconcile Skipped] Node {nid} is offline.")
            continue

        try:
            res = requests.get(f"http://localhost:{port}/list-cache", timeout=5)
            their_files = res.json().get("files", [])

            for fname in their_files:
                meta_res = requests.get(f"http://localhost:{port}/cache-meta", params={"filename": fname}, timeout=5)
                if meta_res.status_code != 200:
                    continue
                meta_json = meta_res.json()
                if "mtime" not in meta_json:
                    continue

                their_mtime = float(meta_json["mtime"])
                our_mtime = leader_files.get(fname, 0)

                if their_mtime > our_mtime:
                    file_data = requests.get(f"http://localhost:{port}/get-cache-file", params={"filename": fname}, timeout=10)
                    if file_data.status_code == 200:
                        with open(os.path.join(CACHE_DIR, fname), "wb") as f:
                            f.write(file_data.content)
                        updates.append(fname)
                        print(f"[Reconcile] Pulled newer {fname} from Node {nid}")
        except Exception as e:
            print(f"[Reconcile] Error processing file from Node {nid}: {e}")

    return JSONResponse({"status": "ok", "updated": updates})

@router.post("/raft/append_entries")
async def append_entries(request: Request):
    data = await request.json()
    return raft_node.handle_append_entries(data)

@router.post("/raft/request_vote")
async def request_vote(request: Request):
    data = await request.json()
    return raft_node.handle_request_vote(data)
