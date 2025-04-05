import os
import csv
import time
import requests
from datetime import datetime, timedelta
from config import API_KEY, BASE_URL, HEADERS
from state import CACHE_DIR, NODE_ID, CLUSTER_NODES
from raft_instance import raft_node

os.makedirs(CACHE_DIR, exist_ok=True)

# Check if cached file is recent
def is_recent(file_path, hours=24):
    if not os.path.exists(file_path):
        return False
    modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
    return datetime.now() - modified_time < timedelta(hours=hours)

# Fetch car listings from API
def fetch_cars(country, city, make, model_keyword, max_cars=500, rows_per_request=50):
    filename = f"{make.lower()}_{model_keyword.lower()}_{city.lower()}.csv"
    filepath = os.path.join(CACHE_DIR, filename)

    if is_recent(filepath):
        print(f"[Cache] Using cached data for {city} from '{filepath}'")
        return load_from_csv(filepath)

    cars = []
    start = 0
    params = {
        "api_key": API_KEY,
        "country": country,
        "city": city,
        "make": make,
        "rows": rows_per_request,
    }

    while start < max_cars:
        params["start"] = start
        try:
            res = requests.get(BASE_URL, headers=HEADERS, params=params)
            res.raise_for_status()
            data = res.json()
            listings = data.get("listings", [])
            if not listings:
                break

            for listing in listings:
                build = listing.get("build", {})
                dealer = listing.get("dealer", {})
                model = build.get("model", "")
                mileage = listing.get("miles")
                price = listing.get("price")

                if model and model_keyword.lower().replace("-", "") in model.lower().replace("-", ""):
                    if mileage is not None and mileage > 6213:
                        cars.append({
                            "year": build.get("year"),
                            "make": build.get("make"),
                            "model": model,
                            "price": price,
                            "mileage": mileage,
                            "location": f"{dealer.get('city')}, {dealer.get('state')}"
                        })

            start += rows_per_request
            time.sleep(0.2)
        except Exception as e:
            print(f"[Fetch Error] {e}")
            break

    save_to_csv(cars, filepath)
    replicate_to_followers(filepath, filename)
    return cars

# Replicate file to follower nodes
def replicate_to_followers(filepath, filename):
    try:
        with open(filepath, "rb") as f:
            file_data = f.read()
        
        # Use RAFT to replicate the file
        raft_node.append_command({
            "type": "replicate_file",
            "filename": filename,
            "data": file_data.decode()
        })
        
    except Exception as e:
        print(f"[Replication Error] Failed to replicate file '{filename}': {e}")

# Sync all files to new node
def replicate_all_to_new_node(new_node_port):
    for fname in os.listdir(CACHE_DIR):
        fpath = os.path.join(CACHE_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "rb") as f:
                res = requests.post(
                    f"http://localhost:{new_node_port}/replicate",
                    files={"file": (fname, f.read())},
                    data={"filename": fname},
                    timeout=5
                )
                if res.status_code == 200:
                    print(f"[Sync] Sent '{fname}' to new node on port {new_node_port}")
        except Exception as e:
            print(f"[Sync Error] Sending '{fname}' to port {new_node_port}: {e}")

# Save cars to CSV
def save_to_csv(cars, filename):
    with open(filename, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=["year", "make", "model", "price", "mileage", "location"])
        writer.writeheader()
        writer.writerows(cars)

# Load cars from CSV
def load_from_csv(filename):
    cars = []
    with open(filename, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            row["year"] = int(row["year"]) if row["year"] else None
            row["price"] = float(row["price"]) if row["price"] else 0
            row["mileage"] = float(row["mileage"]) if row["mileage"] else 0
            cars.append(row)
    return cars
