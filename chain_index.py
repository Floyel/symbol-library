"""
chain_index.py
──────────────
Fetches all token data from the Symbol by Flōyél contract on Base mainnet
and saves it to chain_data.json in the same folder.

Run from your project folder:
    python chain_index.py

Options:
    python chain_index.py --rpc https://base-mainnet.g.alchemy.com/v2/YOUR_KEY
    python chain_index.py --delay 0.1   (seconds between requests, default 0.3)
    python chain_index.py --start 1     (resume from a specific token ID)

The public Base RPC works but is slow (~0.3s delay to avoid 429).
An Alchemy key makes it much faster (~0.05s delay).
"""

import json
import time
import sys
import os
import urllib.request
import argparse
from datetime import datetime, timezone

# ── CONFIG ──────────────────────────────────────────────────────────────────
CONTRACT     = "0xB881317390AbA4fA628C2235381D7838070125EC"
DEFAULT_RPC  = "https://mainnet.base.org"
OUTPUT_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chain_data.json")
SYMBOLS_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "symbols")
PLACEHOLDER  = "https://"   # unrevealed tokens return a URL
MAX_RETRIES  = 3
# ────────────────────────────────────────────────────────────────────────────

ELEMENT_MAP = {
    "ild": "△", "luft": "⌃", "vann": "▽", "jord": "▢",
    "plante": "✳", "lyn": "ϟ", "metall": "⌂", "tom": "·"
}


