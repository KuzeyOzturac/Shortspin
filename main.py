import sys
import re
import os
import math
import wave
import struct
import shutil
import tempfile
import subprocess
import random
import threading
import queue
import time
import urllib.request
from pathlib import Path
from dataclasses import dataclass
from collections import deque

import yt_dlp

from PySide6.QtCore import Qt, QTimer, Property, QUrl, QPoint
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QPen
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtCore import QPropertyAnimation, QEasingCurve


# ============================================================
# CONFIG
# ============================================================

DIRECT_VIDEO_URLS = [
    # "https://www.youtube.com/shorts/VIDEO_ID",
    # "https://www.tiktok.com/@creator/video/POST_ID",
    # "https://www.instagram.com/reel/SHORTCODE/",
]

SEARCH_TERMS = [
    "funny viral #shorts",
    "animals #shorts",
    "travel #shorts",
    "street food #shorts",
    "science #shorts",
    "technology #shorts",
    "sports #shorts",
    "satisfying #shorts",
    "cinematic #shorts",
    "gaming #shorts",
    "unexpected #shorts",
    "nature #shorts",
    "comedy #shorts",
    "amazing #shorts",
]

SEARCH_BATCH = 12
DISCOVERY_TARGET = 60

# Number of videos whose direct streaming URLs we keep ready in RAM.
STREAM_READY_TARGET = 18

REEL_WIDTH = 290
REEL_HEIGHT = 500

# Purely game-style odds. No money/betting.
JACKPOT_CHANCE = 0.08
PAIR_CHANCE = 0.22


# ============================================================
# DATA
# ============================================================

@dataclass(frozen=True)
class VideoRef:
    platform: str
    video_id: str
    source_url: str
    thumbnail_url: str | None = None

    @property
    def key(self):
        return f"{self.platform}:{self.video_id}"


@dataclass
class StreamInfo:
    url: str
    audio_url: str | None
    resolved_at: float


def parse_direct_url(url: str):
    for pattern in (
        r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})",
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
    ):
        m = re.search(pattern, url)
        if m:
            vid = m.group(1)
            return VideoRef(
                "youtube",
                vid,
                url,
                f"https://i.ytimg.com/vi/{vid}/oar2.jpg",
            )

    m = re.search(r"tiktok\.com/.+?/video/(\d+)", url)
    if m:
        return VideoRef("tiktok", m.group(1), url)

    m = re.search(r"instagram\.com/reel/([^/?#]+)", url)
    if m:
        return VideoRef("instagram", m.group(1), url)

    return None


# ============================================================
# DISCOVERY
# Metadata only. No video media is downloaded.
# ============================================================

class DiscoveryService:
    def __init__(self):
        self.out = queue.Queue()
        self.stop_event = threading.Event()
        self.seen = set()
        self.thread = threading.Thread(target=self._worker, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _worker(self):
        for url in DIRECT_VIDEO_URLS:
            ref = parse_direct_url(url)
            if ref and ref.key not in self.seen:
                self.seen.add(ref.key)
                self.out.put(ref)

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "cachedir": False,
            "noplaylist": True,
            "socket_timeout": 8,
        }

        while not self.stop_event.is_set():
            terms = SEARCH_TERMS[:]
            random.shuffle(terms)
            progress = False

            for term in terms:
                if self.stop_event.is_set():
                    return

                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(
                            f"ytsearch{SEARCH_BATCH}:{term}",
                            download=False,
                        )

                    for entry in (info or {}).get("entries", []) or []:
                        if not entry:
                            continue

                        vid = entry.get("id")
                        if not vid:
                            continue

                        duration = entry.get("duration")
                        if duration and duration > 180:
                            continue

                        key = f"youtube:{vid}"
                        if key in self.seen:
                            continue

                        ref = VideoRef(
                            "youtube",
                            vid,
                            f"https://www.youtube.com/shorts/{vid}",
                            f"https://i.ytimg.com/vi/{vid}/oar2.jpg",
                        )

                        self.seen.add(key)
                        self.out.put(ref)
                        progress = True

                except Exception:
                    pass

                time.sleep(0.30)

                if self.out.qsize() >= DISCOVERY_TARGET:
                    break

            if not progress:
                time.sleep(4)
            elif self.out.qsize() >= DISCOVERY_TARGET:
                time.sleep(6)


# ============================================================
# THUMBNAILS
# Thumbnails are downloaded into RAM only.
# ============================================================

class ThumbnailFetcher:
    def __init__(self):
        self.jobs = queue.Queue()
        self.out = queue.Queue()
        self.stop_event = threading.Event()
        self.queued = set()

        self.threads = [
            threading.Thread(target=self._worker, daemon=True)
            for _ in range(3)
        ]

    def start(self):
        for thread in self.threads:
            thread.start()

    def stop(self):
        self.stop_event.set()

    def request(self, ref):
        if not ref.thumbnail_url or ref.key in self.queued:
            return

        self.queued.add(ref.key)
        self.jobs.put(ref)

    @staticmethod
    def _read(url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/152 Safari/537.36"
                )
            },
        )

        with urllib.request.urlopen(request, timeout=7) as response:
            return response.read()

    def _worker(self):
        while not self.stop_event.is_set():
            try:
                ref = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue

            data = None

            try:
                data = self._read(ref.thumbnail_url)
            except Exception:
                if ref.platform == "youtube":
                    try:
                        fallback = (
                            f"https://i.ytimg.com/vi/{ref.video_id}/hqdefault.jpg"
                        )
                        data = self._read(fallback)
                    except Exception:
                        pass

            if data:
                self.out.put((ref, data))


# ============================================================
# DIRECT STREAM URL RESOLVER
#
# yt-dlp resolves the provider's actual media URL with download=False.
# QMediaPlayer then streams that URL directly.
# No YouTube/TikTok/Instagram iframe is used, so there is no provider UI.
# ============================================================

