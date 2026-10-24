"""Pull NIFTY 50 historic close and P/E from NSE and plot them with Plotly.

Usage:
    python nifty_pe_chart.py --start 2018-01-01 --end 2025-12-31

NSE publishes daily P/E for NIFTY 50 from 9 Nov 2015; earlier dates show price only.
"""

import argparse
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

API_URL = "https://www.nseindia.com/api/historicalOR"
ENDPOINTS = {"price": f"{API_URL}/indicesHistory", "pe": f"{API_URL}/indicesYield"}
INDEX_NAME = "NIFTY 50"
PE_START = date(2015, 11, 9)  # first day NSE has P/E data
CACHE_FILE = Path(__file__).parent / "data" / "nifty50.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports-indices-historical-index-data",
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_range(session, kind, start, end, retries=3):
    """Fetch one date range of 'price' or 'pe' data as a DataFrame.

    NSE returns at most ~70 rows per call, so keep ranges to about a quarter.
    """
    params = {"indexType": INDEX_NAME, "from": f"{start:%d-%m-%Y}", "to": f"{end:%d-%m-%Y}"}
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(ENDPOINTS[kind], params=params, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            if body.get("error"):
                raise ValueError(body.get("showMessage", "NSE returned an error"))
            return pd.DataFrame(body.get("data", []))
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries:
                raise RuntimeError(f"Failed to fetch {kind} {start}..{end}: {exc}") from exc
            time.sleep(2 * attempt)


def parse_price(df):
    if df.empty:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame({
        "date": pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y"),
        "close": pd.to_numeric(df["EOD_CLOSE_INDEX_VAL"], errors="coerce"),
    })


def parse_pe(df):
    if df.empty:
        return pd.DataFrame(columns=["date", "pe", "pb", "div_yield"])
    return pd.DataFrame({
        "date": pd.to_datetime(df["IY_DT"], format="%d-%b-%Y"),
        "pe": pd.to_numeric(df["IY_PE"], errors="coerce"),
        "pb": pd.to_numeric(df["IY_PB"], errors="coerce"),
        "div_yield": pd.to_numeric(df["IY_DY"], errors="coerce"),
    })


def quarters(start, end):
    """Yield (chunk_start, chunk_end) pairs of at most ~90 days covering start..end."""
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=89))
        yield chunk_start, chunk_end
        chunk_start = chunk_end + timedelta(days=1)


def download(start, end):
    """Download price and P/E a quarter at a time and merge on date."""
    session = make_session()
    prices, pes = [], []
    for chunk_start, chunk_end in quarters(start, end):
        print(f"Fetching {chunk_start} to {chunk_end} ...")
        prices.append(parse_price(fetch_range(session, "price", chunk_start, chunk_end)))
        if chunk_end >= PE_START:
            pes.append(parse_pe(fetch_range(session, "pe", chunk_start, chunk_end)))
        time.sleep(0.3)
    price = pd.concat(prices, ignore_index=True)
    pe = pd.concat(pes, ignore_index=True) if pes else parse_pe(pd.DataFrame())
    return price.merge(pe, on="date", how="outer")


def load_data(start, end, refresh=False):
    cached = pd.DataFrame()
    if CACHE_FILE.exists() and not refresh:
        cached = pd.read_csv(CACHE_FILE, parse_dates=["date"])

    if cached.empty:
        fresh = download(start, end)
    else:
        first, last = cached["date"].min().date(), cached["date"].max().date()
        parts = []
        if start < first:
            parts.append(download(start, first))
        if end > last:
            parts.append(download(last, end))
        fresh = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    df = pd.concat([cached, fresh], ignore_index=True)
    df = df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE_FILE, index=False)

    mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    return df.loc[mask].reset_index(drop=True)


