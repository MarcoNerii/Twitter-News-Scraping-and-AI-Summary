import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Tuple

from playwright.async_api import async_playwright
import google.generativeai as genai


# =========================
# ---- Settings (edit) ----
# =========================
USER = "financialjuice"                 # X handle to scrape
HOURS_BACK = 24                         # last N hours
OUT_TXT = "financialjuice_last_hours.txt"
OUTPUT_TZ = "Europe/Zurich"             # Geneva time
MAX_SCROLLS = 80                        # increase for more tweets
SCROLL_WAIT_MS = 1600                   # milliseconds between scrolls
COOKIES_FILE = "x_cookies.json"         # your exported X cookies (JSON)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

MODEL_NAME = "gemini-1.5-flash"         # or "gemini-1.5-pro"

CUSTOM_PROMPT = (
    """ Summarieze the following headlines into a concise Daily Macro & Markets Recap.
    Divide the summary into clear sections by region and country, using headings and bullet points.
    Group very very related news toghether and keep only the most relevant news for financial markets.
    Keep the summary within 2 pages maximum, and max 5 bullet points per country.
    Use the following sections, but remove those without relevant news:
    1. Euro Area (Germany, France, Italy, Spain, Greece, Portugal, Belgium, Netherlands, Austria, Ireland, Finland)
    2. Nordics (Sweden, Norway, Denmark, not Switzerland)
    3. United Kingdom
    4. Switzerland
    5. North America (only United States and Canada)
    6. APAC (only China, Japan, Australia, and New Zealand)
    Make a subsection for each country for sections including many countries, and keep max 5 bullet points per country.
    Use a headline line for each country (e.g., United States – Housing soft, Fed bias tilts dovish).
    Divide every section with a horizontal line (---)."""
)

