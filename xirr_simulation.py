"""Build an HTML simulator comparing two NIFTY 50 investing rules by XIRR.

1. Buy a fixed amount at the close on every trading day the P/E is below a threshold.
2. A monthly SIP on a fixed day of the month (run once for each of days 1-28). When
   that day isn't a trading day, it buys on the next one.

The simulation runs in the browser, so the page can be re-run with a different
number of simulations, P/E threshold, window lengths or seed. This script refreshes
the NSE data (see nifty_pe_chart.load_data) and embeds it in the page.

Usage:
    python xirr_simulation.py
"""

import argparse
import json
import math
import webbrowser
from datetime import date, datetime
from pathlib import Path

from nifty_pe_chart import PE_START, load_data

TEMPLATE = Path(__file__).parent / "templates" / "xirr_simulation.html"
PLACEHOLDER = "/*__NIFTY_DATA__*/"


def build_payload(df):
    df = df.dropna(subset=["close"])
    return {
        "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        "close": df["close"].round(2).tolist(),
        "pe": [None if math.isnan(v) else round(v, 2) for v in df["pe"]],
        "generated": datetime.now().strftime("%d %b %Y %H:%M"),
    }


def main():
    parser = argparse.ArgumentParser(description="Build the NIFTY P/E vs SIP XIRR simulator page.")
    parser.add_argument("--out", default="index.html",
                        help="Output HTML file (index.html so GitHub Pages serves it)")
    parser.add_argument("--refresh", action="store_true",
                        help="Ignore the cache and download everything again")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't open the page in the browser")
    args = parser.parse_args()

    df = load_data(PE_START, date.today(), args.refresh)
    if df.empty:
        raise SystemExit("No data available.")
    print(f"Loaded {len(df)} rows ({df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d})")

    template = TEMPLATE.read_text(encoding="utf-8")
    html = template.replace(PLACEHOLDER, json.dumps(build_payload(df), separators=(",", ":")))
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"Simulator written to {out}")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
