"""
Multi-CLOB Arbitrage Scanner
=============================
Scans for pricing divergences between Polymarket and Kalshi on the same
underlying prediction-market events.

When the same binary event trades at significantly different prices on two
platforms, a risk-free (or near risk-free) spread may exist: buy YES on the
cheaper platform and NO on the other. If both pay $1.00 on resolution, any
combined cost below $1.00 is locked-in profit.

History
-------
Built after Polymarket acquired Dome in February 2026, eliminating the
only neutral Kalshi+Polymarket aggregator. This project fills that gap as
a fully open-source, community-maintained replacement.

Platforms Supported
-------------------
- Polymarket  — Live (no API key required, public CLOB + Gamma APIs)
- Kalshi       — Scaffolded (bring your own API key; RSA auth required)

Usage
-----
    python arb_scanner.py                        # scan default keywords
    python arb_scanner.py --keywords "bitcoin"   # custom keyword
    python arb_scanner.py --config config.yml    # load from config file
    python arb_scanner.py --threshold 5.0        # min spread % to report
    python arb_scanner.py --output json          # output as JSON

Dependencies
------------
    pip install -r requirements.txt

Configuration
-------------
    Copy config.example.yml → config.yml and fill in your Kalshi API key.
    All thresholds, keywords, and output options are configurable there.

License: MIT
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import Optional

import requests
import yaml


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class MarketPrice:
    """Normalised price snapshot for a single binary market on one platform."""
    platform: str
    event_slug: str
    event_title: str
    yes_price: float   # 0.0 – 1.0  (probability implied)
    no_price: float    # 0.0 – 1.0
    volume: float      # total traded volume in USD


@dataclass
class ArbOpportunity:
    """
    A detected pricing divergence between Polymarket and Kalshi.

    Profit calculation
    ------------------
    Strategy: buy YES on the cheaper platform + NO on the other.

    Example:
        Polymarket YES = 0.55  →  buy Polymarket NO at 0.45
        Kalshi YES     = 0.45  →  buy Kalshi YES  at 0.45
        Total cost             = 0.90
        Payout (either side)   = 1.00
        Profit                 = 0.10 per $1 invested  (≈ 11%)

    Note: Does not account for fees, slippage, withdrawal delays, or
    cross-platform transfer friction. Always verify manually.
    """
    event_title: str
    poly_yes: float
    kalshi_yes: float
    spread_pct: float
    implied_profit_pct: float  # (1 - total_cost) / total_cost * 100
    cost_per_unit: float       # Total cost to capture 1 unit of arb


# ---------------------------------------------------------------------------
# Polymarket Client
# ---------------------------------------------------------------------------

class PolymarketClient:
    """
    Fetches markets from Polymarket's public APIs.

    No API key required.

    Endpoints used:
        Gamma API:  https://gamma-api.polymarket.com/markets
            — Market discovery, metadata, question text, outcome prices.
        CLOB API:   https://clob.polymarket.com
            — Order book data (used for precise bid/ask when needed).
    """

    GAMMA_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "multi-clob-arb-scanner/1.0"})

    def fetch_markets(self, keyword: str, limit: int = 50) -> list[MarketPrice]:
        """
        Query Gamma API for active markets matching *keyword*.

        Parameters
        ----------
        keyword : str
            Free-text search term (e.g. "bitcoin", "fed rate").
        limit : int
            Maximum markets to return per keyword.

        Returns
        -------
        list[MarketPrice]
            Normalised price snapshots; empty list on error.
        """
        try:
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "q": keyword,
            }
            r = self.session.get(self.GAMMA_URL, params=params, timeout=self.timeout)
            r.raise_for_status()
            markets = r.json()

            results = []
            for m in markets:
                if not m.get("outcomePrices"):
                    continue
                try:
                    prices = (
                        json.loads(m["outcomePrices"])
                        if isinstance(m["outcomePrices"], str)
                        else m["outcomePrices"]
                    )
                    yes_price = float(prices[0]) if prices else 0.5
                    no_price = float(prices[1]) if len(prices) > 1 else 1 - yes_price

                    results.append(MarketPrice(
                        platform="polymarket",
                        event_slug=m.get("slug", ""),
                        event_title=m.get("question", "Unknown")[:120],
                        yes_price=yes_price,
                        no_price=no_price,
                        volume=float(m.get("volume", 0)),
                    ))
                except (KeyError, ValueError, TypeError):
                    continue

            return results

        except requests.RequestException as e:
            print(f"[Polymarket] Request error: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"[Polymarket] Unexpected error: {e}", file=sys.stderr)
            return []


# ---------------------------------------------------------------------------
# Kalshi Client (scaffolded — bring your own API key)
# ---------------------------------------------------------------------------

class KalshiClient:
    """
    Fetches markets from Kalshi's REST API.

    Authentication
    --------------
    Kalshi uses RSA-signed requests. You must:
        1. Create an account at https://kalshi.com
        2. Generate an API key in your account settings
        3. Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH in config.yml
           (or set environment variables KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY)

    API Reference
    -------------
    Production:  https://api.kalshi.com/v1
    Demo:        https://demo-api.kalshi.co/v1  (paper trading, free)
    Docs:        https://docs.kalshi.com

    Key Endpoints (v1)
    ------------------
    GET /markets              — List open markets (auth required)
    GET /markets/{ticker}     — Single market detail
    GET /markets/{ticker}/orderbook  — Order book depth
    GET /portfolio/balance    — Account balance (auth required)
    GET /portfolio/positions  — Open positions (auth required)

    Kalshi prices are in CENTS (0–99). This client normalises to 0.0–1.0.

    TODO: Contributor notes
    -----------------------
    To enable Kalshi support:
        1. Install cryptography:  pip install cryptography
        2. Implement _sign_request() using RS256/RSA-PSS (see Kalshi docs)
        3. Pass the signed headers in self.session.headers
        4. Uncomment the live fetch logic in fetch_markets()

    We welcome PRs — see CONTRIBUTING.md.
    """

    PROD_URL  = "https://api.kalshi.com/v1"
    DEMO_URL  = "https://demo-api.kalshi.co/v1"

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        use_demo: bool = False,
        timeout: int = 10,
    ):
        """
        Parameters
        ----------
        api_key_id : str, optional
            Your Kalshi API key ID.
            TODO: Set via KALSHI_API_KEY_ID env var or config.yml.
        private_key_path : str, optional
            Path to your RSA private key PEM file.
            TODO: Set via KALSHI_PRIVATE_KEY_PATH env var or config.yml.
        use_demo : bool
            If True, use the demo environment (paper trading).
        """
        self.base_url = self.DEMO_URL if use_demo else self.PROD_URL
        self.api_key_id = api_key_id or os.environ.get("KALSHI_API_KEY_ID")
        self.private_key_path = private_key_path or os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "multi-clob-arb-scanner/1.0"})
        self._authenticated = False

        if self.api_key_id and self.private_key_path:
            self._setup_auth()

    def _setup_auth(self) -> None:
        """
        Configure RSA authentication headers.

        TODO: Implement RSA-PSS request signing.
        Kalshi requires each request to include:
            KALSHI-ACCESS-KEY:       your api_key_id
            KALSHI-ACCESS-TIMESTAMP: current UTC timestamp (ms)
            KALSHI-ACCESS-SIGNATURE: RSA-PSS(private_key, message)
                where message = timestamp + method + path + body_hash

        Reference implementation:
            https://github.com/AndrewNolte/KalshiPythonClient
        """
        # TODO: Load private key from self.private_key_path
        # TODO: Implement _sign_request() method
        # TODO: Add a requests.auth.AuthBase subclass or pre-request hook
        print("[Kalshi] TODO: RSA auth not yet implemented — contributions welcome!")
        self._authenticated = False

    def fetch_markets(self, keyword: str, limit: int = 50) -> list[MarketPrice]:
        """
        Query Kalshi for open markets matching *keyword*.

        Parameters
        ----------
        keyword : str
            Free-text search term.
        limit : int
            Max results to return.

        Returns
        -------
        list[MarketPrice]
            Normalised price snapshots; empty list if auth not configured.

        TODO: Once auth is implemented, this will live-fetch from Kalshi.
        Currently returns an empty list with an informational message.
        """
        if not self._authenticated:
            # Friendly message on first call only
            if not hasattr(self, "_warned"):
                self._warned = True
                print(
                    "[Kalshi] ⚠️  No API key configured. "
                    "Set KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH to enable Kalshi scanning.\n"
                    "         See config.example.yml and CONTRIBUTING.md for setup instructions."
                )
            return []

        # --- Live fetch (active once auth is implemented) ---
        try:
            params = {
                "status": "open",
                "limit": limit,
                "search": keyword,
            }
            r = self.session.get(
                f"{self.base_url}/markets",
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            markets = data.get("markets", [])

            results = []
            for m in markets:
                # Kalshi prices are in cents (0–99); normalise to 0.0–1.0
                yes_price = float(m.get("yes_bid", 50)) / 100
                no_price  = float(m.get("no_bid",  50)) / 100

                results.append(MarketPrice(
                    platform="kalshi",
                    event_slug=m.get("ticker", ""),
                    event_title=m.get("title", "Unknown")[:120],
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=float(m.get("volume", 0)),
                ))

            return results

        except requests.RequestException as e:
            print(f"[Kalshi] Request error: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"[Kalshi] Unexpected error: {e}", file=sys.stderr)
            return []


# ---------------------------------------------------------------------------
# Arb Detector
# ---------------------------------------------------------------------------

# Stop-words excluded from keyword-overlap matching
_STOP_WORDS = frozenset({
    "will", "the", "a", "an", "by", "in", "on", "to", "be", "of",
    "at", "or", "and", "is", "for", "that", "this", "from", "with",
    "are", "was", "has", "have", "had", "end", "before", "after",
})


def find_arb_opportunities(
    poly_markets: list[MarketPrice],
    kalshi_markets: list[MarketPrice],
    min_spread_pct: float = 3.0,
    min_word_overlap: int = 3,
) -> list[ArbOpportunity]:
    """
    Cross-match markets between platforms and identify pricing divergences.

    Matching heuristic
    ------------------
    Two markets are considered the same event if their titles share at least
    *min_word_overlap* non-stop-words. This is intentionally conservative —
    false positives (wrong pairings) are worse than false negatives.

    TODO (community): Improve matching with:
        - Slug/series ID cross-referencing
        - Embedding-based semantic similarity
        - Manual mapping table (mapping.json)

    Profit model
    ------------
    Buy the cheap YES + cheap NO across platforms:
        cost = cheap_yes + cheap_no   (where cheap_no = 1 - expensive_yes)
        profit_pct = (1 - cost) / cost * 100

    Parameters
    ----------
    poly_markets : list[MarketPrice]
    kalshi_markets : list[MarketPrice]
    min_spread_pct : float
        Minimum absolute YES-price spread (in %) to report.
    min_word_overlap : int
        Minimum shared non-stop-words required to consider two markets matched.

    Returns
    -------
    list[ArbOpportunity]
        Opportunities sorted by spread descending.
    """
    opportunities = []

    for pm in poly_markets:
        pm_words = {w for w in pm.event_title.lower().split() if w not in _STOP_WORDS}

        for km in kalshi_markets:
            km_words = {w for w in km.event_title.lower().split() if w not in _STOP_WORDS}
            common   = pm_words & km_words

            if len(common) < min_word_overlap:
                continue

            spread = abs(pm.yes_price - km.yes_price) * 100  # in %
            if spread < min_spread_pct:
                continue

            cheap_yes  = min(pm.yes_price, km.yes_price)
            cheap_no   = 1 - max(pm.yes_price, km.yes_price)
            total_cost = cheap_yes + cheap_no

            if total_cost >= 1.0:
                continue  # No profit after cost

            profit_pct = (1 - total_cost) / total_cost * 100

            opportunities.append(ArbOpportunity(
                event_title=pm.event_title,
                poly_yes=pm.yes_price,
                kalshi_yes=km.yes_price,
                spread_pct=spread,
                implied_profit_pct=profit_pct,
                cost_per_unit=total_cost,
            ))

    return sorted(opportunities, key=lambda x: x.spread_pct, reverse=True)


# ---------------------------------------------------------------------------
# Config Loader
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "keywords": ["bitcoin", "trump", "federal reserve", "election", "inflation"],
    "min_spread_pct": 3.0,
    "min_word_overlap": 3,
    "market_limit": 50,
    "output_format": "table",   # "table" | "json"
    "polymarket": {
        "enabled": True,
        "timeout": 10,
    },
    "kalshi": {
        "enabled": True,
        "use_demo": False,
        "timeout": 10,
        "api_key_id": None,          # TODO: add your Kalshi API key ID
        "private_key_path": None,    # TODO: path to your RSA private key PEM
    },
}


def load_config(path: Optional[str] = None) -> dict:
    """
    Load configuration from a YAML file, overlaying onto defaults.

    Parameters
    ----------
    path : str, optional
        Path to config.yml. Falls back to DEFAULT_CONFIG if not provided.
    """
    config = DEFAULT_CONFIG.copy()

    if path and os.path.exists(path):
        with open(path) as f:
            user_cfg = yaml.safe_load(f) or {}
        # Deep merge top-level keys
        for k, v in user_cfg.items():
            if isinstance(v, dict) and isinstance(config.get(k), dict):
                config[k] = {**config[k], **v}
            else:
                config[k] = v

    # Environment variable overrides
    if os.environ.get("KALSHI_API_KEY_ID"):
        config["kalshi"]["api_key_id"] = os.environ["KALSHI_API_KEY_ID"]
    if os.environ.get("KALSHI_PRIVATE_KEY_PATH"):
        config["kalshi"]["private_key_path"] = os.environ["KALSHI_PRIVATE_KEY_PATH"]

    return config


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------

def print_table(opportunities: list[ArbOpportunity]) -> None:
    """Render opportunities as a formatted terminal table."""
    if not opportunities:
        print("\n✅ No arb opportunities found above threshold.")
        print("   (If Kalshi is not configured, enable it to unlock cross-CLOB scanning.)")
        return

    hdr = f"\n🎯 {len(opportunities)} Opportunity{'s' if len(opportunities) != 1 else ''} Found\n"
    print(hdr)
    col = f"{'Event':<52} {'PM YES':>7} {'KL YES':>7} {'Spread':>8} {'Profit%':>8} {'Cost':>7}"
    print(col)
    print("─" * len(col))

    for opp in opportunities[:20]:
        print(
            f"{opp.event_title[:52]:<52} "
            f"{opp.poly_yes:>7.3f} "
            f"{opp.kalshi_yes:>7.3f} "
            f"{opp.spread_pct:>7.1f}% "
            f"{opp.implied_profit_pct:>7.1f}% "
            f"{opp.cost_per_unit:>7.3f}"
        )


def print_json(opportunities: list[ArbOpportunity]) -> None:
    """Render opportunities as JSON (suitable for piping to other tools)."""
    print(json.dumps([asdict(o) for o in opportunities], indent=2))


# ---------------------------------------------------------------------------
# Main Scanner
# ---------------------------------------------------------------------------

def run_scan(config: dict) -> list[ArbOpportunity]:
    """
    Execute a full scan across all configured platforms and keywords.

    Parameters
    ----------
    config : dict
        Merged configuration (from load_config()).

    Returns
    -------
    list[ArbOpportunity]
        All detected opportunities, sorted by spread descending.
    """
    poly_cfg   = config["polymarket"]
    kalshi_cfg = config["kalshi"]

    poly_client = PolymarketClient(timeout=poly_cfg.get("timeout", 10))
    kalshi_client = KalshiClient(
        api_key_id=kalshi_cfg.get("api_key_id"),
        private_key_path=kalshi_cfg.get("private_key_path"),
        use_demo=kalshi_cfg.get("use_demo", False),
        timeout=kalshi_cfg.get("timeout", 10),
    )

    banner = "=" * 72
    print(f"\n{banner}")
    print("  MULTI-CLOB ARB SCANNER  |  Polymarket + Kalshi  |  v1.0.0")
    print(f"  github.com/up2itnow/multi-clob-arb-scanner")
    print(banner)

    all_opps: list[ArbOpportunity] = []

    for keyword in config["keywords"]:
        print(f"\n🔍 Scanning: '{keyword}'")

        poly_markets   = poly_client.fetch_markets(keyword, limit=config["market_limit"]) \
                         if poly_cfg.get("enabled", True) else []
        kalshi_markets = kalshi_client.fetch_markets(keyword, limit=config["market_limit"]) \
                         if kalshi_cfg.get("enabled", True) else []

        print(f"   Polymarket: {len(poly_markets):3} markets  |  Kalshi: {len(kalshi_markets):3} markets")

        opps = find_arb_opportunities(
            poly_markets,
            kalshi_markets,
            min_spread_pct=config["min_spread_pct"],
            min_word_overlap=config["min_word_overlap"],
        )
        all_opps.extend(opps)

    all_opps.sort(key=lambda x: x.spread_pct, reverse=True)
    return all_opps


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-CLOB Arb Scanner — detect pricing divergences across prediction markets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yml",
        help="Path to YAML config file (default: config.yml)",
    )
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        help="Keywords to scan (overrides config)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        help="Minimum spread %% to report (overrides config)",
    )
    parser.add_argument(
        "--output", "-o",
        choices=["table", "json"],
        help="Output format (overrides config)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use Kalshi demo environment",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    if args.keywords:
        config["keywords"] = args.keywords
    if args.threshold is not None:
        config["min_spread_pct"] = args.threshold
    if args.output:
        config["output_format"] = args.output
    if args.demo:
        config["kalshi"]["use_demo"] = True

    opportunities = run_scan(config)

    fmt = config.get("output_format", "table")
    if fmt == "json":
        print_json(opportunities)
    else:
        print_table(opportunities)
        print()
        print("─" * 72)
        print("⚠️  Disclaimer: Spreads shown are theoretical. Real arb requires:")
        print("   • Fast execution on both platforms simultaneously")
        print("   • Accounting for taker fees (Polymarket ~2%, Kalshi ~7%)")
        print("   • Cross-platform withdrawal/deposit friction")
        print("   • Sufficient liquidity at quoted prices")
        print("─" * 72)
        print()


if __name__ == "__main__":
    main()
