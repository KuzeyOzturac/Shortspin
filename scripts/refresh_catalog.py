"""Refresh stable video IDs, never expiring CDN URLs or downloaded media."""
import ast
import json
import random
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def shorts_shelf(term):
    # Recent YouTube search pages keep Shorts in a separate shelf, which some
    # yt-dlp flat searches omit. Read those stable IDs before normal results.
    url = 'https://www.youtube.com/results?' + urllib.parse.urlencode({'search_query': term})
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode('utf-8')
    match = re.search(r'var ytInitialData = (.*?);</script>', html)
    if not match:
        return []
    result = []
    def walk(value):
        if isinstance(value, dict):
            shelf = value.get('shortsLockupViewModel')
            if shelf:
                command = shelf.get('onTap', {}).get('innertubeCommand', {})
                vid = command.get('reelWatchEndpoint', {}).get('videoId', '')
                title = shelf.get('overlayMetadata', {}).get('primaryText', {}).get('content')
                video = entry_to_video({'id': vid, 'title': title or shelf.get('accessibilityText', 'Short video').split(',')[0]})
                if video:
                    result.append(video)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(json.loads(match.group(1)))
    return result


def config():
    wanted = {"SEARCH_TERMS", "DIRECT_VIDEO_URLS", "SEARCH_BATCH", "DISCOVERY_TARGET"}
    values = {}
    for node in ast.parse((ROOT / "main.py").read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    values[target.id] = ast.literal_eval(node.value)
    return values


def entry_to_video(entry):
    if not entry or not re.fullmatch(r"[A-Za-z0-9_-]{11}", entry.get("id", "")):
        return None
    duration = entry.get("duration")
    if duration is not None and (duration <= 0 or duration > 180):
        return None
    if entry.get("is_live") or entry.get("availability") in {"private", "premium_only", "subscriber_only", "needs_auth"}:
        return None
    vid = entry["id"]
    return {"type": "youtube", "id": vid, "title": entry.get("title") or "Short video",
            "source": f"https://www.youtube.com/shorts/{vid}",
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/oar2.jpg"}


def main():
    import yt_dlp
    settings = config()
    path = ROOT / "web/videos.json"
    existing = json.loads(path.read_text()) if path.exists() else {"videos": []}
    found = {}
    terms = settings["SEARCH_TERMS"][:]
    random.shuffle(terms)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": "in_playlist", "cachedir": False, "socket_timeout": 12,
            "retries": 0, "extractor_retries": 0, "ignoreerrors": True}
    urls = settings["DIRECT_VIDEO_URLS"] + [f'ytsearch{settings["SEARCH_BATCH"]}:{term}' for term in terms]
    for url in urls:
        # Pages-only playback supports YouTube embeds and explicit direct media
        # in videos.json. Do not pretend TikTok/Instagram URLs are MP4 streams.
        if not url.startswith("ytsearch") and not any(host in url for host in ("youtube.com/", "youtu.be/")):
            print("Unsupported Pages discovery source:", url)
            continue
        try:
            if url.startswith('ytsearch'):
                shelf = shorts_shelf(url.split(':', 1)[1])
                for video in shelf:
                    found[video['id']] = video
                if len(found) >= settings['DISCOVERY_TARGET']:
                    break
                if shelf:
                    continue
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = (info or {}).get("entries", [info])
            for entry in entries or []:
                video = entry_to_video(entry)
                if video:
                    found[video["id"]] = video
        except Exception as exc:
            print(f"Discovery failed: {type(exc).__name__}")
        if len(found) >= settings["DISCOVERY_TARGET"]:
            break
    # Keep the last usable catalog if the provider blocks CI discovery.
    if len(found) < 6:
        if len(existing.get("videos", [])) >= 6:
            print("::warning::Discovery returned fewer than six videos; retaining the checked-in catalog.")
            return
        raise RuntimeError("No usable catalog. Add at least six videos to web/videos.json.")
    direct = [v for v in existing.get("videos", []) if v.get("type") == "video"]
    output = {"updatedAt": datetime.now(timezone.utc).isoformat(),
              "videos": direct + list(found.values())[:settings["DISCOVERY_TARGET"]]}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(output, indent=2) + "\n")
    temp.replace(path)
    print(f"Prepared {len(output['videos'])} video references.")


if __name__ == "__main__":
    main()
