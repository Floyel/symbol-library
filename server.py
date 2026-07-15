"""
Symbol Library Server
Run this once from the terminal: python server.py
Then open http://localhost:5000 in your browser.
Place this file one level above your symbols/ folder.
"""

import os
import json
import subprocess
import platform
import urllib.request
from flask import Flask, jsonify, send_from_directory, abort, request

app = Flask(__name__)

# ── CONFIG ──────────────────────────────────────────────────────────────────
SYMBOLS_DIR = os.path.join(os.path.dirname(__file__), "symbols")
BASE_RPC    = "https://mainnet.base.org"
# ────────────────────────────────────────────────────────────────────────────

# Clean Apple Double files on Mac startup
if platform.system() == "Darwin":
    subprocess.run(["dot_clean", SYMBOLS_DIR], capture_output=True)


def get_symbols():
    """Scan the symbols/ folder and return a list of symbol metadata."""
    symbols = []
    if not os.path.isdir(SYMBOLS_DIR):
        return symbols

    for folder_name in sorted(os.listdir(SYMBOLS_DIR)):
        folder_path = os.path.join(SYMBOLS_DIR, folder_name)
        if not os.path.isdir(folder_path):
            continue

        manifest_path = os.path.join(folder_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            continue

        # Find the GIF file — skip Apple Double files
        gif_file = None
        for fname in sorted(os.listdir(folder_path)):
            if fname.lower().endswith(".gif") and not fname.startswith("._"):
                gif_file = fname
                break

        # Check for audio
        has_audio = any(
            fname.lower().endswith(".mp3") for fname in os.listdir(folder_path)
        )

        symbols.append({
            "folder":     folder_name,
            "manifest":   manifest,
            "gif":        gif_file,
            "has_audio":  has_audio,
            "has_viewer": os.path.isfile(os.path.join(folder_path, "viewer.html")),
        })

    return symbols


# ── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "library.html")

@app.route("/manifest-panel.html")
def manifest_panel():
    return send_from_directory(os.path.dirname(__file__), "manifest-panel.html")

@app.route("/mint.html")
def mint_page():
    return send_from_directory(os.path.dirname(__file__), "mint.html")

@app.route("/chain_data.json")
def chain_data():
    """Serve the chain index file built by chain_index.py."""
    path = os.path.join(os.path.dirname(__file__), "chain_data.json")
    if not os.path.isfile(path):
        return jsonify({
            "revealed": [],
            "hiddenCount": 0,
            "total": 3333,
            "fetchedAt": 0
        })
    return send_from_directory(os.path.dirname(__file__), "chain_data.json")

@app.route("/api/symbols")
def api_symbols():
    return jsonify(get_symbols())

@app.route("/api/debug/token/<int:token_id>")
def debug_token(token_id):
    """Debug: fetch and decode tokenURI for a specific token ID."""
    import urllib.request as ur
    CONTRACT = "0xB881317390AbA4fA628C2235381D7838070125EC"
    sig    = "0xc87b56dd"
    padded = hex(token_id)[2:].zfill(64)
    data   = sig + padded
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_call",
        "params": [{"to": CONTRACT, "data": data}, "latest"]
    }).encode()
    req = ur.Request(BASE_RPC, data=payload,
        headers={"Content-Type":"application/json",
                 "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        method="POST")
    with ur.urlopen(req, timeout=15) as r:
        rpc_result = json.loads(r.read())
    if "error" in rpc_result:
        return jsonify({"error": rpc_result["error"]}), 400
    hex_str = rpc_result.get("result", "")
    if len(hex_str) <= 2:
        return jsonify({"raw_hex": hex_str, "decoded": None})
    data_bytes = bytes.fromhex(hex_str[2:])
    try:
        str_len = int.from_bytes(data_bytes[32:64], "big")
        text = data_bytes[64:64 + str_len].decode("utf-8", errors="replace")
    except Exception:
        text = data_bytes.decode("utf-8", errors="replace").strip("\x00")
    return jsonify({
        "token_id":    token_id,
        "hex_length":  len(hex_str),
        "str_length":  len(text),
        "starts_with": text[:50],
        "is_revealed": text.strip().startswith("=== symbol"),
        "full_text":   text[:500]
    })

@app.route("/api/rpc", methods=["POST"])
def rpc_proxy():
    """
    Proxy JSON-RPC calls to Base mainnet.
    The browser cannot call the RPC directly due to CORS restrictions.
    This route forwards the request server-side and returns the result.
    """
    try:
        body = request.get_data()
        print(f"RPC proxy: body={body[:200]}")
        req  = urllib.request.Request(
            BASE_RPC,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read()
        print(f"RPC proxy: response={result[:200]}")
        return app.response_class(
            response=result,
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        import traceback
        print(f"RPC proxy ERROR: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/symbols/<path:filepath>")
def serve_symbol_file(filepath):
    """Serve any file from inside a symbol folder. Blocks Apple Double files."""
    filename = os.path.basename(filepath)
    if filename.startswith("._"):
        abort(404)
    full_path = os.path.join(SYMBOLS_DIR, filepath)
    if not os.path.isfile(full_path):
        abort(404)
    folder = os.path.dirname(filepath)
    return send_from_directory(os.path.join(SYMBOLS_DIR, folder), filename)


if __name__ == "__main__":
    print("\n  Symbol Library running at http://localhost:5000\n")
    app.run(debug=False, port=5000)