class StreamResolver:
    def __init__(self):
        self.jobs = queue.Queue()
        self.out = queue.Queue()
        self.stop_event = threading.Event()
        self.queued = set()

        self.threads = [
            threading.Thread(target=self._worker, daemon=True)
            for _ in range(2)
        ]

    def start(self):
        for thread in self.threads:
            thread.start()

    def stop(self):
        self.stop_event.set()

    def request(self, ref):
        if ref.key in self.queued:
            return

        self.queued.add(ref.key)
        self.jobs.put(ref)

    @staticmethod
    def _pick_stream_urls(info):
        formats = info.get("formats") or []

        video_candidates = []
        audio_candidates = []

        for fmt in formats:
            url = fmt.get("url")
            if not url:
                continue

            vcodec = (fmt.get("vcodec") or "").lower()
            acodec = (fmt.get("acodec") or "").lower()
            height = fmt.get("height") or 9999
            ext = (fmt.get("ext") or "").lower()

            # Reliable reel video: H.264/AVC, <= 720p.
            if vcodec and vcodec != "none":
                is_h264 = (
                    vcodec.startswith("avc1")
                    or "h264" in vcodec
                    or "h.264" in vcodec
                )

                if is_h264 and height <= 720:
                    score = (
                        0 if ext == "mp4" else 1,
                        abs(height - 480),
                        -(fmt.get("fps") or 0),
                    )
                    video_candidates.append((score, url))

            # Independent audio-only stream. It is used ONLY on jackpot.
            if (
                acodec
                and acodec != "none"
                and (not vcodec or vcodec == "none")
            ):
                abr = fmt.get("abr") or 0
                audio_candidates.append((-abr, url))

        video_url = None
        audio_url = None

        if video_candidates:
            video_candidates.sort(key=lambda item: item[0])
            video_url = video_candidates[0][1]

        if audio_candidates:
            audio_candidates.sort(key=lambda item: item[0])
            audio_url = audio_candidates[0][1]

        # Fallback for extractors that expose one direct H.264 stream.
        if not video_url:
            direct = info.get("url")
            direct_codec = (info.get("vcodec") or "").lower()

            if direct and (
                direct_codec.startswith("avc1")
                or "h264" in direct_codec
                or "h.264" in direct_codec
            ):
                video_url = direct

        return video_url, audio_url

    def _resolve(self, ref):
        # Do not request a strict combined video+audio format. Many Shorts do
        # not expose one, which caused the "Requested format is not available"
        # errors. Instead, retrieve metadata and select video/audio separately.
        class SilentLogger:
            def debug(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                pass

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cachedir": False,
            "noplaylist": True,
            "socket_timeout": 8,
            "ignoreerrors": True,
            "logger": SilentLogger(),
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                ref.source_url,
                download=False,
            )

        if not info:
            return None

        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            info = next((entry for entry in entries if entry), None)
            if not info:
                return None

        video_url, audio_url = self._pick_stream_urls(info)

        if not video_url:
            return None

        return video_url, audio_url

    def _worker(self):
        while not self.stop_event.is_set():
            try:
                ref = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                resolved = self._resolve(ref)
            except Exception:
                resolved = None

            if resolved:
                video_url, audio_url = resolved

                self.out.put(
                    (
                        ref,
                        StreamInfo(
                            url=video_url,
                            audio_url=audio_url,
                            resolved_at=time.time(),
                        ),
                    )
                )
            else:
                # Allow a later retry if extraction failed.
                self.queued.discard(ref.key)


# ============================================================
# THUMBNAIL REEL ANIMATION
# ============================================================

class ThumbnailReelSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_pixmap = QPixmap()
        self.next_pixmap = QPixmap()

        self._offset = 0.0
        self.sequence = []
        self.durations = []
        self.finished_callback = None
        self.animation = None

        self.setStyleSheet("background:#000;")

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def set_current(self, pixmap):
        if pixmap and not pixmap.isNull():
            self.current_pixmap = pixmap
            self.update()

    def start_sequence(self, pixmaps, durations, finished_callback):
        self.sequence = list(pixmaps)
        self.durations = list(durations)
        self.finished_callback = finished_callback
        self._run_next()

    def _run_next(self):
        if not self.sequence:
            callback = self.finished_callback
            self.finished_callback = None

            if callback:
                callback()
            return

        self.next_pixmap = self.sequence.pop(0)
        duration = self.durations.pop(0)

        anim = QPropertyAnimation(self, b"offset", self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.Linear)

        def done():
            self.current_pixmap = self.next_pixmap
            self.next_pixmap = QPixmap()
            self._offset = 0.0
            self.update()
            QTimer.singleShot(0, self._run_next)

        anim.finished.connect(done)
        self.animation = anim
        anim.start()

    @staticmethod
    def _source_rect_for_fill(pixmap, target_w, target_h):
        if pixmap.isNull():
            return pixmap.rect()

        src_w = pixmap.width()
        src_h = pixmap.height()

        src_ratio = src_w / src_h
        target_ratio = target_w / target_h

        if src_ratio > target_ratio:
            wanted_w = int(src_h * target_ratio)
            x = (src_w - wanted_w) // 2
            return pixmap.rect().adjusted(x, 0, -(src_w - wanted_w - x), 0)

        wanted_h = int(src_w / target_ratio)
        y = (src_h - wanted_h) // 2
        return pixmap.rect().adjusted(0, y, 0, -(src_h - wanted_h - y))

    def _draw_filled(self, painter, pixmap, y):
        target = self.rect()
        target.moveTop(int(y))

        if pixmap.isNull():
            painter.fillRect(target, QColor(15, 15, 15))
            return

        source = self._source_rect_for_fill(
            pixmap,
            self.width(),
            self.height(),
        )

        painter.drawPixmap(target, pixmap, source)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        painter.fillRect(self.rect(), QColor(0, 0, 0))

        h = self.height()

        self._draw_filled(
            painter,
            self.current_pixmap,
            -self._offset * h,
        )

        if not self.next_pixmap.isNull():
            self._draw_filled(
                painter,
                self.next_pixmap,
                (1.0 - self._offset) * h,
            )

        if self._offset > 0:
            # Slight motion veil + streaks.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 28))
            painter.setPen(QColor(255, 255, 255, 50))

            for x in range(18, self.width(), 34):
                base = int((self._offset * 190 + x * 2) % 120)
                y = base - 80

                while y < h:
                    painter.drawLine(x, y, x, y + 55)
                    y += 120



# ============================================================
# ARCADE SOUND ENGINE
#
# Effects are synthesized at runtime. No external sound pack is required.
# Temporary WAV files contain only the generated UI effects, never the reels.
# ============================================================

