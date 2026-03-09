import json
import os


SCENARIOS_DIR = "scenarios_data"


def _ensure_scenarios_dir():
    if not os.path.exists(SCENARIOS_DIR):
        os.makedirs(SCENARIOS_DIR)


def scenarios_file(user_id):
    _ensure_scenarios_dir()
    return os.path.join(SCENARIOS_DIR, f"user_{user_id}_scenarios.json")


def load_scenarios_data(user_id):
    path = scenarios_file(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[scenarios_store] load error for {user_id}: {e}")
    return {}


def save_scenarios_data(user_id, data):
    path = scenarios_file(user_id)
    try:
        with open(path, "w") as f:
            json.dump(data or {}, f, indent=2)
        return True
    except Exception as e:
        print(f"[scenarios_store] save error for {user_id}: {e}")
        return False
