# Shortspin

A browser port of the original Python Shorts spinning machine, ready for GitHub Pages. The desktop app remains in `main.py`; the web app lives in `web/` and uses the original `sounds/` files.

## Deploy to GitHub Pages

1. Open this repository's **Settings → Pages**.
2. Set **Source** to **GitHub Actions**.
3. Open **Actions → Deploy Shortspin to GitHub Pages → Run workflow**. Future pushes to `main` deploy automatically.
4. After the workflow succeeds, open **https://kuzeyozturac.github.io/Shortspin/**.

No npm dependencies, API key, or paid server is needed for the Pages version. Press **START** once to enable audio and prepare the videos. Browser autoplay restrictions require this initial interaction.

## What the port preserves

- The SHORTSPIN heading, dark background, gray rounded reel frames, gold spin button, original desktop reel dimensions (290 × 500), and 430 × 500 expanded jackpot frame. Small screens use responsive sizing.
- The exact three thumbnail animation duration sequences, progressive slowdown, staggered locks, border pulses, lock bursts, pair celebration, jackpot confetti, short shake, and result flashes. Reduced-motion preferences suppress decorative animation.
- The original selection algorithm: an 8% forced-jackpot branch, a 22% forced-pair branch, and a 70% independent-draw branch that can also match. These are branch probabilities, not the final observed match rates.
- All seven original MP3 files, including click/spin/lock transitions with a 180 ms spin-resume delay, delayed win/pair sounds, and loading-to-loaded timing tied to the visible progress bar.
- Muted video during ordinary play. A jackpot expands the existing first player and enables only its audio. The other two players pause; the next spin restores all three and mutes content immediately.
- A selected thumbnail remains visible when video playback fails, with a retry button. Removed or non-embeddable YouTube IDs are excluded from subsequent draws during that session.

## Pages-only differences

GitHub Pages serves static files; it cannot run Python, Qt, or `yt-dlp` for visitors. Therefore this version is **not an exact replacement for the desktop stream resolver**:

- YouTube videos use the official iframe player. Provider branding, ads, playback restrictions, and occasional overlays are controlled by YouTube. They cannot be guaranteed absent. The player uses supported `controls=0` and `playsinline` settings.
- Discovery runs through **Actions → Refresh video catalog → Run workflow**, which reads the original `SEARCH_TERMS` and `DIRECT_VIDEO_URLS` from `main.py`, updates stable video IDs, and deploys. It is not continuous per-visitor discovery. The checked-in starter catalog contains 25 Shorts retrieved from the original funny/viral search. Metadata retrieval does not guarantee that every video permits embedding in every region.
- Refresh keeps the last usable catalog if YouTube blocks discovery. It never saves expiring CDN links or downloads/rehosts YouTube media.
- The progress bar measures thumbnail preparation and initial player attempts. A failed player attempt can finish preparation with a visible retry control; 100% does not claim every provider video is playable.
- Browsers can block playback or unmuting. Use the reel's play/retry control if needed. Sound is suspended when the tab is hidden.
- TikTok and Instagram page URLs cannot be used as direct video streams. Their original `yt-dlp` extraction requires a separately hosted backend; that backend is not included or deployed in this Pages-only port.

To preserve the original provider-free playback surface, use browser-playable MP4/WebM files you host and control. Add records to `web/videos.json` with `type: "video"`, a unique `id`, `title`, `url`, and `thumbnail`. Put local assets inside `web/` and use relative URLs. Native playback keeps audio and video on one media timeline. At least six distinct catalog entries are required. YouTube embeds remain supported alongside direct media.

Full live `yt-dlp` discovery and extraction, including TikTok/Instagram, require a separate service outside GitHub Pages. Extracted streams may also require request headers or an authorized media proxy; merely publishing CDN URLs is not a reliable substitute.

## Local development

Requires Node.js 22 or later. There are no packages to install.

```sh
npm test
npm run build
python -m http.server 8000 --directory dist
```

Open `http://localhost:8000`. Use HTTP rather than opening `index.html` as a file, since modules, fetch, and YouTube's origin checks need a served page.

To refresh the catalog locally:

```sh
python -m pip install yt-dlp
python scripts/refresh_catalog.py
npm run build
```

The build copies only the static web app and sounds into `dist/`. Source Python, tests, and workflows are not published. Tests check selection branches, incidental matches, target landing, and the original stop timings; they do not verify live third-party playback.

Platform references: [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages), [YouTube IFrame API](https://developers.google.com/youtube/iframe_api_reference).
