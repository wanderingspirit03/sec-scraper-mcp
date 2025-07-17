"""
Improved version of the FastMCP SEC scraper
- Robust XBRL URL extraction (instance document prioritization)
- Optional `count` arg for latest annual filings
- XBRL-to-JSON converter integration (optimized summary)
- Insider‑trading, Institutional‑holders, and Executive‑compensation tools added
- Shared POST/GET helpers to reduce duplication
- Caching, type hints, clear error handling remain
TODO:
- Convert to async/await
- Shared httpx.AsyncClient
"""

# ---------------------------------------------------------------------------#
#  SEC‑Driven MCP Assistant – bootstrap (FastMCP 2.3)                        #
# ---------------------------------------------------------------------------#

import os
from dotenv import load_dotenv
from fastmcp import FastMCP
import httpx
from sec_api import ExtractorApi
import json
from functools import lru_cache
from typing import Dict, Any, Optional, List, Tuple 

# ---------------------------------------------------------------------------
# Load env and set up constants
# ---------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, ".env"))

SEC_API_KEY = os.getenv("SEC_API_IO_KEY")
if not SEC_API_KEY:
    raise EnvironmentError("SEC_API_IO_KEY missing in .env")

API_HOST = "https://api.sec-api.io"
HEADERS = {
    "Authorization": SEC_API_KEY,
    "User-Agent": "FastMCP-Scraper/2.3.0"
}

# ---------------------------------------------------------------------------
# Create server instance with system instructions
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTIONS = """
Core Operating Procedure (SOP)
You are a financial research assistant. When presented with a user request, you must follow this three-step process:

1. Deconstruct: Break down the user's query into a series of smaller, answerable questions. Identify the specific pieces of information needed (e.g., revenue, risk factors, insider trades, institutional ownership).

2. Execute & Gather: Call the necessary tools in a logical sequence to gather the required data. You must chain tools together. For example, never assume you have a CIK or XBRL URL; always call the appropriate tool to find it first if needed.

3. Synthesize & Report: Once all data is gathered, synthesize it into a coherent, well-structured report for the user. Do not simply output raw data. Structure your answers under clear headings and provide a concluding summary.

Tool-Specific Guidelines & Workflows
Your primary value is in executing complex research workflows. Adhere to these patterns:

For a Full Company Analysis:
- Start by calling `get_latest_annual_filings` to get the most recent 10-K URL and, crucially, the XBRL URL.
- Use the XBRL URL to call `get_financial_snapshot` with a broad set of key metrics (e.g., "Revenues", "NetIncomeLoss", "Assets", "Liabilities").
- Use the HTML URL to call `extract_section_from_filing` for section 1A ("Risk Factors") and 7 ("Management's Discussion and Analysis").
- Call `get_insider_trades` and `get_institutional_holders` for the same ticker.
- Synthesize all of this data into a comprehensive overview covering Financial Performance, Key Risks, Insider Sentiment, and Institutional Confidence.

For Specific Financial Metrics (`extract_metric_from_section` or `get_financial_snapshot`):
- Use `extract_metric_from_section` for targeted, single-metric questions.
- Always use it with an XBRL URL obtained from `get_latest_annual_filings`.
- If a user asks for a metric like "Gross Profit", and it is not found, you are authorized to infer its composition (e.g., "Revenues" - "CostOfRevenue") and retrieve the component parts.

For Ownership Questions:
- When reporting on `get_institutional_holders`, you will receive manager CIKs. You must then use the `map_cik_to_name` tool on each CIK to provide the readable fund name in your final answer. This is a mandatory step for clarity.
- When asked about sentiment, you must combine the findings from both `get_insider_trades` and `get_institutional_holders`.

Caching & Efficiency:
- Be aware that some data is cached. Call `preload_xbrl_summary` on a new XBRL URL to efficiently warm the cache before making multiple calls to metric tools.

Answer Style & Formatting Mandates:
- Cite Everything: Every piece of data you present must be attributed to its source filing, including the `periodOfReport` or `filedAt` date.
- Structure Your Reports: Use Markdown headings (##, ###) and bullet points (*) to structure your answers. A typical report should have sections like:

    ## Financial Health  
    ## Key Risk Factors  
    ## Ownership Summary  
    ## Executive Compensation  

- Format Numbers Professionally:
  - For values over $1 billion, format as $XXX.XB (e.g., $123.4B).
  - For values over $1 million, format as $XXX.XM (e.g., $56.7M).
  - For all other values, use commas (e.g., $1,234,567).

- State Limitations: Be upfront about the data’s limitations. For example, “This analysis is based on the 13F filings for the quarter ending 2025-06-30...”

- Objective Tone: Maintain a neutral, objective, and analytical tone. Avoid speculation. Your answers are based on data, not opinion.

Your adherence to this protocol is paramount.
"""


