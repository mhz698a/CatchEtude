# ng_extract.py
import requests
import re
import os
import email.utils
from bs4 import BeautifulSoup
from dateutil import parser

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

class NGError(Exception):
    pass

USE_NG_UPLOADED_DATE = False

VERBOSE = False

def ng_print(text):
    print(text if VERBOSE else "")

def parse_http_date(v):
    try:
        if not v:
            return None
        return email.utils.parsedate_to_datetime(v).timestamp()
    except Exception:
        return None


def extract_ng_uploaded_ts(soup):
    try:
        dl = soup.select_one("#sidestats dl.sidestats")
        if not dl:
            return None

        for dt in dl.find_all("dt"):
            if dt.get_text(strip=True) == "Uploaded":
                dd_date = dt.find_next_sibling("dd")
                dd_time = dd_date.find_next_sibling("dd") if dd_date else None

                if not dd_date or not dd_time:
                    return None

                raw = f"{dd_date.get_text(strip=True)} {dd_time.get_text(strip=True)}"
                return parser.parse(raw).timestamp()

    except Exception:
        pass

    return None

def extract_ng(song_id):
    """Devuelve dict: {title, url, content_length (int or None), last_modified_ts (float or None)}"""
    if not song_id or not song_id.isdigit():
        raise NGError("ID no numérico")

    url = f"https://www.newgrounds.com/audio/listen/{song_id}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        raise NGError(f"HTTP {r.status_code} al pedir la página NG")

    soup = BeautifulSoup(r.text, "html.parser")

    if soup.find(id="pageerror"):
        raise NGError("Audio no existe o fue eliminado (pageerror)")

    title = soup.title.text.strip() if soup.title else f"newgrounds_{song_id}"
    
    # ---------- artista ----------
    artist = None
    try:
        a = soup.select_one("div.authorlinks h4 a")
        if a:
            artist = a.get_text(strip=True)
    except Exception:
        artist = None

    # regex para URL mp3
    m = re.search(r'https?://audio\.ngfiles\.com/[^\s"\'<>]+?\.mp3', r.text)
    if not m:
        # fallback: buscar con escapes
        m2 = re.search(r'audio\.ngfiles\.com\\?/[^"]+?\.mp3', r.text)
        if m2:
            raw = m2.group(0).replace('\\/', '/')
            mp3_url = "https://" + raw if raw.startswith('audio.') else raw
        else:
            raise NGError("No se encontró enlace mp3 en HTML")
    else:
        mp3_url = m.group(0)

    # HEAD para metadata
    try:
        h = requests.head(mp3_url, headers=HEADERS, allow_redirects=True, timeout=15)
    except Exception:
        h = None

    content_length = None
    last_mod_ts = None
    if h is not None:
        try:
            if 'Content-Length' in h.headers:
                content_length = int(h.headers['Content-Length'])
        except Exception:
            content_length = None
            
        lm = h.headers.get('Last-Modified') or h.headers.get('Date')
        file_ts = parse_http_date(lm) if lm else None

        uploaded_ts = None
        if USE_NG_UPLOADED_DATE:
            uploaded_ts = extract_ng_uploaded_ts(soup)

        final_ts = uploaded_ts if uploaded_ts is not None else file_ts

    return {
        "title": title,
        "artist": artist,
        "mp3_url": mp3_url,
        "content_length": content_length,
        "last_modified_ts": final_ts
    }


def download_ng_stream(mp3_url, dest_path, progress_callback=None, chunk_size=64*1024, stop_flag=None):
    """Descarga por streaming. progress_callback(bytes_downloaded, total_or_none)"""
    tmp = dest_path + ".part"
    with requests.get(mp3_url, headers=HEADERS, stream=True, timeout=20) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0)) or None
        downloaded = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if stop_flag is not None and stop_flag():
                    # cancela limpiamente (dejar partial para reanudar)
                    return {"cancelled": True, "downloaded": downloaded, "total": total}
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)
    os.replace(tmp, dest_path)
    # intentar setear fecha si el servidor la tiene
    # (no repetimos HEAD aquí, se espera que caller la pase o use extract_ng para obtener last_modified)
    return {"cancelled": False, "downloaded": downloaded, "total": total}
