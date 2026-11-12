"""Flask backend for the Website Info Scraper."""
from flask import Flask, jsonify, request, send_from_directory

from scraper import ScrapeError, scrape_site

app = Flask(__name__, static_folder="static", static_url_path="/static")


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/scrape")
def api_scrape():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    try:
        max_pages = int(data.get("max_pages", 8))
    except (TypeError, ValueError):
        max_pages = 8
    max_pages = max(1, min(max_pages, 25))

    if not url:
        return jsonify({"error": "Please enter a website link."}), 400

    try:
        return jsonify(scrape_site(url, max_pages=max_pages))
    except ScrapeError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Unexpected scrape failure")
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