mcp = FastMCP(
    "My SEC Analyst Assistant v2.3.0",
    instructions=SYSTEM_INSTRUCTIONS
)


# ---------------------------------
# Helper utilities
# ---------------------------------

def _full_url(partial: str) -> str:
    return partial if partial.startswith("http") else f"https://www.sec.gov{partial}"

@lru_cache(maxsize=1024)
def _get_company_identifiers(ticker: str) -> Dict[str, Any]:
    url = f"{API_HOST}/mapping/ticker/{ticker}?token={SEC_API_KEY}"
    with httpx.Client(headers=HEADERS, timeout=20) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    if isinstance(data, list) and data:
        return data[0]
    raise ValueError(f"Ticker {ticker} not found in SEC mapping API")

# ── Cached filing‑section fetcher ────────────────────────────────────────────
from functools import lru_cache

@lru_cache(maxsize=256)
def _fetch_filing_section(filing_url: str, section: str) -> str:
    """
    One SEC‑API hit per unique (filing_url, section) pair.
    Subsequent calls are served from in‑process cache.
    """
    extractor = ExtractorApi(api_key=SEC_API_KEY)
    return extractor.get_section(
        filing_url=filing_url,
        section=section,
        return_type="text"
    ) or ""


# ── XBRL caching ─────────────────────────────────────────────────────────────
from functools import lru_cache

