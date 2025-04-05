import requests
from models import ClientRequest

# Node configuration
CLUSTER_NODES = {
    217: 8217,
    536: 8536,
    657: 8657,
    777: 8777,
    888: 8888
}

# Verify single leader exists
def verify_unique_leader():
    confirmed_leaders = set()
    for node_id, port in CLUSTER_NODES.items():
        try:
            res = requests.get(f"http://localhost:{port}/leader", timeout=2)
            data = res.json()
            leader_id = data.get("leader_id")
            if leader_id is not None:
                confirmed_leaders.add(leader_id)
        except:
            continue
    if len(confirmed_leaders) == 1:
        return list(confirmed_leaders)[0]
    print(f"[Client] Conflicting leader reports: {confirmed_leaders}")
    return None

# Find active leader node
def discover_current_leader():
    for node_id, port in CLUSTER_NODES.items():
        try:
            res = requests.get(f"http://localhost:{port}/leader", timeout=2)
            data = res.json()
            leader_id = data.get("leader_id")
            if leader_id is not None:
                leader_port = CLUSTER_NODES.get(leader_id)
                if leader_port:
                    health = requests.get(f"http://localhost:{leader_port}/health", timeout=2)
                    if health.status_code == 200:
                        print(f"[Client] Communicating with leader node {leader_id} on port {leader_port}.")
                        return leader_id, leader_port
        except Exception as e:
            print(f"[Debug] Could not reach node on port {port}: {e}")
    print("[Client] No leader found.")
    return None, None

# Compare cheapest cars between cities
def run_cheapest_lookup(leader_port):
    country = input("Enter country (e.g., CA): ").strip()
    city1 = input("Enter first city: ").strip()
    city2 = input("Enter second city: ").strip()
    make = input("Enter car make (e.g., Toyota): ").strip()
    model = input("Enter car model (e.g., Corolla): ").strip()

    payload = {
        "country": country,
        "city1": city1,
        "city2": city2,
        "make": make,
        "model": model
    }

    try:
        res = requests.post(f"http://localhost:{leader_port}/client", json=payload, timeout=5)
        data = res.json()

        if "error" in data:
            print(f"[Client] Error: {data['error']}. Leader is Node {data['leader_id']}")
        else:
            print(f"[Client] Cheapest cars found by leader Node {data['leader_id']}:")
            prices = {}
            for city, car in data["results"].items():
                if isinstance(car, dict):
                    price = car.get("price", "N/A")
                    title_parts = [str(car.get("year", "")), car.get("make", ""), car.get("model", "")]
                    title = " ".join(filter(None, title_parts)).strip()
                    title = title if title else "No title"
                    print(f"  {city}: ${price} - {title}")
                    prices[city] = price
                else:
                    print(f"  {city}: No cars found or malformed response.")

            if all(isinstance(prices.get(c), (int, float)) for c in [city1, city2]):
                better_city = city1 if prices[city1] < prices[city2] else city2
                print(f"[Client] Recommended purchase location: {better_city}")
    except Exception as e:
        print(f"[Client] Failed to contact leader: {e}")

# Compare price per km between cities
def run_arbitrage_lookup(leader_port):
    country = input("Enter country (e.g., CA): ").strip()
    city1 = input("Enter first city: ").strip()
    city2 = input("Enter second city: ").strip()
    make = input("Enter car make (e.g., Toyota): ").strip()
    model = input("Enter car model (e.g., Corolla): ").strip()

    payload = {
        "country": country,
        "city1": city1,
        "city2": city2,
        "make": make,
        "model": model
    }

    try:
        res = requests.post(f"http://localhost:{leader_port}/client", json=payload, timeout=5)
        data = res.json()

        if "error" in data:
            print(f"[Client] Error: {data['error']}. Leader is Node {data['leader_id']}")
        else:
            cars = data["results"]
            ratios = {}
            for city, car in cars.items():
                if car and car.get("price") and car.get("mileage"):
                    try:
                        price = float(car["price"])
                        mileage = float(car["mileage"])
                        if mileage > 0:
                            ratios[city] = price / mileage
                    except:
                        continue
            if len(ratios) == 2:
                better_city = min(ratios, key=ratios.get)
                print("[Client] Arbitrage ratios (price per km):")
                for city, ratio in ratios.items():
                    print(f"  {city}: ${ratio:.4f} per km")
                print(f"[Client] Recommended purchase location based on arbitrage: {better_city}")
            else:
                print("[Client] Not enough data to compute arbitrage.")
    except Exception as e:
        print(f"[Client] Failed to contact leader: {e}")

# Main client loop
def main():
    while True:
        leader_id, leader_port = discover_current_leader()
        if not leader_id:
            break

        print("\nChoose an option:")
        print("1. Cheapest vehicle comparison")
        print("2. Best arbitrage deal (price per km)")
        choice = input("Enter 1 or 2: ").strip()

        if choice == '1':
            run_cheapest_lookup(leader_port)
        elif choice == '2':
            run_arbitrage_lookup(leader_port)
        else:
            print("Invalid choice.")

        again = input("\nWould you like to search again? (y/n): ").strip().lower()
        if again != 'y':
            break

if __name__ == "__main__":
    main()