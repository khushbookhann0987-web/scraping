# Site Reader – Website Info Scraper

Paste a website link and get: **pages, services, purpose and contact info**.

- Backend: Python (Flask, Requests, BeautifulSoup)
- Frontend: HTML, CSS, JavaScript (no frameworks)

## Run in VS Code

1. Open this folder in VS Code (`File > Open Folder`).
2. Open a terminal (`Ctrl + ` `) and create a virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # macOS / Linux
   ```
3. Install packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the server:
   ```bash
   python app.py
   ```
5. Open http://127.0.0.1:5000 in your browser, type a website link, and click **Scan website**.

## Structure

```
website-scraper/
├── app.py            Flask server + /api/scrape endpoint
├── scraper.py        Crawling and extraction logic
├── requirements.txt
└── static/
    ├── index.html
    ├── style.css
    └── script.js
```

## How it works

- Crawls the homepage, then follows internal links (contact / about / services pages first).
- **Pages**: URL, title, type (home, about, contact, services, products, blog) and word count.
- **Services**: JSON-LD data, headings and lists on service/product pages, and navigation links.
- **Purpose**: meta description, JSON-LD description, and intro paragraphs from home/about pages.
- **Contact**: emails, phone numbers (`tel:` links and text), addresses, social profiles, contact pages and forms.
- Links to private/local network addresses are blocked.

## Limits

- Sites that build their content with JavaScript (React, Vue, etc.) may return little data, because this tool reads the HTML only. A browser-based tool such as Playwright can be added for those sites.
- Some sites block automated requests.
- Results come from heuristics, so review them before relying on them.
- Only scan sites you are allowed to access and follow their terms of use.
