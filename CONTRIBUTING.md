# Contributing to Multi-CLOB Arb Scanner

Thanks for helping build independent prediction market infrastructure! This guide covers the most
common contribution paths.

---

## 🔑 Most Wanted: Kalshi RSA Auth

The highest-impact contribution right now is completing Kalshi authentication.

**What's needed:**
```python
# In KalshiClient._setup_auth() — implement RSA-PSS request signing
# Kalshi docs: https://docs.kalshi.com/api-v2/authentication

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64, time

def _sign_request(self, method: str, path: str, body: str = "") -> dict:
    """
    Return auth headers for a Kalshi API request.
    
    Required headers:
        KALSHI-ACCESS-KEY:        self.api_key_id
        KALSHI-ACCESS-TIMESTAMP:  current UTC timestamp in milliseconds
        KALSHI-ACCESS-SIGNATURE:  base64(RSA_PSS_SHA256(private_key, message))
    
    where message = timestamp + method.upper() + path + body
    """
    # TODO: load private key, sign, return headers dict
    pass
```

Reference implementation: [AndrewNolte/KalshiPythonClient](https://github.com/AndrewNolte/KalshiPythonClient)

---

## ➕ Adding a New Prediction Market Venue

The scanner is designed to be extended. Here's the pattern for adding a new platform:

### 1. Create a client class

```python
class NovigsClient:
    """
    Fetches markets from Novig's API.
    
    Novig is a CFTC-licensed prediction market exchange.
    API docs: https://novig.com/api (when available)
    """

    BASE_URL = "https://api.novig.com/v1"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 10):
        self.api_key = api_key or os.environ.get("NOVIG_API_KEY")
        self.timeout = timeout
        self.session = requests.Session()
        # Add auth header if key provided
        if self.api_key:
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    def fetch_markets(self, keyword: str, limit: int = 50) -> list[MarketPrice]:
        """
        Query Novig for open markets matching keyword.
        Returns normalised MarketPrice list (yes_price and no_price in 0.0–1.0).
        """
        # TODO: implement
        ...
```

### 2. Add to `run_scan()`

```python
novig_client = NovigsClient(api_key=config.get("novig", {}).get("api_key"))
novig_markets = novig_client.fetch_markets(keyword)
```

### 3. Extend `find_arb_opportunities()` or call it per pair

```python
# Polymarket vs Novig
poly_novig_opps = find_arb_opportunities(poly_markets, novig_markets, ...)

# Kalshi vs Novig  
kalshi_novig_opps = find_arb_opportunities(kalshi_markets, novig_markets, ...)
```

### 4. Add config keys to `config.example.yml`

```yaml
novig:
  enabled: true
  api_key: ""   # Get at novig.com/developers
```

---

## 🧠 Improving Market Matching

Current matching uses word-overlap (≥3 shared non-stop-words). This is a starting point.

Better approaches:

### Option A: Slug/ticker mapping table

Create `mapping.json`:
```json
{
  "polymarket:will-bitcoin-hit-100k-by-2025": "kalshi:BTC-100K-25",
  "polymarket:fed-rate-cut-march": "kalshi:FOMC-MAR25"
}
```

### Option B: Semantic similarity (embeddings)

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")  # 80MB, runs locally

def semantic_match(pm_title: str, km_title: str, threshold: float = 0.80) -> bool:
    embeddings = model.encode([pm_title, km_title])
    similarity = np.dot(embeddings[0], embeddings[1]) / (
        np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
    )
    return similarity >= threshold
```

---

## 📡 Adding Real-Time WebSocket Feeds

For live spread monitoring instead of periodic polling:

```python
import websockets
import asyncio

async def watch_polymarket_prices(slug: str):
    uri = f"wss://ws-subscriptions-clob.polymarket.com/ws/market"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "subscribe", "markets": [slug]}))
        async for message in ws:
            data = json.loads(message)
            # yield price updates
```

---

## Development Setup

```bash
git clone https://github.com/up2itnow/multi-clob-arb-scanner.git
cd multi-clob-arb-scanner
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run tests
python -m pytest tests/        # (tests coming soon — PRs welcome)

# Run scanner in demo mode
python arb_scanner.py --demo
```

---

## Pull Request Guidelines

1. **One feature per PR** — keep diffs focused
2. **Add docstrings** to any new classes/functions
3. **No secrets in code** — use env vars or config.yml (gitignored)
4. **Test your change** — manual run with `python arb_scanner.py` is fine for now
5. **Update README** if you add a new platform or config option

---

## Questions?

Open a GitHub Issue. We're friendly.
