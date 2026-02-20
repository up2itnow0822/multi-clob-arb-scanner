# Multi-CLOB Arb Scanner

> **Independent multi-CLOB arbitrage scanner for prediction markets.**
> Works with Polymarket today. Add your Kalshi API key to unlock full cross-CLOB scanning.
> Built after Polymarket acquired Dome — because the community deserves neutral infrastructure.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## Why This Exists

In February 2026, Polymarket acquired **Dome** — the only neutral aggregator that unified
Kalshi and Polymarket orderbooks into a single view. Every independent arb bot builder
lost their infrastructure overnight.

This project is the open-source replacement: a lightweight, self-hosted scanner that you
control. No middlemen. No vendor lock-in. Add your own keys, run your own scans.

---

## What It Does

Scans for **pricing divergences** between prediction market platforms on the same underlying event.

**The arb logic:**
- If Polymarket says "Biden wins: 55¢" and Kalshi says "Biden wins: 45¢"
- Buy YES on Kalshi (45¢) + NO on Polymarket (45¢) = 90¢ total cost
- Either outcome pays $1.00 → **guaranteed 10¢ profit per $1 invested**

```
MULTI-CLOB ARB SCANNER  |  Polymarket + Kalshi  |  v1.0.0

🔍 Scanning: 'bitcoin'
   Polymarket: 47 markets  |  Kalshi: 31 markets

🎯 3 Opportunities Found

Event                                                PM YES  KL YES   Spread  Profit%    Cost
────────────────────────────────────────────────────────────────────────────────────────────
Will Bitcoin exceed $100k before March 2026?         0.430   0.550    12.0%    13.6%   0.880
Will Bitcoin ETF inflows exceed $1B this week?       0.680   0.590     9.0%     9.9%   0.910
Bitcoin above $95k on Feb 28 close?                  0.510   0.450     6.0%     6.4%   0.940
```

---

## Platforms Supported

| Platform    | Status    | Auth Required | Notes                                      |
|-------------|-----------|---------------|--------------------------------------------|
| Polymarket  | ✅ Live   | No            | Public Gamma + CLOB APIs                   |
| Kalshi      | 🔧 Ready  | Yes (RSA key) | Bring your own API key — see setup below   |
| Novig       | 🗓 Planned | TBD           | CFTC-licensed, API in development          |
| Manifold    | 🗓 Planned | No            | Open API, adding soon                      |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/up2itnow/multi-clob-arb-scanner.git
cd multi-clob-arb-scanner

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run (Polymarket-only — no key needed)
python arb_scanner.py

# 4. Custom keywords
python arb_scanner.py --keywords "bitcoin" "fed rate" "election"

# 5. JSON output (pipe to jq, save to file, etc.)
python arb_scanner.py --output json | jq '.[] | select(.spread_pct > 5)'

# 6. Adjust minimum spread threshold
python arb_scanner.py --threshold 5.0
```

---

## Enabling Kalshi

Kalshi requires RSA-signed API requests. Setup:

1. Create a Kalshi account at [kalshi.com](https://kalshi.com)
2. Generate an API key in **Settings → API Keys**
3. Download your RSA private key (`.pem` file)
4. Copy `config.example.yml` → `config.yml` and fill in:

```yaml
kalshi:
  enabled: true
  api_key_id: "your-key-id-here"
  private_key_path: "/path/to/your/private.pem"
```

Or use environment variables:
```bash
export KALSHI_API_KEY_ID="your-key-id"
export KALSHI_PRIVATE_KEY_PATH="/path/to/private.pem"
python arb_scanner.py
```

> **Demo mode:** Add `--demo` flag to use Kalshi's paper-trading environment (free, no real money).

---

## Configuration

Copy and edit the example config:

```bash
cp config.example.yml config.yml
```

See [config.example.yml](config.example.yml) for all options with comments.

---

## Architecture

```
arb_scanner.py
├── PolymarketClient     — Fetches from Gamma API (no auth)
├── KalshiClient         — Fetches from Kalshi REST API (RSA auth)
├── find_arb_opportunities() — Cross-matches markets, calculates spreads
├── load_config()        — YAML config + env var overrides
└── CLI (argparse)       — --keywords, --threshold, --output, --config
```

**Market matching** uses keyword-overlap heuristics (3+ shared non-stop-words).
Community improvements welcome — embedding-based matching, slug cross-references,
or a manual mapping table would all increase accuracy.

---

## Caveats & Risks

This scanner identifies **theoretical** arbitrage opportunities. Real execution requires:

- **Speed:** Both sides must be placed simultaneously before prices move
- **Fees:** Polymarket charges ~2% taker fee; Kalshi ~7% (varies by market)
- **Liquidity:** Quoted prices may not be available at the size you want
- **Transfer friction:** Cross-platform deposits/withdrawals take time (and may close the window)
- **Matching accuracy:** The keyword heuristic may false-match unrelated events

**Always verify manually before trading.**

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to:
- Add a new prediction market venue
- Improve market matching
- Add WebSocket real-time feeds

---

## Roadmap

- [ ] Kalshi RSA auth implementation (scaffolded — help wanted!)
- [ ] WebSocket real-time spread monitoring
- [ ] Novig integration (CFTC-licensed, API coming)
- [ ] Manifold Markets integration (open API)
- [ ] Persistent opportunity logging (SQLite)
- [ ] Telegram / Discord alerting on spread detection
- [ ] Auto-execution via [Agent Wallet SDK](https://github.com/up2itnow/agent-wallet-sdk)
- [ ] Embedding-based market matching (OpenAI / local model)
- [ ] Fee-adjusted profit calculations

---

## License

MIT — see [LICENSE](LICENSE)

---

## Acknowledgements

Inspired by the now-shuttered Dome aggregator. Built for the prediction market community.