def build_figure(df):
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=df["date"], y=df["close"], name="Close", mode="lines",
            line=dict(color="#2a6fdb", width=1.6),
            hovertemplate="Close: ₹%{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df["date"], y=df["pe"], name="P/E", mode="lines",
            line=dict(color="#e0752d", width=1.4),
            customdata=df[["pb", "div_yield"]],
            hovertemplate=(
                "P/E: %{y:.2f}<br>P/B: %{customdata[0]:.2f}"
                "<br>Div yield: %{customdata[1]:.2f}%<extra></extra>"
            ),
        ),
        secondary_y=True,
    )

    median_pe = df["pe"].median()
    if pd.notna(median_pe):
        fig.add_hline(
            y=median_pe, line_dash="dash", line_color="#e0752d", opacity=0.6,
            secondary_y=True,
        )
        fig.add_annotation(
            x=0, xref="paper", y=median_pe, yref="y2", text=f"Median P/E {median_pe:.1f}",
            showarrow=False, xanchor="left", yanchor="bottom", font=dict(color="#e0752d"),
            bgcolor="rgba(255,255,255,0.8)",
        )

    fig.update_layout(
        title=f"NIFTY 50: Daily Close and P/E "
              f"({df['date'].min():%d %b %Y} to {df['date'].max():%d %b %Y})",
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=60, t=90, b=40),
    )
    fig.update_xaxes(
        hoverformat="%d %b %Y",
        rangeslider=dict(visible=True),
        rangeselector=dict(buttons=[
            dict(count=1, label="1M", step="month", stepmode="backward"),
            dict(count=6, label="6M", step="month", stepmode="backward"),
            dict(count=1, label="YTD", step="year", stepmode="todate"),
            dict(count=1, label="1Y", step="year", stepmode="backward"),
            dict(count=5, label="5Y", step="year", stepmode="backward"),
            dict(count=10, label="10Y", step="year", stepmode="backward"),
            dict(step="all", label="All"),
        ]),
    )
    fig.update_yaxes(title_text="Close (₹)", tickformat=",", secondary_y=False)
    fig.update_yaxes(title_text="P/E", showgrid=False, tickformat=".1f", secondary_y=True)
    return fig


# Plotly doesn't rescale y-axes when the x-range changes (range buttons, slider, zoom),
# so refit both axes to the data visible in the new window.
AUTOSCALE_Y_JS = """
var gd = document.getElementById('{plot_id}');
// Keep the range-slider preview at full height (Python's API can't set yaxis2 here).
Plotly.relayout(gd, {
    'xaxis.rangeslider.yaxis.rangemode': 'auto',
    'xaxis.rangeslider.yaxis2.rangemode': 'auto',
});
function fit(trace, x0, x1) {
    var lo = Infinity, hi = -Infinity;
    for (var i = 0; i < trace.x.length; i++) {
        var t = new Date(trace.x[i]).getTime(), y = trace.y[i];
        if (t >= x0 && t <= x1 && y !== null && !isNaN(y)) {
            if (y < lo) lo = y;
            if (y > hi) hi = y;
        }
    }
    if (lo === Infinity) return null;
    var pad = (hi - lo) * 0.05 || 1;
    return [lo - pad, hi + pad];
}
gd.on('plotly_relayout', function (ev) {
    if (ev['yaxis.range'] || ev['yaxis.range[0]']) return;  // our own update
    var range = gd.layout.xaxis.range;
    var x0 = new Date(range[0]).getTime(), x1 = new Date(range[1]).getTime();
    var update = {};
    var y1 = fit(gd._fullData[0], x0, x1), y2 = fit(gd._fullData[1], x0, x1);  // _fullData has decoded arrays
    if (y1) update['yaxis.range'] = y1;
    if (y2) update['yaxis2.range'] = y2;
    if (Object.keys(update).length) Plotly.relayout(gd, update);
});
"""


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(description="Plot NIFTY 50 daily close and P/E.")
    parser.add_argument("--start", type=parse_date, default=PE_START,
                        help="Start date, YYYY-MM-DD (default 2015-11-09, first day with P/E)")
    parser.add_argument("--end", type=parse_date, default=date.today(),
                        help="End date, YYYY-MM-DD (default today)")
    parser.add_argument("--refresh", action="store_true",
                        help="Ignore the cache and download everything again")
    parser.add_argument("--out", default="nifty50_price_pe.html",
                        help="Output HTML file")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't open the chart in the browser")
    args = parser.parse_args()

    if args.start > args.end:
        parser.error("--start must be on or before --end")

    df = load_data(args.start, args.end, args.refresh)
    if df.empty:
        raise SystemExit("No data returned for that date range.")
    print(f"Loaded {len(df)} rows ({df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d})")

    fig = build_figure(df)
    fig.write_html(args.out, include_plotlyjs="cdn", post_script=AUTOSCALE_Y_JS,
                   auto_open=not args.no_open)
    print(f"Chart written to {args.out}")


if __name__ == "__main__":
    main()