def rpc_call(rpc_url, method, params, retries=MAX_RETRIES):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": method, "params": params
    }).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                rpc_url, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.loads(r.read())
            if "error" in result:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return None
            return result.get("result")
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                wait = (attempt + 1) * 2
                print(f"\n  Rate limited — waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
            elif attempt < retries - 1:
                time.sleep(1)
            else:
                return None
    return None


def decode_string(hex_result):
    """Decode ABI-encoded string from eth_call result."""
    if not hex_result or hex_result == "0x":
        return ""
    try:
        data = bytes.fromhex(hex_result[2:])
        if len(data) < 64:
            return data.decode("utf-8", errors="replace").strip("\x00")
        str_len = int.from_bytes(data[32:64], "big")
        return data[64:64 + str_len].decode("utf-8", errors="replace")
    except Exception:
        return ""


def decode_address(hex_result):
    """Decode address from eth_call result."""
    if not hex_result or len(hex_result) < 42:
        return ""
    return "0x" + hex_result[-40:]


def decode_uint256(hex_result):
    """Decode uint256 from eth_call result."""
    if not hex_result or hex_result == "0x":
        return 0
    return int(hex_result, 16)


def call(rpc_url, fn_selector, arg_hex=""):
    data = fn_selector + arg_hex
    return rpc_call(rpc_url, "eth_call", [{"to": CONTRACT, "data": data}, "latest"])


def pad_uint(n):
    return hex(n)[2:].zfill(64)


def pad_address(addr):
    return addr[2:].zfill(64) if addr.startswith("0x") else addr.zfill(64)


def parse_effect_line(line):
    """Parse effect notation into structured dict (mirrors parser.py)."""
    import re
    line = (line or "").strip()
    if not line or line == "~":
        return None
    if line == "I":
        return {"type": "negative"}
    if line == "@G":
        return {"type": "glow", "pulse": True, "cycle": True}
    if line == "@F":
        return {"type": "filter", "pulse": True, "cycle": True}
    m = re.match(r"^\*([GF]):([RGBWCMY])$", line)
    if m:
        kind = "glow" if m.group(1) == "G" else "filter"
        return {"type": kind, "color": m.group(2), "pulse": True, "cycle": False}
    m = re.match(r"^※([GF])\[(\d+)\]$", line)
    if m:
        kind = "glow" if m.group(1) == "G" else "filter"
        key  = "radius" if kind == "glow" else "opacity"
        return {"type": kind, key: int(m.group(2)), "pulse": False, "cycle": True}
    m = re.match(r"^([GF]):([RGBWCMY])\[(\d+)\]$", line)
    if m:
        kind = "glow" if m.group(1) == "G" else "filter"
        key  = "radius" if kind == "glow" else "opacity"
        return {"type": kind, "color": m.group(2), key: int(m.group(3)),
                "pulse": False, "cycle": False}
    return None


def parse_metadata(raw):
    """Parse raw on-chain metadata string into structured dict."""
    lines = [l for l in raw.splitlines() if l.strip()]
    lines = [l for l in lines
             if not l.strip().startswith("===")
             and l.strip() != "---"           # skip solo separator lines only
             and not all(c in "-" for c in l.strip().replace(" ",""))]  # skip all-dash separator

    if not lines:
        return None

    import re
    file_name  = lines[0].strip() if len(lines) > 0 else ""
    generation = lines[1].strip() if len(lines) > 1 else ""
    chain      = lines[2].strip() if len(lines) > 2 else ""

    m = re.match(r"^(\d+) - (.+)\.gif$", file_name)
    number = m.group(1) if m else ""
    title  = m.group(2) if m else file_name

    # Grid lines until timestamp
    idx = 3
    grid_lines = []
    while idx < len(lines) and not lines[idx].strip().isdigit():
        grid_lines.append(lines[idx].strip())
        idx += 1

    timestamp = int(lines[idx].strip()) if idx < len(lines) else 0
    idx += 1

    if idx < len(lines) and lines[idx].strip() == "effects:":
        idx += 1

    glow_raw   = lines[idx].strip()   if idx     < len(lines) else "~"
    invert_raw = lines[idx+1].strip() if idx + 1 < len(lines) else "~"
    filt_raw   = lines[idx+2].strip() if idx + 2 < len(lines) else "~"

    effects = [e for e in [
        parse_effect_line(glow_raw),
        parse_effect_line(invert_raw),
        parse_effect_line(filt_raw)
    ] if e is not None]

    return {
        "number":     number,
        "title":      title,
        "generation": generation,
        "chain":      chain,
        "grid":       "|".join(grid_lines),
        "timestamp":  timestamp,
        "effects":    effects
    }


def find_symbol_folder(number):
    """Find the local symbol folder matching a token number."""
    if not os.path.isdir(SYMBOLS_DIR):
        return None, None
    for folder in os.listdir(SYMBOLS_DIR):
        if folder.startswith(number):
            folder_path = os.path.join(SYMBOLS_DIR, folder)
            if os.path.isdir(folder_path):
                gif = next((f for f in sorted(os.listdir(folder_path))
                            if f.lower().endswith(".gif") and not f.startswith("._")), None)
                return folder, gif
    return None, None


def main():
    parser = argparse.ArgumentParser(description="Build chain_data.json for Symbol library")
    parser.add_argument("--rpc",   default=DEFAULT_RPC, help="RPC endpoint URL")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests (seconds)")
    parser.add_argument("--start", type=int,   default=1,   help="Start from token ID")
    args = parser.parse_args()

    rpc_url = args.rpc
    delay   = args.delay

    print(f"\n  chain_index.py")
    print(f"  Contract : {CONTRACT}")
    print(f"  RPC      : {rpc_url}")
    print(f"  Delay    : {delay}s per request")
    print(f"  Output   : {OUTPUT_FILE}\n")

    # ── Get total minted ──
    print("  Fetching totalMinted()...", end="", flush=True)
    raw_total = call(rpc_url, "0xa2309ff8")
    total = decode_uint256(raw_total) if raw_total else 0
    if not total:
        print(" FAILED — check RPC and contract address")
        sys.exit(1)
    print(f" {total} tokens")

    # ── Load existing data if resuming ──
    existing = {}
    if args.start > 1 and os.path.isfile(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        for t in old.get("revealed", []):
            existing[t["tokenId"]] = t
        print(f"  Resuming from token {args.start}, "
              f"{len(existing)} tokens already indexed\n")

    revealed    = list(existing.values())
    hidden_count = 0
    start_time  = time.time()

    print(f"  Scanning tokens {args.start}–{total}...\n")

    for token_id in range(args.start, total + 1):

        # Progress line
        pct     = (token_id - args.start) / max(total - args.start, 1) * 100
        elapsed = time.time() - start_time
        rate    = (token_id - args.start) / elapsed if elapsed > 0 else 0
        eta     = (total - token_id) / rate if rate > 0 else 0
        print(f"\r  [{token_id:>4}/{total}]  {pct:>5.1f}%  "
              f"revealed={len(revealed)}  hidden={hidden_count}  "
              f"ETA {int(eta//60)}m{int(eta%60):02d}s  ", end="", flush=True)

        # Skip already indexed
        if token_id in existing:
            continue

        # ── Fetch tokenURI ──
        raw_uri = call(rpc_url, "0xc87b56dd", pad_uint(token_id))
        time.sleep(delay)
        uri = decode_string(raw_uri) if raw_uri else ""

        if uri and uri.strip().startswith("=== symbol"):
            # Revealed — parse metadata
            parsed = parse_metadata(uri)
            if not parsed:
                hidden_count += 1
                continue

            # Fetch owner
            raw_owner = call(rpc_url, "0x6352211e", pad_uint(token_id))
            time.sleep(delay)
            owner = decode_address(raw_owner) if raw_owner else ""

            # Match to local folder
            folder, gif = find_symbol_folder(parsed["number"])

            revealed.append({
                "tokenId":    token_id,
                "number":     parsed["number"],
                "title":      parsed["title"],
                "folder":     folder,
                "gif":        gif,
                "owner":      owner,
                "generation": parsed["generation"],
                "chain":      parsed["chain"],
                "ts":         parsed["timestamp"],
                "effects":    parsed["effects"],
                "grid":       parsed["grid"],
            })
        else:
            hidden_count += 1

        # Save checkpoint every 50 tokens
        if token_id % 50 == 0:
            _save(revealed, hidden_count, total, rpc_url)

    # Final save
    _save(revealed, hidden_count, total, rpc_url)

    elapsed = time.time() - start_time
    print(f"\n\n  ─────────────────────────────────")
    print(f"  Revealed : {len(revealed)}")
    print(f"  Hidden   : {hidden_count}")
    print(f"  Total    : {total}")
    print(f"  Time     : {int(elapsed//60)}m{int(elapsed%60):02d}s")
    print(f"  Saved to : {OUTPUT_FILE}")
    print(f"  ─────────────────────────────────\n")


def _save(revealed, hidden_count, total, rpc_url):
    data = {
        "revealed":    revealed,
        "hiddenCount": hidden_count,
        "total":       total,
        "fetchedAt":   int(datetime.now(timezone.utc).timestamp()),
        "rpc":         rpc_url,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
