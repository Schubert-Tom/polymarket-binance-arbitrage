from datetime import datetime, timezone
import requests
from py_clob_client.client import ClobClient

import json

def clean_json(obj):
    """Recursively fix API responses:
       - Parse strings that are JSON objects/arrays
       - Convert numeric strings to int/float
       - Convert 'true'/'false'/'null' to Python types
    """
    if isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json(v) for v in obj]
    elif isinstance(obj, str):
        s = obj.strip()

        # 1) Try parsing as JSON if it looks like JSON
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return clean_json(json.loads(s))
            except Exception:
                pass

        # 2) Handle booleans/null
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        if s.lower() == "null":
            return None

        # 3) Handle numbers
        if s.isdigit():
            return int(s)
        try:
            return float(s)
        except ValueError:
            return obj

    return obj


class PolyMarketInfo:
    """
    Api for fetching data and public market infos.
    No Interaction with the market only polling info
    """
    def __init__(self):
        self._client = ClobClient("https://clob.polymarket.com")  # read-only

    @staticmethod
    def get_markets(**kwargs):
        """
        doku https://docs.polymarket.com/developers/gamma-markets-api/get-markets
        """
        response = requests.get("https://gamma-api.polymarket.com/markets", params=kwargs)
        if response.status_code != 200:
            return {"error": response.text}

        return clean_json(response.json())

    @staticmethod
    def get_events(**kwargs):
        """
        doku https://docs.polymarket.com/developers/gamma-events-api/get-events
        """
        response = requests.get("https://gamma-api.polymarket.com/events", params=kwargs)
        if response.status_code != 200:
            return {"error": response.text}
        return clean_json(response.json())

    @property
    def client(self) -> ClobClient:
        return self._client
    
    @staticmethod
    def get_market_history(token_id, fidelity=1):
        """
        Get market history for a specific token ID.
        """
        response = requests.get(f"https://clob.polymarket.com/prices-history", params={"market": token_id, "interval": "max", "fidelity": fidelity})
        if response.status_code != 200:
            return {"error": response.text}

        return [dict({"ts": datetime.fromtimestamp(el["t"],  tz=timezone.utc), "midPointPrice": float(el["p"])}) for el in response.json()["history"]]