# ==========================================================
# ---- (Optional) login helper you can run once if needed ---
# ==========================================================
async def login_and_save_cookies():
    """Run this once if anonymous scraping yields 0 tweets.
    It opens a real browser window so you can login; then saves cookies."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1200, "height": 900})
        page = await ctx.new_page()
        await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=120_000)
        input("A browser window opened. Log in to X. When your timeline is visible, press Enter here...")
        cookies = await ctx.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        await browser.close()
        print(f"[login] Cookies saved to {COOKIES_FILE}")


# ============================
# ---- Scraper (Playwright) ---
# ============================
async def scrape_last_hours(user: str, hours_back: int = 24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    tz = ZoneInfo(OUTPUT_TZ)
    rows, seen = [], set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 2000})

        # Reuse your logged‑in cookies if present (recommended)
        if Path(COOKIES_FILE).exists():
            try:
                with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                    await ctx.add_cookies(json.load(f))
            except Exception:
                pass

        page = await ctx.new_page()
        await page.goto(f"https://x.com/{user}", wait_until="domcontentloaded", timeout=90_000)

        # Best-effort: dismiss consent overlays
        for label in ("Accept", "I agree", "Allow all"):
            try:
                await page.get_by_role("button", name=label).click(timeout=1500)
            except Exception:
                pass

        # Scroll & collect
        for _ in range(MAX_SCROLLS):
            arts = await page.query_selector_all("article[data-testid='tweet']")
            for a in arts:
                link_el = await a.query_selector('a[role="link"][href*="/status/"]')
                if not link_el:
                    continue
                href = await link_el.get_attribute("href")
                if not href or href in seen:
                    continue

                t_el = await a.query_selector("time")
                if not t_el:
                    continue
                dt_str = await t_el.get_attribute("datetime")
                if not dt_str:
                    continue

                # Parse ISO time (UTC) and filter by cutoff
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue

                parts = await a.query_selector_all('[data-testid="tweetText"]')
                text = "\n".join([await n.inner_text() for n in parts]).strip() if parts else ""

                rows.append({"time": dt.astimezone(tz), "text": text})
                seen.add(href)

            await page.mouse.wheel(0, 20000)
            await page.wait_for_timeout(SCROLL_WAIT_MS)

        await browser.close()

    # Dedupe + newest→oldest
    out = list({(r["time"].isoformat(), r["text"]): r for r in rows}.values())
    out.sort(key=lambda r: r["time"], reverse=True)
    return out


def save_tweets_txt(rows, path: str):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['time'].strftime('%Y-%m-%d %H:%M:%S %Z')} | {r['text']}\n\n")


# ==================================
# ---- Summarization (Gemini) -------
# ==================================
def require_gemini():
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_API_KEY environment variable.")
    genai.configure(api_key=key, transport="rest")


def load_tweets(path: str = OUT_TXT) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def chunk_text(s: str, max_chars: int = 15000) -> List[str]:
    """Greedy chunking by blank-line separated entries, staying under max_chars per chunk."""
    s = s.replace("\r\n", "\n")
    chunks, cur, total = [], [], 0
    for block in s.split("\n\n"):
        block += "\n\n"
        if cur and total + len(block) > max_chars:
            chunks.append("".join(cur))
            cur, total = [], 0
        cur.append(block)
        total += len(block)
    if cur:
        chunks.append("".join(cur))
    return chunks


def summarize_chunks(chunks: List[str], custom_prompt: str, model_name: str) -> List[str]:
    model = genai.GenerativeModel(model_name)
    system = "Follow the user’s instructions exactly. Do not add extra sections beyond what they ask."
    outputs = []
    for i, ch in enumerate(chunks, 1):
        prompt = (
            custom_prompt
            + f"\n\nCHUNK {i}/{len(chunks)} — TWEETS START\n<<<\n{ch}\n>>>\n"
            + "Return a 'generatconcise markdown summary (headings + bullet points)."
        )
        resp = model.generate_content([system, prompt])
        outputs.append((resp.text or "").strip())
    return outputs


def final_synthesis(per_chunk: List[str], custom_prompt: str, model_name: str) -> str:
    model = genai.GenerativeModel(model_name)
    joined = "\n\n--- CHUNK SPLIT ---\n\n".join(per_chunk)
    prompt = (
        custom_prompt
        + "\n\nYou are given partial summaries of tweet batches. "
          "Merge them into ONE well-structured Markdown document following the exact instructions above.\n\n"
          "PARTIAL SUMMARIES START\n<<<\n" + joined + "\n>>>\n"
          "Return ONLY the final markdown."
    )
    resp = model.generate_content(prompt)
    return (resp.text or "").strip()


def summarize_tweets_to_md(
    tweets_path: str = OUT_TXT,
    output_md: str = "summary.md",
    custom_prompt: str = CUSTOM_PROMPT,
    model_name: str = MODEL_NAME,
    max_chars_per_chunk: int = 15000,
) -> Tuple[str, int, int]:
    require_gemini()
    raw = load_tweets(tweets_path)
    if not raw:
        raise ValueError(f"Tweet file is empty: {tweets_path}")

    chunks = chunk_text(raw, max_chars=max_chars_per_chunk)
    per_chunk = summarize_chunks(chunks, custom_prompt, model_name)
    md = final_synthesis(per_chunk, custom_prompt, model_name)

    Path(output_md).write_text(md, encoding="utf-8")
    return output_md, len(raw), len(chunks)


# ==========================
# ---- Main entrypoint -----
# ==========================
async def main():
    # 1) Scrape
    rows = await scrape_last_hours(USER, HOURS_BACK)
    print(f"[scrape] Collected {len(rows)} tweets in last {HOURS_BACK}h")
    save_tweets_txt(rows, OUT_TXT)
    print(f"[scrape] Saved -> {OUT_TXT}")

    # 2) Summarize
    out_file, n_chars, n_chunks = summarize_tweets_to_md(
        tweets_path=OUT_TXT,
        output_md="summary.md",
        custom_prompt=CUSTOM_PROMPT,
        model_name=MODEL_NAME,
        max_chars_per_chunk=15000,
    )
    print(f"[summarize] Input chars: {n_chars}, chunks: {n_chunks}")
    print(f"[summarize] Saved -> {out_file}")


if __name__ == "__main__":
    # If you need to create cookies first, uncomment this line once:
    asyncio.run(login_and_save_cookies())
    asyncio.run(main())
