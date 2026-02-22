



import asyncio
import re
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright
import requests
import httpx
import os
from dotenv import load_dotenv

load_dotenv()
OMDB_KEY = os.getenv("OMDB_KEY")

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0"}


@app.get("/search")
async def search(q: str):
    r = requests.get("http://www.omdbapi.com/", params={"apikey": OMDB_KEY, "s": q})
    return r.json()

@app.get("/servers")
async def servers(imdb: str, type: str, season: str = None, episode: str = None):
    params = {"imdb": imdb, "type": type}
    if season: params["season"] = season
    if episode: params["episode"] = episode
    r = requests.get("https://primesrc.me/api/v1/s", params=params, headers=HEADERS)
    return r.json()

@app.get("/link")
async def link(key: str):
    r = requests.get("https://primesrc.me/api/v1/l", params={"key": key}, headers=HEADERS)
    return r.json()

@app.get("/download")
async def download(primevid_url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )

        page = await context.new_page()

        async def close_popup(popup):
            await popup.close()
        context.on("page", lambda popup: asyncio.create_task(close_popup(popup)))

        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        await page.goto(primevid_url, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        await page.wait_for_selector("button.downloader-button", timeout=15000)
        await page.evaluate("""
            () => {
                const btn = document.querySelector('button.downloader-button');
                btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            }
        """)

        await page.wait_for_timeout(8000)

        html = await page.content()
        all_links = re.findall(r'<a[^>]*class="downloader-button"[^>]*href="([^"]+)"', html)

        download_url = None
        for link_url in all_links:
            if "primevid.click" not in link_url:
                download_url = link_url
                break

        await browser.close()

        if not download_url:
            return {"error": "Could not extract download URL"}
        return {"url": download_url}

@app.get("/proxy-download")
async def proxy_download(url: str, title: str = "video.mp4"):
    headers = {
        "Referer": "https://primevid.click/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0",
        "Origin": "https://primevid.click",
    }

    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
                async for chunk in r.aiter_bytes(chunk_size=1024 * 64):
                    yield chunk

    filename = title.replace('"', '')
    return StreamingResponse(
        stream(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

app.mount("/", StaticFiles(directory="static", html=True), name="static")