@lru_cache(maxsize=128)
def _fetch_xbrl_json(xbrl_url: str) -> Dict[str, Any]:
    """
    One‑time download & parse of an XBRL instance document.
    Subsequent calls with the same URL are served from cache (no SEC credits).
    """
    params = {"xbrl-url": xbrl_url, "token": SEC_API_KEY}
    resp = httpx.get(f"{API_HOST}/xbrl-to-json", params=params, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()

def _lookup_tag_any_section(data: Dict[str, Any], tag: str) -> Optional[tuple]:
    """
    Search every section for `tag`.  Returns (section_name, value) or None.
    """
    for section_name, section_data in data.items():
        if tag in section_data:
            value = section_data[tag][0].get("value")
            return section_name, value
    return None


# ── Generic HTTP helpers ──────────────────────────────────────────────────────

def _sec_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{API_HOST}{endpoint}?token={SEC_API_KEY}"
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

def _sec_get(endpoint: str) -> Dict[str, Any]:
    url = f"{API_HOST}{endpoint}?token={SEC_API_KEY}"
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()

def _date_range(start: Optional[str], end: Optional[str]) -> Optional[str]:
    if start and end:
        return f"[{start} TO {end}]"
    if start:
        return f"[{start} TO *]"
    if end:
        return f"[* TO {end}]"
    return None

# ── NEW: Resolve CIK to Entity Name ───────────────────────────────────────────

from functools import lru_cache

@lru_cache(maxsize=2048)
def resolve_cik_name(cik: str) -> str:
    """
    Resolve a CIK to its official entity name using SEC‑API’s Mapping endpoint.

    • Pads the CIK to 10 digits (required by the API).
    • Caches results so repeated look‑ups are instant.
    • Falls back to the raw CIK string if the name is unavailable
      or the request fails for any reason.
    """
    padded = cik.zfill(10)           # ensure 10‑digit CIK (e.g. '924171' → '0000924171')
    try:
        result = _sec_get(f"/mapping/cik/{padded}")
        if result and isinstance(result, list) and result[0].get("name"):
            return result[0]["name"]
    except Exception:
        pass
    return cik  # graceful fallback


# ---------------------------------
# MCP Tools – mapping
# ---------------------------------

@mcp.tool()
def map_cik_to_name(cik: str) -> str:
    """
    MCP tool • Convert a CIK to its entity name.

    Example:
        map_cik_to_name("924171")  →  "CIK 924171 → BlackRock Fund Advisors"
    """
    name = resolve_cik_name(str(cik))
    return f"CIK {cik} → {name}"

@mcp.tool()
def get_latest_annual_filings(ticker: str, count: int = 5) -> str:
    """Return metadata for the latest *count* 10-K filings incl. XBRL instance URLs."""
    try:
        company = _get_company_identifiers(ticker)
        cik = company["cik"]

        query = {
            "query": {"query_string": {"query": f"cik:{cik} AND formType:\"10-K\""}},
            "from": "0",
            "size": str(count),
            "sort": [{"filedAt": {"order": "desc"}}],
        }

        with httpx.Client(headers=HEADERS, timeout=30) as client:
            resp = client.post(f"{API_HOST}?token={SEC_API_KEY}", json=query)
            resp.raise_for_status()
            filings = resp.json().get("filings", [])

        if not filings:
            return f"No recent 10-K filings found for {ticker} (CIK {cik})."

        lines: List[str] = [f"Found {len(filings)} 10-K filings for {ticker} (CIK {cik}):\n"]
        for filing in filings:
            filed_at = filing.get("filedAt", "N/A")[:10]
            html_link = filing.get("linkToFilingDetails", "N/A")
            xbrl_url: Optional[str] = filing.get("linkToXbrl") or filing.get("linkToXBRL")

            # fallback: brute-force search instance document
            if not xbrl_url:
                for df in filing.get("dataFiles", []):
                    desc = df.get("description", "").lower()
                    doc_type = df.get("documentType", "").upper()
                    url_lower = df.get("documentUrl", "").lower()
                    if (
                        "extracted xbrl instance document" in desc
                        or doc_type == "EX-101.INS"
                        or (url_lower.endswith(".xml") and not any(s in url_lower for s in ["_cal", "_def", "_lab", "_pre"]))
                    ):
                        xbrl_url = _full_url(df.get("documentUrl", ""))
                        break

            lines.append(f"• {filed_at} → HTML: {html_link}  |  XBRL: {xbrl_url or '⚠️ not found'}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error while fetching filings: {e}"
    # ── Canonicalise XBRL URL ────────────────────────────────────────────────────
def _canonical_xbrl_url(url: str) -> str:
    """
    Strip query‑strings / fragments, force lowercase, so cache keys are stable.
    """
    clean = url.split("?")[0].split("#")[0]
    return clean.lower()


# ── Cached XBRL JSON download ───────────────────────────────────────────────
from functools import lru_cache

@lru_cache(maxsize=128)
def _fetch_xbrl_json(xbrl_url: str) -> Dict[str, Any]:
    """
    One real SEC‑API hit per unique XBRL instance URL; everything else served
    from in‑process cache.  Uses canonical URL so variants map to the same key.
    """
    url = _canonical_xbrl_url(xbrl_url)
    params = {"xbrl-url": url, "token": SEC_API_KEY}
    resp = httpx.get(
        f"{API_HOST}/xbrl-to-json",
        params=params,
        headers=HEADERS,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()

@lru_cache(maxsize=128)
def _cached_xbrl_summary(xbrl_url: str) -> str:
    """
    Returns a comma‑separated list of section names for this filing.
    """
    data = _fetch_xbrl_json(xbrl_url)  # already cached at JSON level
    return f"Loaded XBRL. Sections available: {', '.join(data.keys())[:400]}"




@mcp.tool()
def extract_metric_from_section(
    xbrl_url: str,
    section: str,
    tag: str
) -> str:
    """
    Extract a specific financial metric by section and tag from an XBRL instance URL.
    Uses cached XBRL to avoid repeated SEC‑API calls.
    """
    # ---- guard against wrong URL type ----
    if not xbrl_url.lower().endswith(".xml"):
        return "Error: please supply the XBRL instance‑document (.xml) URL"

    # ---- load (or fetch & cache) XBRL ----
    try:
        data = _fetch_xbrl_json(xbrl_url)   # one real download per unique URL
    except Exception as e:
        return f"Failed to load XBRL: {e}"

    # ---- look up section / tag ----
    if section not in data:
        return f"Section '{section}' not found in the filing."

    section_data = data[section]

    if tag not in section_data:
        available = list(section_data.keys())[:10]
        return (
            f"Metric '{tag}' not in section '{section}'. "
            f"Sample available metrics: {available}"
        )

    metric_entry = section_data[tag][0]
    value  = metric_entry.get("value")
    period = metric_entry.get("period", {}).get("endDate", "unknown date")

    if value is None:
        return f"Metric '{tag}' was found but has no value."

    return f"{tag} in {section} for period ending {period}: ${int(value):,}"


@mcp.tool()
def extract_section_from_filing(filing_url: str, section: str) -> str:
    """
    Returns a filing section (e.g. 'Financial Statements') with caching.
    """
    try:
        text = _fetch_filing_section(filing_url, section)
        if not text:
            return f"Section {section} not found in filing."
        return text if len(text) < 3900 else text[:3900] + "…"
    except Exception as e:
        return f"Error extracting section: {e}"
    
@mcp.tool()
def get_metric_smart(
    xbrl_url: str,
    tag: str,
    section_hint: Optional[str] = None
) -> str:
    """
    Efficient single‑metric lookup.
    1. loads cached XBRL JSON (no extra API hit),
    2. looks for `tag` in the hinted section if provided,
    3. otherwise scans all sections,
    4. falls back to extract_metric_from_section if still not found.
    """
    if not xbrl_url.lower().endswith(".xml"):
        return "Error: supply the XBRL instance (.xml) URL"

    try:
        data = _fetch_xbrl_json(xbrl_url)
    except Exception as e:
        return f"Failed to load XBRL: {e}"

    # ① try hinted section fast‑path
    if section_hint and section_hint in data and tag in data[section_hint]:
        value = data[section_hint][tag][0].get("value")
        period = data[section_hint][tag][0].get("period", {}).get("endDate", "unknown")
        return f"{tag} ({section_hint}) – {period}: ${int(value):,}"

    # ② scan all sections
    found = _lookup_tag_any_section(data, tag)
    if found:
        sec, val = found
        period = data[sec][tag][0].get("period", {}).get("endDate", "unknown")
        return f"{tag} ({sec}) – {period}: ${int(val):,}"

    # ③ final fallback (old extractor)
    return extract_metric_from_section(xbrl_url=xbrl_url, section=section_hint or "StatementsOfOperations", tag=tag)


@mcp.tool()
def get_financial_snapshot(
    xbrl_url: str,
    metrics: Dict[str, List[str]]  # e.g. {"BalanceSheets": ["Assets"], ...}
) -> Dict[str, Any]:
    """
    Pull many metrics at once.  If a tag isn’t found in the requested section,
    the tool scans *all* sections and returns the first match.
    """
    try:
        data = _fetch_xbrl_json(xbrl_url)
    except Exception as e:
        return {"error": f"Failed to load XBRL: {e}"}

    snapshot: Dict[str, Any] = {}

    for wanted_section, tags in metrics.items():
        for tag in tags:
            value = None
            actual_section = wanted_section

            # 1️⃣ try the requested section name verbatim
            sec_data = data.get(wanted_section, {})
            if tag in sec_data:
                value = sec_data[tag][0].get("value")

            # 2️⃣ fallback: scan all sections
            if value is None:
                for sec_name, sec_data in data.items():
                    if tag in sec_data:
                        value = sec_data[tag][0].get("value")
                        actual_section = sec_name
                        break

            snapshot.setdefault(actual_section, {})[tag] = value

    return snapshot

# ---------- NEW tools ----------

@mcp.tool()
def get_insider_trades(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trans_code: Optional[str] = None,
    max_results: int = 50
) -> str:
    """Return recent insider buy/sell transactions for *ticker*."""
    clauses: List[str] = [f"issuer.tradingSymbol:{ticker.upper()}"]
    if trans_code:
        clauses.append(f"nonDerivativeTable.transactions.coding.code:{trans_code}")
    if (rng := _date_range(start_date, end_date)):
        clauses.append(f"periodOfReport:{rng}")

    try:
        data = _sec_post(
            "/insider-trading",
            {
                "query": " AND ".join(clauses),
                "from": "0",
                "size": str(min(max_results, 50)),
                "sort": [{"filedAt": {"order": "desc"}}],
            },
        )
    except Exception as e:
        return f"Error contacting insider‑trading endpoint: {e}"

    txs: List[Dict[str, Any]] = data.get("transactions", [])
    if not txs:
        return f"No insider trades found for {ticker}."

    def _first_transaction(entry: Dict[str, Any]) -> Tuple[str, Optional[int], Optional[float]]:
        nd = entry.get("nonDerivativeTable", {}).get("transactions", [])
        if not nd:
            return "?", None, None
        tx = nd[0]
        code = tx.get("coding", {}).get("code", "?")
        shares = (
            tx.get("transactionShares", {}).get("value")
            or tx.get("amounts", {}).get("shares")
        )
        price = (
            tx.get("transactionPrice", {}).get("value")
            or tx.get("amounts", {}).get("pricePerShare")
        )
        return code, shares, price

    lines: List[str] = [f"Top {len(txs)} Form 4/5 transactions for {ticker}:"]
    for entry in txs:
        owner = entry.get("reportingOwner", {}).get("name", "—")
        date = entry.get("periodOfReport", "?")
        code, shares, price = _first_transaction(entry)
        share_txt = f"{shares:,}" if shares is not None else "?"
        price_txt = f"${price}" if price is not None else "?"
        lines.append(f"• {date}: {owner} {code} {share_txt} @ {price_txt}")
    return "\n".join(lines)

@mcp.tool()
def get_institutional_holders(
    ticker: str,
    quarter: Optional[str] = None,
    top_n: int = 20
) -> str:
    """Return top institutional holders for *ticker* in a 13F quarter with fund names."""
    query_str = f"holdings.ticker:{ticker.upper()}"
    if quarter:
        query_str += f" AND periodOfReport:{quarter}"

    try:
        res = _sec_post(
            "/form-13f/holdings",
            {
                "query": query_str,
                "from": "0",
                "size": "50",
                "sort": [{"filedAt": {"order": "desc"}}],
            },
        )
    except Exception as e:
        return f"Error contacting 13F holdings endpoint: {e}"

    filings = res.get("data", [])
    if not filings:
        return f"No 13F holdings found for {ticker}."

    target_period = quarter or filings[0].get("periodOfReport")
    same_q = [f for f in filings if f.get("periodOfReport") == target_period]

    aggregated: Dict[str, Tuple[int, int]] = {}
    for f in same_q:
        cik = str(f.get("cik", "unknown"))
        name = resolve_cik_name(cik)
        for h in (f.get("holdings", [])):
            if h.get("ticker") != ticker.upper():
                continue
            shares = h.get("shrsOrPrnAmt", {}).get("sshPrnamt", 0)
            value = h.get("value", 0)
            if name in aggregated:
                prev_sh, prev_val = aggregated[name]
                aggregated[name] = (prev_sh + shares, prev_val + value)
            else:
                aggregated[name] = (shares, value)

    if not aggregated:
        return f"Ticker {ticker} not held by any institution in {target_period}."

    sorted_rows = sorted(aggregated.items(), key=lambda x: x[1][1], reverse=True)[:top_n]
    lines = [f"Institutional holders of {ticker.upper()} — {target_period} (top {top_n}):"]
    for fund, (sh, val) in sorted_rows:
        lines.append(f"• {fund}: {sh:,} sh @ ${val/1e6:.1f} M")
    return "\n".join(lines)

@mcp.tool()
def get_executive_compensation(
    ticker: str,
    year: Optional[int] = None,
    top_n: int = 10
) -> str:
    try:
        data = _sec_get(f"/compensation/{ticker.upper()}")
    except Exception as e:
        return f"Error contacting compensation endpoint: {e}"

    if not data:
        return f"No compensation data found for {ticker}."

    if year is None:
        year = max(row["year"] for row in data)
    filtered = [row for row in data if row["year"] == year]
    filtered.sort(key=lambda r: r["total"], reverse=True)

    lines = [f"{ticker.upper()} — executive compensation {year} (top {top_n}):"]
    for rec in filtered[:top_n]:
        lines.append(f"• {rec['name']} ({rec['position']}): ${rec['total']:,}")
    return "\n".join(lines)

@mcp.tool()
def preload_xbrl_summary(xbrl_url: str) -> str:
    """
    Preloads an XBRL and returns its top‑level section list (cached).
    """
    try:
        return _cached_xbrl_summary(xbrl_url)
    except Exception as e:
        return f"Error preloading XBRL: {e}"



# ---------------------------------
# Entry‑point
# ---------------------------------
if __name__ == "__main__":
    mcp.run()
