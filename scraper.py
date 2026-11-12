"""Scraping logic: crawls a site and extracts pages, services, purpose and contact info."""
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SiteInfoScraper/1.0; +local-tool)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en;q=0.9,*;q=0.5",
}
TIMEOUT = 12
MAX_BYTES = 2_500_000

SKIP_EXT = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".pdf", ".zip", ".rar",
    ".mp3", ".mp4", ".avi", ".mov", ".css", ".js", ".xml", ".json", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".exe", ".dmg", ".woff", ".woff2", ".ttf",
)

CATEGORY_KEYWORDS = {
    "contact": ("contact", "reach-us", "get-in-touch", "support", "enquiry", "inquiry", "location"),
    "about": ("about", "who-we-are", "company", "our-story", "mission", "team", "history"),
    "services": ("service", "solution", "what-we-do", "offering", "capabilit", "expertise", "industries"),
    "products": ("product", "shop", "store", "catalog", "pricing", "plans", "menu", "courses"),
    "blog": ("blog", "news", "article", "insight", "press", "stories"),
}
PRIORITY = ["contact", "about", "services", "products", "blog"]

SOCIAL_DOMAINS = {
    "facebook.com": "Facebook", "fb.com": "Facebook", "instagram.com": "Instagram",
    "twitter.com": "X / Twitter", "x.com": "X / Twitter", "linkedin.com": "LinkedIn",
    "youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok",
    "github.com": "GitHub", "pinterest.com": "Pinterest", "wa.me": "WhatsApp",
    "api.whatsapp.com": "WhatsApp", "t.me": "Telegram", "threads.net": "Threads",
}

NOISE_TEXT = {
    "home", "menu", "contact", "contact us", "about", "about us", "login", "log in", "sign in",
    "sign up", "register", "read more", "learn more", "view all", "see more", "subscribe",
    "newsletter", "privacy policy", "terms", "terms of service", "cookies", "cookie policy",
    "follow us", "share", "search", "cart", "skip to content", "get started", "back to top",
    "quick links", "useful links", "categories", "navigation", "footer", "next", "previous",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w/])(\+?\d[\d\s().\-]{7,18}\d)(?![\w/])")


class ScrapeError(Exception):
    """A user-facing scraping problem."""


# --------------------------------------------------------------------------- #
# URL helpers
# --------------------------------------------------------------------------- #
def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc or "." not in parsed.netloc and parsed.hostname != "localhost":
        raise ScrapeError("That doesn't look like a valid website link.")
    return raw


def assert_public(url: str) -> None:
    """Block requests to private/internal addresses (basic SSRF protection)."""
    host = urlparse(url).hostname
    if not host:
        raise ScrapeError("That doesn't look like a valid website link.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ScrapeError(f"Could not find the website '{host}'. Check the spelling of the link.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ScrapeError("Links to private or local network addresses are not allowed.")


def clean_url(url: str) -> str:
    """Drop fragment + query, strip trailing slash (used for de-duplication)."""
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc}{path}"


def same_site(a: str, b: str) -> bool:
    strip = lambda h: (h or "").lower().removeprefix("www.")  # noqa: E731
    return strip(urlparse(a).hostname) == strip(urlparse(b).hostname)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch(url: str):
    assert_public(url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True)
    except requests.exceptions.SSLError:
        raise ScrapeError("The website has an SSL/certificate problem.")
    except requests.exceptions.ConnectionError:
        raise ScrapeError("Could not connect to the website.")
    except requests.exceptions.Timeout:
        raise ScrapeError("The website took too long to respond.")
    except requests.exceptions.RequestException as exc:
        raise ScrapeError(f"Request failed: {exc}")

    assert_public(resp.url)  # check the final URL after redirects too
    if resp.status_code >= 400:
        raise ScrapeError(f"The website returned an error (HTTP {resp.status_code}).")
    if "html" not in resp.headers.get("Content-Type", "").lower():
        raise ScrapeError("That link is not a web page (HTML).")

    body = b""
    for chunk in resp.iter_content(65536):
        body += chunk
        if len(body) > MAX_BYTES:
            break
    resp.close()
    encoding = resp.encoding or resp.apparent_encoding or "utf-8"
    html = body.decode(encoding, errors="replace")
    return resp.url, BeautifulSoup(html, "lxml")


def fetch_sitemap(base: str):
    try:
        resp = requests.get(urljoin(base, "/sitemap.xml"), headers=HEADERS, timeout=8)
        if resp.status_code != 200 or "<loc>" not in resp.text:
            return []
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", resp.text, re.S)
        return [u for u in locs if same_site(u, base) or u.endswith(".xml")]
    except requests.exceptions.RequestException:
        return []


# --------------------------------------------------------------------------- #
# Extraction helpers
# --------------------------------------------------------------------------- #
def text_of(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def meta(soup, *names):
    for n in names:
        tag = soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"property": n})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""