class ArcadeAudio:
    """
    Plays the user's actual MP3 effects from:

        sounds/click_spin.mp3
        sounds/spin.mp3
        sounds/lock.mp3
        sounds/win.mp3

    Paths are resolved relative to this Python file, so the project should be:

        reelsslots/
            main.py
            sounds/
                click_spin.mp3
                spin.mp3
                lock.mp3
                win.mp3

    QMediaPlayer is used instead of QSoundEffect because it is much more
    reliable for MP3 playback on macOS/PySide6.
    """

    def __init__(self, parent):
        self.parent = parent

        base_dir = Path(__file__).resolve().parent
        self.sound_dir = base_dir / "sounds"

        self.paths = {
            "click": self.sound_dir / "click_spin.mp3",
            "spin": self.sound_dir / "spin.mp3",
            "lock": self.sound_dir / "lock.mp3",
            "win": self.sound_dir / "win.mp3",
            "two_matched": self.sound_dir / "two_matched.mp3",
            "loading": self.sound_dir / "loading.mp3",
            "loaded": self.sound_dir / "loaded.mp3",
        }

        missing = [
            str(path)
            for path in self.paths.values()
            if not path.is_file()
        ]

        self.enabled = not missing

        if missing:
            print("SOUND FILES MISSING:")
            for path in missing:
                print("  ", path)
        else:
            print("Sound files loaded from:", self.sound_dir)

        # Separate players let click/lock/win fire immediately without waiting
        # for another effect to finish.
        self.click_player, self.click_output = self._make_player(0.95)
        self.spin_player, self.spin_output = self._make_player(0.72)
        self.win_player, self.win_output = self._make_player(1.00)
        self.two_matched_player, self.two_matched_output = self._make_player(1.00)
        self.loading_player, self.loading_output = self._make_player(0.85)
        self.loaded_player, self.loaded_output = self._make_player(1.00)

        # Three lock players form a tiny pool, so a second reel can lock before
        # the previous lock sound has completely decayed.
        self.lock_players = []
        for _ in range(3):
            player, output = self._make_player(1.00)
            self.lock_players.append((player, output))

        self._next_lock_player = 0
        self._spin_should_loop = False
        self._loading_should_loop = False

        self.spin_player.mediaStatusChanged.connect(
            self._spin_status_changed
        )
        self.loading_player.mediaStatusChanged.connect(
            self._loading_status_changed
        )

        if self.enabled:
            self.click_player.setSource(
                QUrl.fromLocalFile(str(self.paths["click"]))
            )
            self.spin_player.setSource(
                QUrl.fromLocalFile(str(self.paths["spin"]))
            )
            self.win_player.setSource(
                QUrl.fromLocalFile(str(self.paths["win"]))
            )
            self.two_matched_player.setSource(
                QUrl.fromLocalFile(str(self.paths["two_matched"]))
            )
            self.loading_player.setSource(
                QUrl.fromLocalFile(str(self.paths["loading"]))
            )
            self.loaded_player.setSource(
                QUrl.fromLocalFile(str(self.paths["loaded"]))
            )

            for player, _ in self.lock_players:
                player.setSource(
                    QUrl.fromLocalFile(str(self.paths["lock"]))
                )

    def _make_player(self, volume):
        player = QMediaPlayer(self.parent)
        output = QAudioOutput(self.parent)

        output.setMuted(False)
        output.setVolume(volume)

        player.setAudioOutput(output)

        return player, output

    def _restart(self, player):
        if not self.enabled:
            return

        player.stop()
        player.setPosition(0)
        player.play()

    def start_loading(self):
        if not self.enabled:
            return

        self._loading_should_loop = True
        self._restart(self.loading_player)

    def _loading_status_changed(self, status):
        if (
            self.enabled
            and self._loading_should_loop
            and status == QMediaPlayer.MediaStatus.EndOfMedia
        ):
            self.loading_player.setPosition(0)
            self.loading_player.play()

    def finish_loading(self):
        if not self.enabled:
            return

        # Cut loading.mp3 immediately and transition directly to loaded.mp3.
        self._loading_should_loop = False
        self.loading_player.stop()
        self._restart(self.loaded_player)

    def play_click(self):
        self._restart(self.click_player)

    def start_spin(self):
        if not self.enabled:
            return

        self._spin_should_loop = True
        self._restart(self.spin_player)

    def stop_spin(self):
        self._spin_should_loop = False
        self.spin_player.stop()

    def _spin_status_changed(self, status):
        if (
            self.enabled
            and self._spin_should_loop
            and status == QMediaPlayer.MediaStatus.EndOfMedia
        ):
            self.spin_player.setPosition(0)
            self.spin_player.play()

    def play_lock(self):
        if not self.enabled:
            return

        player, _ = self.lock_players[
            self._next_lock_player % len(self.lock_players)
        ]
        self._next_lock_player += 1

        self._restart(player)

    def cut_spin_to_lock(self):
        """
        The currently-running spin sound stops on the exact reel-lock callback,
        then lock.mp3 fires immediately.
        """
        self.spin_player.stop()
        self.play_lock()

    def resume_spin(self):
        """
        Called after an earlier reel locks while later reels are still moving.
        """
        if not self.enabled:
            return

        self._spin_should_loop = True
        self._restart(self.spin_player)

    def play_win(self):
        if not self.enabled:
            return

        self.stop_spin()
        self._restart(self.win_player)

    def play_two_matched(self):
        if not self.enabled:
            return

        self.stop_spin()
        self._restart(self.two_matched_player)

    def close(self):
        self._spin_should_loop = False

        self._loading_should_loop = False

        self.click_player.stop()
        self.spin_player.stop()
        self.win_player.stop()
        self.two_matched_player.stop()
        self.loading_player.stop()
        self.loaded_player.stop()

        for player, _ in self.lock_players:
            player.stop()


# ============================================================
# FULL-WINDOW VISUAL FX
# ============================================================

class FXOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self.spin_active = False
        self.phase = 0.0
        self.flash_alpha = 0.0
        self.particles = []

        self.palette = [
            QColor("#ffd84d"),
            QColor("#ffffff"),
            QColor("#ff7a59"),
            QColor("#55e6c1"),
            QColor("#7db7ff"),
            QColor("#c28cff"),
        ]

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.hide()

    def _ensure_running(self):
        self.show()
        self.raise_()

        if not self.timer.isActive():
            self.timer.start()

    def start_spin(self):
        self.spin_active = True
        self.phase = 0.0
        self._ensure_running()

    def stop_spin(self):
        self.spin_active = False

        if not self.particles and self.flash_alpha <= 0:
            self.timer.stop()
            self.hide()

    def burst_at(self, point, count=26):
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(90, 270)

            self.particles.append(
                {
                    "x": float(point.x()),
                    "y": float(point.y()),
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed - 65,
                    "life": random.uniform(0.28, 0.58),
                    "age": 0.0,
                    "size": random.uniform(2.5, 6.0),
                    "color": random.choice(self.palette),
                    "confetti": False,
                    "spin": random.uniform(-9, 9),
                    "angle": random.uniform(0, math.tau),
                }
            )

        self.flash_alpha = max(self.flash_alpha, 90)
        self._ensure_running()

    def pair_celebration(self):
        center = QPoint(self.width() // 2, self.height() // 2)

        self.burst_at(center, count=58)
        self.flash_alpha = 115
        self._ensure_running()

    def jackpot_celebration(self):
        width = max(1, self.width())

        for _ in range(170):
            self.particles.append(
                {
                    "x": random.uniform(0, width),
                    "y": random.uniform(-120, 10),
                    "vx": random.uniform(-85, 85),
                    "vy": random.uniform(110, 330),
                    "life": random.uniform(1.4, 2.7),
                    "age": 0.0,
                    "size": random.uniform(4.5, 9.5),
                    "color": random.choice(self.palette),
                    "confetti": True,
                    "spin": random.uniform(-12, 12),
                    "angle": random.uniform(0, math.tau),
                }
            )

        self.flash_alpha = 185
        self._ensure_running()

    def _tick(self):
        dt = 0.016
        self.phase += dt

        alive = []

        for p in self.particles:
            p["age"] += dt

            if p["age"] >= p["life"]:
                continue

            p["vy"] += 260 * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["angle"] += p["spin"] * dt

            alive.append(p)

        self.particles = alive
        self.flash_alpha = max(
            0.0,
            self.flash_alpha - 235 * dt,
        )

        self.update()

        if (
            not self.spin_active
            and not self.particles
            and self.flash_alpha <= 0
        ):
            self.timer.stop()
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
        )

        # Very light motion-energy frame during the spin.
        if self.spin_active:
            pulse = 0.5 + 0.5 * math.sin(self.phase * 14)

            edge_alpha = int(32 + 24 * pulse)
            pen = QPen(
                QColor(255, 215, 70, edge_alpha),
                4,
            )
            painter.setPen(pen)
            painter.drawRoundedRect(
                self.rect().adjusted(5, 5, -5, -5),
                18,
                18,
            )

            # Fast diagonal streaks around the edges only.
            painter.setPen(
                QPen(
                    QColor(255, 255, 255, 24),
                    2,
                )
            )

            offset = int((self.phase * 700) % 90)

            for x in range(-100 + offset, self.width() + 100, 90):
                painter.drawLine(
                    x,
                    0,
                    x + 52,
                    38,
                )
                painter.drawLine(
                    x,
                    self.height(),
                    x + 52,
                    self.height() - 38,
                )

        if self.flash_alpha > 0:
            painter.fillRect(
                self.rect(),
                QColor(
                    255,
                    225,
                    90,
                    int(self.flash_alpha),
                ),
            )

        for p in self.particles:
            progress = p["age"] / p["life"]
            alpha = int(255 * (1.0 - progress))

            color = QColor(p["color"])
            color.setAlpha(alpha)

            painter.save()
            painter.translate(p["x"], p["y"])
            painter.rotate(math.degrees(p["angle"]))

            if p["confetti"]:
                painter.fillRect(
                    int(-p["size"]),
                    int(-p["size"] * 0.45),
                    int(p["size"] * 2),
                    int(p["size"] * 0.9),
                    color,
                )
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(
                    QPoint(0, 0),
                    int(p["size"]),
                    int(p["size"]),
                )

            painter.restore()



# ============================================================
# NATIVE VIDEO REEL
# No embedded webpage. Therefore no title, channel, play/pause, skip,
# YouTube logo, or hover controls can appear.
# ============================================================

class ReelWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedSize(REEL_WIDTH, REEL_HEIGHT)
        self.setStyleSheet("""
            QFrame {
                background:#000;
                border:3px solid #666;
                border-radius:18px;
            }
        """)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setGeometry(
            4, 4, REEL_WIDTH - 8, REEL_HEIGHT - 8
        )
        self.video_widget.setAspectRatioMode(
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )

        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.audio.setVolume(1.0)

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        # Separate remote audio-only player used only after JACKPOT.
        self.jackpot_audio_output = QAudioOutput(self)
        self.jackpot_audio_output.setMuted(False)
        self.jackpot_audio_output.setVolume(1.0)

        self.jackpot_audio_player = QMediaPlayer(self)
        self.jackpot_audio_player.setAudioOutput(
            self.jackpot_audio_output
        )

        self.current_audio_url = None

        # Keeps the separate jackpot audio stream locked to the exact
        # position of the visible Short.
        self._jackpot_audio_sync_active = False
        self._jackpot_audio_unmuted = False
        self.jackpot_sync_timer = QTimer(self)
        self.jackpot_sync_timer.setInterval(120)
        self.jackpot_sync_timer.timeout.connect(
            self._sync_jackpot_audio
        )

        self.player.mediaStatusChanged.connect(
            self._media_status_changed
        )

        self.spinner = ThumbnailReelSurface(self)
        self.spinner.setGeometry(
            4, 4, REEL_WIDTH - 8, REEL_HEIGHT - 8
        )
        self.spinner.hide()

        self.current_ref = None
        self.current_pixmap = QPixmap()
        self.target_ref = None
        self.target_pixmap = None
        self.target_audio_url = None

        # Never reveal a black native video surface. We keep the landed
        # thumbnail on screen until QMediaPlayer is actually advancing.
        self._reveal_generation = 0
        self._lock_completed = False

    def mute_video_audio(self):
        self.audio.setMuted(True)

        self._jackpot_audio_sync_active = False
        self._jackpot_audio_unmuted = False
        self.jackpot_sync_timer.stop()

        self.jackpot_audio_output.setMuted(True)
        self.jackpot_audio_player.stop()

    def play_video_audio(self):
        """
        Play the winning Short's audio without changing the video stream.

        The video and audio URLs are separate YouTube streams, so simply
        starting them together can produce noticeable drift. We initially
        buffer the audio while muted, seek it to the live video position, then
        keep correcting small drift while the jackpot view remains open.
        """
        if not self.current_audio_url:
            return

        self._jackpot_audio_sync_active = True
        self._jackpot_audio_unmuted = False

        # Never let an unsynchronised beginning leak through.
        self.jackpot_audio_output.setMuted(True)
        self.jackpot_audio_player.stop()
        self.jackpot_audio_player.setSource(
            QUrl(self.current_audio_url)
        )
        self.jackpot_audio_player.play()

        self.jackpot_sync_timer.start()

        # Run a few eager checks while the remote audio stream starts.
        QTimer.singleShot(40, self._sync_jackpot_audio)
        QTimer.singleShot(100, self._sync_jackpot_audio)
        QTimer.singleShot(180, self._sync_jackpot_audio)

    def _sync_jackpot_audio(self):
        if not self._jackpot_audio_sync_active:
            return

        video_pos = max(0, self.player.position())
        audio_state = self.jackpot_audio_player.playbackState()
        audio_status = self.jackpot_audio_player.mediaStatus()

        usable_statuses = (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )

        if audio_status not in usable_statuses:
            # Keep asking the player to buffer, but stay muted.
            if (
                audio_state
                != QMediaPlayer.PlaybackState.PlayingState
            ):
                self.jackpot_audio_player.play()
            return

        audio_pos = max(
            0,
            self.jackpot_audio_player.position(),
        )

        drift = abs(audio_pos - video_pos)

        # Initial alignment is forced. Afterwards, only correct meaningful
        # drift so playback remains smooth rather than constantly seeking.
        if (
            not self._jackpot_audio_unmuted
            or drift > 140
        ):
            self.jackpot_audio_player.setPosition(
                video_pos
            )

        if (
            audio_state
            != QMediaPlayer.PlaybackState.PlayingState
        ):
            self.jackpot_audio_player.play()

        if not self._jackpot_audio_unmuted:
            # Give the seek one event-loop cycle to take effect, then reveal
            # the audio at the same point as the visible Short.
            self._jackpot_audio_unmuted = True

            QTimer.singleShot(
                55,
                lambda: (
                    self.jackpot_audio_output.setMuted(False)
                    if self._jackpot_audio_sync_active
                    else None
                ),
            )

    def _media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.play()

    def set_initial(self, ref, pixmap, stream_url, audio_url=None):
        self.current_ref = ref
        self.current_pixmap = pixmap
        self.current_audio_url = audio_url

        # Show the thumbnail first so startup can never flash a black reel.
        self.video_widget.hide()
        self.spinner.set_current(pixmap)
        self.spinner.show()
        self.spinner.raise_()

        self.player.setSource(QUrl(stream_url))
        self.player.play()

        self._reveal_generation += 1
        generation = self._reveal_generation
        self._wait_for_initial_video(generation, 0)

    def _wait_for_initial_video(self, generation, waited_ms):
        if generation != self._reveal_generation:
            return

        if self.player.error() != QMediaPlayer.Error.NoError:
            # Keep the thumbnail rather than exposing a failed/black surface.
            return

        playing = (
            self.player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )
        advancing = self.player.position() >= 80

        if playing and advancing:
            self.spinner.hide()
            self.video_widget.show()
            self.video_widget.raise_()
            return

        if waited_ms >= 2400:
            # The stream is unusually slow or failed silently. The thumbnail
            # stays visible; the next spin can move on immediately.
            return

        if waited_ms in (700, 1400):
            self.player.play()

        QTimer.singleShot(
            80,
            lambda: self._wait_for_initial_video(
                generation,
                waited_ms + 80,
            ),
        )

    def begin_spin(
        self,
        target_ref,
        target_pixmap,
        stream_url,
        audio_url,
        sequence_pixmaps,
        durations,
        on_locked,
    ):
        self.target_ref = target_ref
        self.target_pixmap = target_pixmap
        self.target_audio_url = audio_url
        self._lock_completed = False
        self._reveal_generation += 1

        # Hide the native video surface while spinning.
        #
        # QVideoWidget uses a native video surface on macOS, which can stay
        # visually above ordinary Qt child widgets even when spinner.raise_()
        # is called. That is why the previous version appeared to "lose" the
        # thumbnail reel animation.
        #
        # We hide only the video WIDGET. QMediaPlayer continues buffering and
        # playing the selected online stream in the background.
        self.video_widget.hide()

        self.player.stop()
        self.player.setSource(QUrl(stream_url))
        self.player.play()

        # Restore the original fast vertical thumbnail reel.
        self.spinner.set_current(self.current_pixmap)
        self.spinner.show()
        self.spinner.raise_()

        self.spinner.start_sequence(
            sequence_pixmaps,
            durations,
            lambda: self._finish_spin(on_locked),
        )

    def _finish_spin(self, on_locked):
        # At this point the spinner is already sitting on the exact target
        # thumbnail. Keep it visible while we verify that the native stream
        # has produced playable frames.
        generation = self._reveal_generation

        QTimer.singleShot(
            90,
            lambda: self._wait_for_target_video(
                generation,
                on_locked,
                0,
            ),
        )

    def _wait_for_target_video(
        self,
        generation,
        on_locked,
        waited_ms,
    ):
        if generation != self._reveal_generation:
            return

        if self._lock_completed:
            return

        media_error = (
            self.player.error()
            != QMediaPlayer.Error.NoError
        )

        playing = (
            self.player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )

        # position() moving is a much better signal than "LoadedMedia":
        # it means Qt is actually decoding/advancing the selected stream.
        advancing = self.player.position() >= 80

        if not media_error and playing and advancing:
            self._commit_target(
                on_locked,
                reveal_video=True,
            )
            return

        # Give normal network buffering a little time. During this entire
        # period the landed thumbnail remains visible, never a black rectangle.
        if waited_ms < 2600 and not media_error:
            if waited_ms in (700, 1400, 2100):
                self.player.play()

            QTimer.singleShot(
                80,
                lambda: self._wait_for_target_video(
                    generation,
                    on_locked,
                    waited_ms + 80,
                ),
            )
            return

        # Failed, unsupported, or extremely slow stream:
        # commit the slot result but leave its thumbnail visible. This is much
        # better than revealing a black frame, and the next spin is unaffected.
        self._commit_target(
            on_locked,
            reveal_video=False,
        )

    def _commit_target(self, on_locked, reveal_video):
        if self._lock_completed:
            return

        self._lock_completed = True

        self.current_ref = self.target_ref
        self.current_pixmap = self.target_pixmap
        self.current_audio_url = self.target_audio_url

        self.target_ref = None
        self.target_pixmap = None
        self.target_audio_url = None

        if reveal_video:
            self.spinner.hide()
            self.video_widget.show()
            self.video_widget.raise_()
        else:
            self.video_widget.hide()
            self.spinner.set_current(self.current_pixmap)
            self.spinner.show()
            self.spinner.raise_()

        self.flash_border()
        on_locked()

    def set_display_size(self, width, height):
        """
        Resize the reel frame and every internal visual surface together.
        This is used only for the post-jackpot expanded view.
        """
        self.setFixedSize(width, height)

        inner_width = max(1, width - 8)
        inner_height = max(1, height - 8)

        self.video_widget.setGeometry(
            4,
            4,
            inner_width,
            inner_height,
        )
        self.spinner.setGeometry(
            4,
            4,
            inner_width,
            inner_height,
        )

    def set_spin_glow(self, phase):
        # Small color/width variation makes the three reel frames feel alive
        # without touching the video or thumbnail animation itself.
        wave_value = 0.5 + 0.5 * math.sin(
            phase + id(self) % 7
        )

        red = 238 + int(17 * wave_value)
        green = 176 + int(48 * wave_value)
        blue = 45 + int(22 * wave_value)
        width = 3 + int(wave_value * 2)

        self.setStyleSheet(
            f"""
            QFrame {{
                background:#000;
                border:{width}px solid rgb({red},{green},{blue});
                border-radius:18px;
            }}
            """
        )

    def reset_border(self):
        self.setStyleSheet("""
            QFrame {
                background:#000;
                border:3px solid #666;
                border-radius:18px;
            }
        """)

    def flash_border(self):
        self.setStyleSheet("""
            QFrame {
                background:#000;
                border:5px solid #fff0a3;
                border-radius:18px;
            }
        """)

        QTimer.singleShot(
            170,
            self.reset_border,
        )


