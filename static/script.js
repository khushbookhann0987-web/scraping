"use strict";

const $ = (id) => document.getElementById(id);
let lastResult = null;

/* ---------- safe DOM helpers (scraped text is never inserted as HTML) ---------- */
function el(tag, { text = "", cls = "", attrs = {} } = {}, children = []) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  children.forEach((c) => node.appendChild(c));
  return node;
}

function safeLink(url, label) {
  const ok = /^https?:\/\//i.test(url);
  if (!ok) return el("span", { text: label || url });
  return el("a", { text: label || url, attrs: { href: url, target: "_blank", rel: "noopener noreferrer" } });
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

/* ---------- status ---------- */
function showStatus(kind, message) {
  const box = $("status");
  clear(box);
  box.className = "status " + kind;
  if (kind === "loading") box.appendChild(el("span", { cls: "spinner" }));
  box.appendChild(el("span", { text: message }));
  box.hidden = false;
}
function hideStatus() { $("status").hidden = true; }

/* ---------- submit ---------- */
$("scrape-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("url").value.trim();
  const maxPages = parseInt($("max-pages").value, 10);
  if (!url) return;

  const btn = $("submit-btn");
  btn.disabled = true;
  btn.textContent = "Scanning…";
  $("results").hidden = true;
  $("empty").hidden = true;
  showStatus("loading", "Scanning the website and its pages. This can take up to 30 seconds.");

  try {
    const res = await fetch("/api/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, max_pages: maxPages }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    lastResult = data;
    render(data);
    hideStatus();
  } catch (err) {
    $("empty").hidden = false;
    showStatus("error", err.message || "Could not reach the scraper. Is the Python server running?");
  } finally {
    btn.disabled = false;
    btn.textContent = "Scan website";
  }
});

/* ---------- render ---------- */
function render(d) {
  const { site, purpose, pages, services, contact } = d;

  // header
  $("site-name").textContent = site.org_name || site.title || "Website";
  const link = $("site-url");
  link.textContent = site.url;
  link.href = /^https?:\/\//i.test(site.url) ? site.url : "#";
  const fav = $("favicon");
  fav.src = site.favicon || "";
  fav.onerror = () => { fav.style.visibility = "hidden"; };
  fav.style.visibility = "visible";

  // purpose
  $("purpose-main").textContent = purpose.summary || "No clear description was found on this website.";
  const more = $("purpose-more");
  clear(more);
  purpose.more.forEach((t) => more.appendChild(el("li", { text: t })));

  const facts = $("site-meta");
  clear(facts);
  const addFact = (k, v) => { if (v) { facts.appendChild(el("dt", { text: k })); facts.appendChild(el("dd", { text: v })); } };
  addFact("Page title", site.title);
  addFact("Language", site.language);
  addFact("Keywords", (site.keywords || []).join(", "));
  addFact("Pages scanned", String(d.stats.pages_scanned));

  renderContact(contact);
  renderServices(services);
  renderPages(pages, d);

  $("results").hidden = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderContact(c) {
  const box = $("contact");
  clear(box);

  const group = (title, items) => {
    if (!items.length) return;
    const ul = el("ul", {}, items);
    box.appendChild(el("div", { cls: "contact-group" }, [el("h4", { text: title }), ul]));
  };

  group("Email", c.emails.map((e) => el("li", {}, [el("a", { text: e.value, attrs: { href: "mailto:" + encodeURIComponent(e.value).replace("%40", "@") } })])));
  group("Phone", c.phones.map((p) => el("li", {}, [el("a", { text: p.value, attrs: { href: "tel:" + p.value.replace(/[^\d+]/g, "") } })])));
  group("Address", c.addresses.map((a) => el("li", { text: a })));
  group("Social profiles", c.socials.map((s) => el("li", {}, [safeLink(s.url, s.name + " – " + s.url.replace(/^https?:\/\/(www\.)?/, ""))])));
  group("Contact pages", c.contact_pages.map((u) => el("li", {}, [safeLink(u)])));
  if (c.forms.length) {
    group("Contact form", c.forms.map((u) => el("li", {}, [safeLink(u, "Form found on " + u.replace(/^https?:\/\//, ""))])));
  }

  if (!box.children.length) {
    box.appendChild(el("p", { cls: "muted", text: "No contact details were found on the scanned pages. Try scanning more pages." }));
  }
}

function renderServices(list) {
  const ul = $("services");
  clear(ul);
  list.forEach((s) => ul.appendChild(el("li", { text: s })));
  $("services-count").textContent = list.length ? `(${list.length})` : "";
  $("services-empty").hidden = list.length > 0;
}

function renderPages(pages, d) {
  const body = $("pages-body");
  clear(body);
  pages.forEach((p) => {
    const row = el("tr", {}, [
      el("td", {}, [el("span", { text: p.category, cls: "badge " + p.category })]),
      el("td", { text: p.title }),
      el("td", {}, [safeLink(p.url, p.url.replace(/^https?:\/\/(www\.)?/, ""))]),
      el("td", { text: String(p.words), cls: "num" }),
    ]);
    body.appendChild(row);
  });
  $("pages-count").textContent = `(${pages.length})`;

  const fill = (boxId, listId, countId, urls) => {
    const box = $(boxId), list = $(listId);
    clear(list);
    urls.forEach((u) => list.appendChild(el("li", {}, [safeLink(u)])));
    $(countId).textContent = urls.length ? `(${urls.length})` : "";
    box.hidden = urls.length === 0;
  };
  fill("more-links-box", "more-links", "more-count", d.other_links);
  const smTotal = d.sitemap.count;
  fill("sitemap-box", "sitemap-links", "sitemap-count", d.sitemap.urls);
  if (smTotal > d.sitemap.urls.length) $("sitemap-count").textContent = `(showing ${d.sitemap.urls.length} of ${smTotal})`;
}

/* ---------- export ---------- */
$("copy-btn").addEventListener("click", async () => {
  if (!lastResult) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2));
    $("copy-btn").textContent = "Copied";
  } catch {
    $("copy-btn").textContent = "Copy failed";
  }
  setTimeout(() => ($("copy-btn").textContent = "Copy JSON"), 1500);
});

$("download-btn").addEventListener("click", () => {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  const host = (() => { try { return new URL(lastResult.site.url).hostname; } catch { return "site"; } })();
  a.href = URL.createObjectURL(blob);
  a.download = `${host}-scan.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
});