def categorize(url: str, title: str) -> str:
    path = urlparse(url).path.lower()
    if path in ("", "/"):
        return "home"
    haystack = f"{path} {title.lower()}"
    for cat in PRIORITY:
        if any(k in haystack for k in CATEGORY_KEYWORDS[cat]):
            return cat
    return "other"


def iter_jsonld(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                stack.extend(v for v in node.values() if isinstance(v, (list, dict)))


def format_address(addr) -> str:
    if isinstance(addr, str):
        return addr.strip()
    if not isinstance(addr, dict):
        return ""
    country = addr.get("addressCountry", "")
    if isinstance(country, dict):
        country = country.get("name", "")
    parts = [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("addressRegion"),
             addr.get("postalCode"), country]
    return ", ".join(str(p).strip() for p in parts if p)


def good_email(e: str) -> bool:
    e = e.lower()
    if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")):
        return False
    return not any(x in e for x in ("sentry", "example.com", "domain.com", "your@", "email@email"))


def normalize_phone(raw: str):
    digits = re.sub(r"\D", "", raw)
    if not 9 <= len(digits) <= 15:
        return None
    # avoid dates / ids: needs a '+' or a separator/parenthesis pattern
    if not (raw.strip().startswith("+") or re.search(r"[\s().\-]", raw)):
        return None
    if re.fullmatch(r"(19|20)\d{2}[\s.\-]\d{1,2}[\s.\-]\d{1,2}", raw.strip()):
        return None
    return re.sub(r"\s+", " ", raw.strip())


def clean_label(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" -–|:•·")
    return text


def usable_label(text: str) -> bool:
    low = text.lower()
    return 3 <= len(text) <= 80 and low not in NOISE_TEXT and not low.startswith(("©", "copyright"))


# --------------------------------------------------------------------------- #
# Main entry
# --------------------------------------------------------------------------- #
def scrape_site(raw_url: str, max_pages: int = 8) -> dict:
    start = normalize_url(raw_url)

    queue = [start]
    seen = set()
    pages = []

    emails, phones, addresses, socials = {}, {}, [], {}
    services = []
    purpose_candidates = []
    contact_pages, forms = [], []
    site = {"url": start, "title": "", "description": "", "language": "", "favicon": "",
            "org_name": "", "keywords": []}
    base_url = start

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        key = clean_url(url)
        if key in seen:
            continue
        seen.add(key)

        try:
            final_url, soup = fetch(url)
        except ScrapeError:
            if not pages:
                raise  # the first page must work
            continue

        is_first = not pages
        if is_first:
            base_url = final_url
            seen.add(clean_url(final_url))

        title = text_of(soup.title) or text_of(soup.find("h1"))
        description = meta(soup, "description", "og:description", "twitter:description")
        category = categorize(final_url, title)
        h1 = text_of(soup.find("h1"))

        # ---- JSON-LD (very reliable when present) ----
        for node in iter_jsonld(soup):
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if any(t in ("Organization", "LocalBusiness", "Corporation", "Store", "Restaurant",
                         "ProfessionalService", "EducationalOrganization", "WebSite") or t.endswith("Business")
                   for t in types):
                if is_first and node.get("name") and not site["org_name"]:
                    site["org_name"] = str(node["name"])
                if node.get("description"):
                    purpose_candidates.append((95, str(node["description"])))
                if node.get("email"):
                    emails.setdefault(str(node["email"]).replace("mailto:", "").lower(), final_url)
                if node.get("telephone"):
                    ph = normalize_phone(str(node["telephone"])) or str(node["telephone"])
                    phones.setdefault(ph, final_url)
                addr = format_address(node.get("address"))
                if addr and addr not in addresses:
                    addresses.append(addr)
                same_as = node.get("sameAs", [])
                for link in ([same_as] if isinstance(same_as, str) else same_as):
                    for dom, name in SOCIAL_DOMAINS.items():
                        if dom in str(link):
                            socials.setdefault(str(link), name)
            if any(t in ("Service", "Product", "Offer") for t in types) and node.get("name"):
                services.append(clean_label(str(node["name"])))

        # ---- Site-level info from the first page ----
        if is_first:
            site["title"] = title
            site["description"] = description
            site["language"] = (soup.html.get("lang", "") if soup.html else "") or ""
            icon = next((l for l in soup.find_all("link", href=True)
                         if "icon" in " ".join(l.get("rel", [])).lower()), None)
            site["favicon"] = urljoin(final_url, icon["href"]) if icon else urljoin(final_url, "/favicon.ico")
            kw = meta(soup, "keywords")
            site["keywords"] = [k.strip() for k in kw.split(",") if k.strip()][:12]
            if not site["org_name"]:
                site["org_name"] = meta(soup, "og:site_name", "application-name") or title.split("|")[0].split(" - ")[0].strip()
            if description:
                purpose_candidates.append((80, description))
            if h1:
                purpose_candidates.append((40, h1))

        # ---- Purpose from about-type pages ----
        if category in ("about", "home"):
            main = soup.find("main") or soup.body or soup
            paras = [text_of(p) for p in main.find_all("p")]
            paras = [p for p in paras if 80 <= len(p) <= 600]
            for p in paras[:2]:
                purpose_candidates.append((70 if category == "about" else 50, p))

        # ---- Contact data ----
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                addr = href[7:].split("?")[0].strip().lower()
                if EMAIL_RE.fullmatch(addr) and good_email(addr):
                    emails.setdefault(addr, final_url)
            elif low.startswith("tel:"):
                num = href[4:].strip()
                phones.setdefault(normalize_phone(num) or num, final_url)
            elif low.startswith("sms:") or "wa.me" in low:
                pass
            for dom, name in SOCIAL_DOMAINS.items():
                host = (urlparse(href).hostname or "").lower().removeprefix("www.")
                if host == dom or host.endswith("." + dom):
                    if len(urlparse(href).path.strip("/")) > 0 and "share" not in low and "intent" not in low:
                        socials.setdefault(href.split("?")[0], name)

        body_text = soup.get_text(" ", strip=True)
        for m in EMAIL_RE.findall(body_text):
            if good_email(m):
                emails.setdefault(m.lower(), final_url)
        for m in PHONE_RE.findall(body_text):
            num = normalize_phone(m)
            if num:
                phones.setdefault(num, final_url)

        for addr_tag in soup.find_all("address"):
            t = text_of(addr_tag)
            if 10 <= len(t) <= 250 and t not in addresses:
                addresses.append(t)
        for tag in soup.find_all(attrs={"itemprop": "streetAddress"}):
            parent = tag.find_parent(attrs={"itemprop": "address"})
            t = text_of(parent or tag)
            if t and t not in addresses:
                addresses.append(t)

        has_form = any(
            f.find("textarea") or f.find("input", attrs={"type": "email"})
            for f in soup.find_all("form")
        )
        if category == "contact":
            contact_pages.append(final_url)
        if has_form and category in ("contact", "home", "about"):
            forms.append(final_url)

        # ---- Services ----
        if category in ("services", "products") or (is_first and category == "home"):
            main = soup.find("main") or soup.body or soup
            limit = 20 if category != "home" else 10
            for h in main.find_all(["h2", "h3", "h4"], limit=limit * 2):
                label = clean_label(text_of(h))
                if usable_label(label):
                    services.append(label)
            if category in ("services", "products"):
                for li in main.find_all("li", limit=60):
                    label = clean_label(text_of(li))
                    if usable_label(label) and len(label.split()) <= 8 and not li.find("a", href=re.compile(r"^(mailto|tel):")):
                        services.append(label)
        if is_first:  # nav links that point to service/product pages
            for a in soup.select("nav a, header a"):
                href = (a.get("href") or "").lower()
                if any(k in href for k in CATEGORY_KEYWORDS["services"] + CATEGORY_KEYWORDS["products"]):
                    label = clean_label(text_of(a))
                    if usable_label(label):
                        services.append(label)

        pages.append({
            "url": final_url, "title": title or "(no title)", "description": description,
            "heading": h1, "category": category,
            "words": len(body_text.split()),
        })

        # ---- Queue internal links ----
        found = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
                continue
            full = urljoin(final_url, href)
            if not full.startswith(("http://", "https://")) or not same_site(full, base_url):
                continue
            if urlparse(full).path.lower().endswith(SKIP_EXT):
                continue
            k = clean_url(full)
            if k not in seen and full not in found:
                found.append(full)
        queue.extend(f for f in found if f not in queue)
        queue.sort(key=lambda u: _priority(u))

    # ---- Sitemap ----
    sitemap = fetch_sitemap(base_url)

    # ---- Assemble results ----
    crawled = {clean_url(p["url"]) for p in pages}
    other_links = [u for u in dict.fromkeys(clean_url(u) for u in queue) if u not in crawled][:40]

    purpose_candidates.sort(key=lambda x: -x[0])
    purpose_text = purpose_candidates[0][1] if purpose_candidates else ""
    supporting = []
    for _, text in purpose_candidates[1:]:
        if text != purpose_text and text not in supporting:
            supporting.append(text)

    return {
        "site": site,
        "purpose": {"summary": purpose_text, "more": supporting[:3]},
        "pages": pages,
        "other_links": other_links,
        "sitemap": {"count": len(sitemap), "urls": sitemap[:40]},
        "services": _dedupe(services)[:30],
        "contact": {
            "emails": [{"value": k, "found_on": v} for k, v in emails.items()][:15],
            "phones": [{"value": k, "found_on": v} for k, v in phones.items()][:15],
            "addresses": addresses[:6],
            "socials": [{"name": n, "url": u} for u, n in socials.items()][:15],
            "contact_pages": list(dict.fromkeys(contact_pages)),
            "forms": list(dict.fromkeys(forms)),
        },
        "stats": {"pages_scanned": len(pages), "requested_max": max_pages},
    }


def _priority(url: str) -> int:
    path = urlparse(url).path.lower()
    for i, cat in enumerate(PRIORITY):
        if any(k in path for k in CATEGORY_KEYWORDS[cat]):
            return i
    return len(PRIORITY) + path.count("/")


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        k = item.lower()
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out