# ============================================================
# MAIN APP
# ============================================================

class ReelMachine(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Shorts Spinning Machine")
        self.setMinimumSize(1000, 720)

        self.discovery = DiscoveryService()
        self.thumbnails = ThumbnailFetcher()
        self.streams = StreamResolver()

        self.discovery.start()
        self.thumbnails.start()
        self.streams.start()

        self.refs = {}
        self.pixmaps = {}
        self.stream_info = {}

        self.thumbnail_ready = deque(maxlen=120)
        self.thumbnail_ready_set = set()

        self.stream_ready = deque(maxlen=80)
        self.stream_ready_set = set()

        self.spinning = False
        self.lock_count = 0
        self.locked_reels = set()
        self.fx_phase = 0.0
        self.jackpot_expanded = False

        self.audio_fx = ArcadeAudio(self)


        self.spin_fx_timer = QTimer(self)
        self.spin_fx_timer.setInterval(70)
        self.spin_fx_timer.timeout.connect(
            self._spin_fx_tick
        )

        root = QWidget()
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(14)

        title = QLabel("SHORTSPIN")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(
            QFont("Arial", 30, QFont.Weight.Bold)
        )
        layout.addWidget(title)

        reel_row = QHBoxLayout()
        reel_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reel_row.setSpacing(16)
        self.reel_row = reel_row

        self.reels = [
            ReelWidget(),
            ReelWidget(),
            ReelWidget(),
        ]

        for reel in self.reels:
            reel_row.addWidget(reel)

        layout.addLayout(reel_row)

        self.result = QLabel("Preparing streams…")
        self.result.setObjectName("resultLabel")
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setFont(
            QFont("Arial", 19, QFont.Weight.Bold)
        )
        layout.addWidget(self.result)

        self.spin_button = QPushButton("PREPARING 0%")
        self.spin_button.setObjectName("spinButton")
        self.spin_button.setEnabled(False)
        self.spin_button.setFixedHeight(58)
        self.spin_button.setFont(
            QFont("Arial", 20, QFont.Weight.Bold)
        )
        self.spin_button.clicked.connect(self.spin)

        # Smooth loading animation. Background preparation still reports real
        # progress in discrete steps, but the bar glides continuously between
        # those values instead of jumping 0 -> 17 -> 33 -> ...
        self.loading_progress_value = 0.0
        self.loading_progress_target = 0.0
        self.loading_progress_complete = False

        self.loading_progress_timer = QTimer(self)
        self.loading_progress_timer.setInterval(16)
        self.loading_progress_timer.timeout.connect(
            self._animate_stream_progress
        )
        self.loading_progress_timer.start()

        self._render_stream_progress(0.0)

        # loading.mp3 begins on the exact first visual movement of the bar,
        # not earlier during window setup.
        self.loading_audio_started = False

        layout.addWidget(
            self.spin_button,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        root.setStyleSheet("""
            QWidget {
                background:#121212;
                color:white;
            }
        """)

        self.root_widget = root
        self.fx_overlay = FXOverlay(root)
        self.fx_overlay.setGeometry(root.rect())
        self.fx_overlay.raise_()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(
            self.poll_background_work
        )
        self.poll_timer.start(100)

    def _set_stream_progress(self, ready_count, target_count=6):
        """
        Set the real preparation target. The visible fill is animated toward
        this value by _animate_stream_progress().
        """
        target_count = max(1, target_count)
        clamped = max(
            0,
            min(ready_count, target_count),
        )

        self.loading_progress_target = (
            clamped / target_count
        )

    def _animate_stream_progress(self):
        if self.loading_progress_complete:
            self.loading_progress_timer.stop()
            return

        target = self.loading_progress_target
        current = self.loading_progress_value

        if current < target:
            # Time-based-looking interpolation at ~60 FPS. The minimum step
            # prevents the final few pixels from crawling forever.
            distance = target - current
            step = max(
                0.0025,
                distance * 0.085,
            )
            current = min(
                target,
                current + step,
            )

        self.loading_progress_value = current

        # The sound begins on the same animation tick where the loading bar
        # first becomes visibly filled.
        if (
            current > 0.0
            and not self.loading_audio_started
        ):
            self.loading_audio_started = True
            self.audio_fx.start_loading()

        self._render_stream_progress(current)

        if (
            target >= 1.0
            and current >= 0.999
        ):
            # Complete the visual bar and cut the loading sound on this exact
            # same animation tick, then immediately play loaded.mp3.
            self.loading_progress_value = 1.0
            self.loading_progress_complete = True
            self._render_stream_progress(1.0)

            self.audio_fx.finish_loading()

            self.loading_progress_timer.stop()
            self.spin_button.setEnabled(True)
            self.result.setText("Press SPIN")

    def _render_stream_progress(self, progress):
        progress = max(
            0.0,
            min(1.0, progress),
        )

        if progress >= 0.999:
            self.spin_button.setText("SPIN")
            self.spin_button.setStyleSheet("""
                QPushButton {
                    border:2px solid #ffe991;
                    border-radius:16px;
                    background:#f5cc32;
                    color:#111;
                    padding:10px 42px;
                }
                QPushButton:hover:!disabled {
                    background:#ffe36d;
                    border:2px solid white;
                }
                QPushButton:pressed:!disabled {
                    background:#ddb428;
                    padding-top:13px;
                    padding-bottom:7px;
                }
            """)
            return

        percent = int(round(progress * 100))

        # Two adjacent stops form the edge; because progress itself moves every
        # 16 ms, the fill travels smoothly across the entire button.
        edge = progress
        after_edge = min(
            1.0,
            edge + 0.002,
        )

        self.spin_button.setText(
            f"PREPARING {percent}%"
        )
        self.spin_button.setStyleSheet(
            f"""
            QPushButton {{
                border:2px solid #6f642f;
                border-radius:16px;
                background:qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f5cc32,
                    stop:{edge:.4f} #f5cc32,
                    stop:{after_edge:.4f} #444444,
                    stop:1 #444444
                );
                color:white;
                padding:10px 42px;
            }}
            """
        )

    def poll_background_work(self):
        # New metadata.
        for _ in range(30):
            try:
                ref = self.discovery.out.get_nowait()
            except queue.Empty:
                break

            self.refs[ref.key] = ref
            self.thumbnails.request(ref)

        # New thumbnails.
        for _ in range(30):
            try:
                ref, data = self.thumbnails.out.get_nowait()
            except queue.Empty:
                break

            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                continue

            self.refs[ref.key] = ref
            self.pixmaps[ref.key] = pixmap

            if ref.key not in self.thumbnail_ready_set:
                self.thumbnail_ready_set.add(ref.key)
                self.thumbnail_ready.append(ref.key)

            # Direct stream resolution begins only after we have a thumbnail.
            if len(self.stream_ready_set) < STREAM_READY_TARGET:
                self.streams.request(ref)

        # New direct streaming URLs.
        for _ in range(20):
            try:
                ref, info = self.streams.out.get_nowait()
            except queue.Empty:
                break

            self.refs[ref.key] = ref
            self.stream_info[ref.key] = info

            if ref.key not in self.stream_ready_set:
                self.stream_ready_set.add(ref.key)
                self.stream_ready.append(ref.key)

        # Keep filling the ready stream pool from thumbnail-ready refs.
        if len(self.stream_ready_set) < STREAM_READY_TARGET:
            for key in list(self.thumbnail_ready):
                if key in self.stream_ready_set:
                    continue

                ref = self.refs.get(key)
                if ref:
                    self.streams.request(ref)

                if len(self.streams.queued) >= STREAM_READY_TARGET * 2:
                    break

        ready = [
            key for key in self.stream_ready
            if key in self.pixmaps
            and key in self.stream_info
        ]

        # The button fills from 0% to 100% as the first six usable streams
        # become ready. The rest of the stream pool can keep growing afterward.
        if not self.reels[0].current_ref:
            self._set_stream_progress(
                min(len(ready), 6),
                6,
            )

        if len(ready) >= 6 and not self.reels[0].current_ref:
            initial_keys = random.sample(ready, 3)

            for reel, key in zip(self.reels, initial_keys):
                reel.set_initial(
                    self.refs[key],
                    self.pixmaps[key],
                    self.stream_info[key].url,
                    self.stream_info[key].audio_url,
                )

            self._set_stream_progress(6, 6)

    def usable_stream_keys(self):
        now = time.time()

        # Resolved provider URLs normally live much longer than this, but
        # refreshing them after 25 min avoids stale CDN links in long sessions.
        return [
            key
            for key in self.stream_ready
            if key in self.pixmaps
            and key in self.stream_info
            and now - self.stream_info[key].resolved_at < 1500
        ]

    def choose_target_keys(self):
        ready = self.usable_stream_keys()

        roll = random.random()

        if roll < JACKPOT_CHANCE:
            key = random.choice(ready)
            return [key, key, key]

        if roll < JACKPOT_CHANCE + PAIR_CHANCE:
            pair = random.choice(ready)
            others = [
                key for key in ready
                if key != pair
            ]
            other = random.choice(others or ready)

            result = [pair, pair, other]
            random.shuffle(result)
            return result

        return [
            random.choice(ready),
            random.choice(ready),
            random.choice(ready),
        ]

    @staticmethod
    def spin_durations(reel_index):
        # Rapid cascade, then a distinct deceleration.
        presets = [
            [58] * 9 + [70] * 4 + [86] * 3 + [115, 150, 215],
            [58] * 11 + [70] * 5 + [88] * 3 + [120, 160, 225, 290],
            [58] * 13 + [72] * 6 + [90] * 4 + [125, 170, 235, 310, 380],
        ]
        return presets[reel_index]

    def make_thumbnail_sequence(self, target_key, durations):
        ready = list(self.thumbnail_ready)

        sequence_keys = []
        previous = None

        for _ in range(len(durations) - 1):
            choices = [
                key
                for key in ready
                if key in self.pixmaps
                and key != previous
                and key != target_key
            ]

            if not choices:
                choices = [
                    key for key in ready
                    if key in self.pixmaps
                ]

            key = random.choice(choices)
            sequence_keys.append(key)
            previous = key

        # Final physical reel position = selected video.
        sequence_keys.append(target_key)

        return [
            self.pixmaps[key]
            for key in sequence_keys
        ]

    def _expand_jackpot_reel(self):
        if self.jackpot_expanded:
            return

        self.jackpot_expanded = True

        # The matching video is identical in all three positions. Keep the
        # first reel, remove the other two from view, and enlarge the survivor.
        self.reels[1].hide()
        self.reels[2].hide()

        # Expand horizontally while keeping the original 500 px height.
        # That preserves the full vertical layout, so JACKPOT, the result line,
        # and the SPIN button stay visible.
        self.reels[0].set_display_size(
            430,
            REEL_HEIGHT,
        )

        self.reel_row.setSpacing(0)

    def _restore_three_reels(self):
        if not self.jackpot_expanded:
            return

        self.jackpot_expanded = False

        self.reels[0].set_display_size(
            REEL_WIDTH,
            REEL_HEIGHT,
        )

        self.reels[1].show()
        self.reels[2].show()

        self.reel_row.setSpacing(16)

    def spin(self):
        ready = self.usable_stream_keys()

        if self.spinning or len(ready) < 6:
            return

        # A jackpot keeps one expanded Short on screen until the player spins
        # again. Restore the original three-reel layout before the next spin.
        self._restore_three_reels()

        self.spinning = True
        self.lock_count = 0
        self.locked_reels.clear()
        self.fx_phase = 0.0

        # Reel content audio is normally silent. A single reel is unmuted only
        # after a JACKPOT; the next spin immediately mutes it again.
        for reel in self.reels:
            reel.mute_video_audio()

        self.spin_button.setEnabled(False)
        self.spin_button.setText("SPINNING")

        self.result.setText("SPINNING")
        self.result.setStyleSheet(
            "color:white;font-size:19px;font-weight:900;"
        )

        # User-provided audio:
        # click_spin.mp3 fires on the button press, then spin.mp3 runs while
        # the reels are in motion.
        self.audio_fx.play_click()
        self.audio_fx.start_spin()

        self.fx_overlay.start_spin()
        self.spin_fx_timer.start()

        target_keys = self.choose_target_keys()

        for i, reel in enumerate(self.reels):
            key = target_keys[i]

            durations = self.spin_durations(i)
            sequence = self.make_thumbnail_sequence(
                key,
                durations,
            )

            reel.begin_spin(
                self.refs[key],
                self.pixmaps[key],
                self.stream_info[key].url,
                self.stream_info[key].audio_url,
                sequence,
                durations,
                lambda reel_index=i: self.reel_locked(
                    reel_index
                ),
            )

    def _spin_fx_tick(self):
        if not self.spinning:
            return

        self.fx_phase += 0.72

        for i, reel in enumerate(self.reels):
            if i not in self.locked_reels:
                reel.set_spin_glow(
                    self.fx_phase + i * 1.2
                )

        pulse = 0.5 + 0.5 * math.sin(
            self.fx_phase * 1.6
        )

        brightness = 205 + int(50 * pulse)
        dots = "." * (1 + int(self.fx_phase) % 3)

        self.result.setText(
            "SPINNING" + dots
        )
        self.result.setStyleSheet(
            f"color:rgb({brightness},{brightness},{brightness});"
            "font-size:19px;font-weight:900;"
        )

    def reel_locked(self, reel_index):
        if reel_index in self.locked_reels:
            return

        self.locked_reels.add(reel_index)
        self.lock_count += 1

        reel = self.reels[reel_index]
        reel.flash_border()

        self.audio_fx.cut_spin_to_lock()

        # If later reels are still moving, bring spin.mp3 back after the lock
        # impact has had a clean moment to read.
        if self.lock_count < 3:
            QTimer.singleShot(
                180,
                self.audio_fx.resume_spin,
            )

        center = reel.mapTo(
            self.root_widget,
            reel.rect().center(),
        )
        self.fx_overlay.burst_at(
            center,
            count=30,
        )

        if self.lock_count == 3:
            self.spin_fx_timer.stop()
            self.audio_fx.stop_spin()
            self.fx_overlay.stop_spin()

            for r in self.reels:
                r.reset_border()

            self.finish_spin()

    def finish_spin(self):
        keys = [
            reel.current_ref.key
            for reel in self.reels
        ]

        if keys[0] == keys[1] == keys[2]:
            self.result.setText("JACKPOT")
            self.result.setStyleSheet(
                "color:#ffe34c;font-size:28px;font-weight:1000;"
            )

            # Let the final lock hit register, then transition into
            # the user's jackpot sound.
            QTimer.singleShot(
                160,
                self.audio_fx.play_win,
            )

            # All three reels are the same video on a jackpot, so play
            # the independent audio stream from only the first reel.
            self.reels[0].play_video_audio()

            # Collapse the three matching frames into one larger Short.
            # It remains this way, with the same jackpot audio continuing,
            # until the next SPIN is pressed.
            self._expand_jackpot_reel()

            self.fx_overlay.jackpot_celebration()
            self._jackpot_shake()

            # Short celebratory text flash.
            for delay, text in (
                (180, "JACKPOT ✦"),
                (360, "✦ JACKPOT ✦"),
                (540, "JACKPOT ✦"),
                (760, "JACKPOT"),
            ):
                QTimer.singleShot(
                    delay,
                    lambda value=text: self.result.setText(value),
                )

        elif len(set(keys)) == 2:
            self.result.setText("TWO MATCHED")
            self.result.setStyleSheet(
                "color:#ffcf5a;font-size:22px;font-weight:900;"
            )

            QTimer.singleShot(
                160,
                self.audio_fx.play_two_matched,
            )
            self.fx_overlay.pair_celebration()

        else:
            self.result.setText("SPIN AGAIN")
            self.result.setStyleSheet(
                "color:white;font-size:19px;font-weight:750;"
            )

        self.spinning = False
        self.spin_button.setText("SPIN")
        self.spin_button.setEnabled(True)

    def _jackpot_shake(self):
        # Tiny 240 ms shake. It is deliberately brief so the app stays usable.
        origin = self.pos()

        offsets = [
            QPoint(-7, 2),
            QPoint(7, -2),
            QPoint(-5, -3),
            QPoint(5, 3),
            QPoint(-3, 1),
            QPoint(3, -1),
            QPoint(0, 0),
        ]

        for index, offset in enumerate(offsets):
            QTimer.singleShot(
                index * 34,
                lambda o=offset: self.move(origin + o),
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if hasattr(self, "fx_overlay"):
            self.fx_overlay.setGeometry(
                self.root_widget.rect()
            )
            self.fx_overlay.raise_()

    def closeEvent(self, event):
        self.spin_fx_timer.stop()
        self.loading_progress_timer.stop()
        self.audio_fx.close()

        self.discovery.stop()
        self.thumbnails.stop()
        self.streams.stop()

        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Shorts Spinning Machine")

    window = ReelMachine()
    window.show()

    sys.exit(app.exec())
