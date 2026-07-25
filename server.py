from __future__ import annotations

import json
import mimetypes
import os
import base64
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8787"))
APP_VERSION = os.getenv("APP_VERSION", "2026-07-25.4")
SHORTCUT_TOKEN = os.getenv("SHORTCUT_TOKEN", "")
REQUIRE_TOKEN = os.getenv("REQUIRE_TOKEN", "0").lower() in {"1", "true", "yes"}
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "900"))
MAX_FILESIZE = os.getenv("MAX_FILESIZE", "750M")
DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_ROOT", tempfile.gettempdir())) / "shortcut-video-downloads"
READY_ROOT = DOWNLOAD_ROOT / "ready"
READY_FILE_TTL_SECONDS = int(os.getenv("READY_FILE_TTL_SECONDS", "1800"))
DEFAULT_FORMAT = os.getenv(
    "YTDLP_FORMAT",
    (
        "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/"
        "b[vcodec^=avc1][ext=mp4]/"
        "bv*[vcodec^=h264][ext=mp4]+ba[ext=m4a]/"
        "b[vcodec^=h264][ext=mp4]/"
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best"
    ),
)
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
IOS_TRANSCODE_MODE = os.getenv("TRANSCODE_FOR_IOS", "0").lower()
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "")
YTDLP_COOKIES_TEXT = os.getenv("YTDLP_COOKIES_TEXT", "")
YTDLP_COOKIES_BASE64 = os.getenv("YTDLP_COOKIES_BASE64", "")
_active_downloads = 0
_download_lock = threading.Lock()
_download_jobs: dict[str, dict[str, object]] = {}

HOME_HTML = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Indir</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f5f7fb;
      color: #111827;
    }
    main {
      width: min(92vw, 560px);
      padding: 24px;
    }
    h1 {
      margin: 0 0 16px;
      font-size: 28px;
    }
    form {
      display: grid;
      gap: 12px;
    }
    input, button {
      box-sizing: border-box;
      width: 100%;
      min-height: 48px;
      border-radius: 8px;
      font: inherit;
    }
    input {
      border: 1px solid #cbd5e1;
      padding: 0 12px;
      background: white;
      color: #111827;
    }
    button {
      border: 0;
      background: #111827;
      color: white;
      font-weight: 700;
    }
    p {
      color: #4b5563;
      line-height: 1.5;
    }
    @media (prefers-color-scheme: dark) {
      body { background: #0b1020; color: #f8fafc; }
      input { background: #111827; border-color: #334155; color: #f8fafc; }
      p { color: #cbd5e1; }
      button { background: #f8fafc; color: #111827; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Video Indir</h1>
    <p>Indirme iznin olan bir video URL'si yapistir. iPhone kestirmesi de ayni endpoint'i arka planda kullanir.</p>
    <form action="/api/download" method="get">
      <input name="url" type="url" placeholder="https://..." required autocomplete="url">
      <button type="submit">Indir</button>
    </form>
  </main>
</body>
</html>
"""


class ShortcutDownloadError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def is_valid_video_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def repeatedly_unquote(value: str) -> str:
    cleaned = value.strip()
    for _ in range(3):
        decoded = unquote(cleaned).strip()
        if decoded == cleaned:
            break
        cleaned = decoded
    return cleaned


def normalize_video_url(value: str) -> str:
    cleaned = repeatedly_unquote(value)
    cleaned = cleaned.replace("\r", " ").replace("\n", " ").replace("\t", " ")

    match = re.search(r"https?://[^\s<>\"']+", cleaned)
    if match:
        cleaned = match.group(0)
    else:
        www_match = re.search(r"www\.[^\s<>\"']+", cleaned)
        if www_match:
            cleaned = f"https://{www_match.group(0)}"

    if cleaned.startswith("www."):
        cleaned = f"https://{cleaned}"

    return cleaned.rstrip(".,;)")


def safe_header_filename(path: Path) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in path.name)
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned or f"video-{int(time.time())}.mp4"


def shortcut_response(message: str, *, status: str = "error") -> dict[str, object]:
    return {
        "status": status,
        "message": message,
    }


def read_download_query(path: str) -> tuple[str, str, bool, bool]:
    parsed = urlparse(path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    debug = query.get("debug", ["0"])[0].lower() in {"1", "true", "yes"}
    prepare = query.get("prepare", ["0"])[0].lower() in {"1", "true", "yes"}
    token = query.get("token", [""])[0]

    candidates: list[str] = []
    for key in ("url", "u", "link", "input", "text"):
        candidates.extend(query.get(key, []))
    for values in query.values():
        candidates.extend(values)
    candidates.extend([parsed.query, parsed.path])

    for candidate in candidates:
        normalized = normalize_video_url(candidate)
        if is_valid_video_url(normalized):
            return normalized, token, debug, prepare

    return "", token, debug, prepare


def log_event(message: str) -> None:
    print(message, flush=True)


def cleanup_ready_files() -> None:
    READY_ROOT.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - READY_FILE_TTL_SECONDS
    for item in READY_ROOT.iterdir():
        if item.is_file() and item.stat().st_mtime < cutoff:
            item.unlink(missing_ok=True)


def stored_file_name(file_path: Path) -> str:
    suffix = file_path.suffix.lower() if file_path.suffix else ".mp4"
    return f"{uuid.uuid4().hex}-{safe_header_filename(file_path.with_suffix(suffix))}"


def newest_downloaded_file(folder: Path) -> Path:
    candidates = [
        item
        for item in folder.iterdir()
        if item.is_file()
        and not item.name.endswith((".part", ".ytdl", ".temp"))
        and item.stat().st_size > 0
    ]
    if not candidates:
        raise ShortcutDownloadError(
            HTTPStatus.BAD_GATEWAY,
            "Video indirilemedi. Link dogrudan indirilebilir olmayabilir veya site izin vermiyor olabilir.",
        )
    return max(candidates, key=lambda item: item.stat().st_mtime)


def friendly_ytdlp_error(message: str) -> str:
    lowered = message.lower()
    if "you need to log in" in lowered or "login required" in lowered:
        return (
            "Bu link giris istiyor. Instagram Story, private hesap veya kapali icerikler "
            "cloud servisinden cookies olmadan indirilemez. Public bir Reel/Post linki dene."
        )
    if "private video" in lowered or "private content" in lowered:
        return "Bu icerik private gorunuyor. Yalnizca indirme iznin olan public linklerle kullan."
    if "unsupported url" in lowered:
        return "Bu site veya link tipi desteklenmiyor olabilir. Public video dosyasi, Reel/Post veya desteklenen bir platform linki dene."
    return message


def cookies_path_for_job(job_dir: Path) -> str:
    if YTDLP_COOKIES_FILE:
        return YTDLP_COOKIES_FILE

    if not YTDLP_COOKIES_TEXT and not YTDLP_COOKIES_BASE64:
        return ""

    cookies_text = YTDLP_COOKIES_TEXT
    if YTDLP_COOKIES_BASE64:
        cookies_text = base64.b64decode(YTDLP_COOKIES_BASE64).decode("utf-8")

    cookies_file = job_dir / "cookies.txt"
    cookies_file.write_text(cookies_text, encoding="utf-8")
    return str(cookies_file)


def is_ios_compatible_video(file_path: Path) -> bool:
    if file_path.suffix.lower() != ".mp4":
        return False

    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "json",
                str(file_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False

    streams = payload.get("streams", [])
    if not isinstance(streams, list):
        return False

    video_codecs = {
        str(stream.get("codec_name", ""))
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    }
    audio_codecs = {
        str(stream.get("codec_name", ""))
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    }
    return bool(video_codecs) and video_codecs <= {"h264", "hevc"} and audio_codecs <= {
        "aac",
        "alac",
        "mp3",
    }


def make_ios_compatible_video(file_path: Path, job_dir: Path) -> Path:
    if IOS_TRANSCODE_MODE in {"0", "false", "no"}:
        return file_path
    if IOS_TRANSCODE_MODE == "auto" and is_ios_compatible_video(file_path):
        log_event(f"iPhone compatible source kept without transcode file={file_path.name}")
        return file_path

    output_path = job_dir / f"{file_path.stem}-iphone.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(file_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ShortcutDownloadError(
            HTTPStatus.BAD_GATEWAY,
            "Video indirildi ama iPhone uyumlu MP4'e cevrilemedi.",
        ) from exc

    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        last_line = detail[-1] if detail else "Bilinmeyen ffmpeg hatasi."
        raise ShortcutDownloadError(
            HTTPStatus.BAD_GATEWAY,
            f"Video indirildi ama iPhone uyumlu MP4'e cevrilemedi: {last_line[:300]}",
        )

    return output_path


def ensure_ytdlp_available() -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ShortcutDownloadError(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "yt-dlp kurulu degil. Kurmak icin: python -m pip install -r requirements.txt",
        ) from exc


def download_video(url: str) -> tuple[Path, Path]:
    url = normalize_video_url(url)
    if not is_valid_video_url(url):
        raise ShortcutDownloadError(
            HTTPStatus.BAD_REQUEST,
            f"Gecerli bir http/https video URL'si gonder. Gelen ham deger uzunlugu: {len(url)}",
        )

    ensure_ytdlp_available()
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="job-", dir=DOWNLOAD_ROOT))
    output_template = str(job_dir / "%(title).180B-%(id)s.%(ext)s")

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--restrict-filenames",
        "--windows-filenames",
        "--trim-filenames",
        "180",
        "--merge-output-format",
        "mp4",
        "--format",
        DEFAULT_FORMAT,
        "--output",
        output_template,
    ]

    if MAX_FILESIZE:
        command.extend(["--max-filesize", MAX_FILESIZE])

    cookies_path = cookies_path_for_job(job_dir)
    if cookies_path:
        command.extend(["--cookies", cookies_path])

    command.append(url)

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise ShortcutDownloadError(
            HTTPStatus.GATEWAY_TIMEOUT,
            "Indirme zaman asimina ugradi. Daha kucuk bir video deneyebilir veya DOWNLOAD_TIMEOUT_SECONDS degerini artirabilirsin.",
        ) from exc

    if completed.returncode != 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        last_line = detail[-1] if detail else "Bilinmeyen yt-dlp hatasi."
        raise ShortcutDownloadError(HTTPStatus.BAD_GATEWAY, friendly_ytdlp_error(last_line[:500]))

    downloaded_file = newest_downloaded_file(job_dir)
    return make_ios_compatible_video(downloaded_file, job_dir), job_dir


def store_ready_file(file_path: Path) -> str:
    cleanup_ready_files()
    name = stored_file_name(file_path)
    shutil.copy2(file_path, READY_ROOT / name)
    return name


def cleanup_download_jobs() -> None:
    cutoff = time.time() - READY_FILE_TTL_SECONDS
    with _download_lock:
        expired = [
            job_id
            for job_id, job in _download_jobs.items()
            if float(job.get("finished_at", time.time())) < cutoff
        ]
        for job_id in expired:
            _download_jobs.pop(job_id, None)


def run_download_job(job_id: str, url: str) -> None:
    global _active_downloads
    job_dir: Path | None = None
    try:
        file_path, job_dir = download_video(url)
        file_size = file_path.stat().st_size
        content_type = "video/mp4" if file_path.suffix.lower() == ".mp4" else (
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        )
        ready_name = store_ready_file(file_path)
        with _download_lock:
            job = _download_jobs[job_id]
            job.update(
                {
                    "state": "ready",
                    "file_name": ready_name,
                    "file_size": file_size,
                    "content_type": content_type,
                    "finished_at": time.time(),
                }
            )
        log_event(f"download job ready id={job_id} file={ready_name} size={file_size}")
    except ShortcutDownloadError as exc:
        with _download_lock:
            job = _download_jobs[job_id]
            job.update(
                {
                    "state": "error",
                    "status": exc.status.value,
                    "message": exc.message,
                    "finished_at": time.time(),
                }
            )
        log_event(f"download job error id={job_id} status={exc.status.value} message={exc.message}")
    except Exception as exc:
        with _download_lock:
            job = _download_jobs[job_id]
            job.update(
                {
                    "state": "error",
                    "status": HTTPStatus.INTERNAL_SERVER_ERROR.value,
                    "message": f"Beklenmeyen sunucu hatasi: {exc}",
                    "finished_at": time.time(),
                }
            )
        log_event(f"download job error id={job_id} status=500 message={exc}")
    finally:
        if job_dir is not None:
            shutil.rmtree(job_dir, ignore_errors=True)
        with _download_lock:
            _active_downloads = max(0, _active_downloads - 1)
            job = _download_jobs.get(job_id)
            event = job.get("event") if job else None
        if isinstance(event, threading.Event):
            event.set()


def start_download_job(url: str) -> str:
    global _active_downloads
    normalized = normalize_video_url(url)
    if not is_valid_video_url(normalized):
        raise ShortcutDownloadError(
            HTTPStatus.BAD_REQUEST,
            f"Gecerli bir http/https video URL'si gonder. Gelen ham deger uzunlugu: {len(normalized)}",
        )

    cleanup_download_jobs()
    with _download_lock:
        if _active_downloads >= MAX_CONCURRENT_DOWNLOADS:
            raise ShortcutDownloadError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "Servis mesgul. Biraz sonra tekrar dene.",
            )
        job_id = uuid.uuid4().hex
        _active_downloads += 1
        _download_jobs[job_id] = {
            "state": "running",
            "event": threading.Event(),
            "created_at": time.time(),
        }

    threading.Thread(
        target=run_download_job,
        args=(job_id, normalized),
        name=f"download-{job_id[:8]}",
        daemon=True,
    ).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortcutVideoDownloader/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/health"}:
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(HTTPStatus.NOT_FOUND.value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(HTTPStatus.OK, {"ok": True, "version": APP_VERSION})
            return

        if parsed.path == "/api/debug":
            url, token, _debug, _prepare = read_download_query(self.path)
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "received_url": url,
                    "received_url_length": len(url),
                    "has_token": bool(token),
                },
            )
            return

        if parsed.path == "/api/download":
            if not self.require_token():
                return
            url, _token, debug, prepare = read_download_query(self.path)
            log_event(
                f"download request debug={debug} prepare={prepare} "
                f"url_length={len(url)} url={url[:160]}"
            )
            try:
                job_id = start_download_job(url)
            except ShortcutDownloadError as exc:
                self.send_json(exc.status, shortcut_response(exc.message))
                return
            log_event(f"download job started id={job_id}")
            self.send_redirect(f"/jobs/{job_id}/wait")
            return

        job_match = re.fullmatch(r"/jobs/([0-9a-f]{32})/wait", parsed.path)
        if job_match:
            self.handle_job_wait(job_match.group(1))
            return

        if parsed.path.startswith("/files/"):
            self.handle_ready_file(parsed.path.removeprefix("/files/"))
            return

        if parsed.path == "/":
            self.send_html(HTTPStatus.OK, HOME_HTML)
            return

        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint bulunamadi."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/download":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint bulunamadi."})
            return

        try:
            body = self.read_request_body()
        except ShortcutDownloadError as exc:
            self.send_json(exc.status, {"error": exc.message})
            return

        self.handle_download(str(body.get("url", "")))

    def read_request_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536:
            raise ShortcutDownloadError(HTTPStatus.BAD_REQUEST, "Istek govdesi eksik veya cok buyuk.")

        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ShortcutDownloadError(HTTPStatus.BAD_REQUEST, "Gecerli UTF-8 veri gonder.") from exc

        if "application/x-www-form-urlencoded" in content_type:
            form = parse_qs(decoded)
            return {key: values[0] for key, values in form.items() if values}

        try:
            value = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ShortcutDownloadError(HTTPStatus.BAD_REQUEST, "Gecerli JSON gonder.") from exc

        if not isinstance(value, dict):
            raise ShortcutDownloadError(HTTPStatus.BAD_REQUEST, "JSON bir nesne olmali.")
        return value

    def require_token(self) -> bool:
        if not REQUIRE_TOKEN:
            return True

        if not SHORTCUT_TOKEN:
            return True

        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        header_token = self.headers.get("X-Shortcut-Token", "")
        if query_token == SHORTCUT_TOKEN or header_token == SHORTCUT_TOKEN:
            return True

        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Token hatali veya eksik."})
        return False

    def handle_download(self, url: str, *, debug: bool = False, prepare: bool = False) -> None:
        global _active_downloads
        if not self.require_token():
            return

        log_event(f"download request debug={debug} prepare={prepare} url_length={len(url)} url={url[:160]}")

        if _active_downloads >= MAX_CONCURRENT_DOWNLOADS:
            self.send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                shortcut_response("Servis mesgul. Biraz sonra tekrar dene."),
            )
            return

        job_dir: Path | None = None
        try:
            _active_downloads += 1
            file_path, job_dir = download_video(url.strip())
            file_size = file_path.stat().st_size
            content_type = self.guess_file_content_type(file_path)
            log_event(f"download ready file={file_path.name} size={file_size} content_type={content_type}")
            if debug or prepare:
                ready_name = self.store_ready_file(file_path)
                file_url = f"{self.public_base_url()}/files/{ready_name}"
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "file_name": ready_name,
                        "file_size": file_size,
                        "content_type": content_type,
                        "file_url": file_url,
                    },
                )
                return
            self.send_file(file_path)
        except ShortcutDownloadError as exc:
            log_event(f"download error status={exc.status.value} message={exc.message}")
            self.send_json(exc.status, shortcut_response(exc.message))
        finally:
            _active_downloads = max(0, _active_downloads - 1)
            if job_dir is not None:
                shutil.rmtree(job_dir, ignore_errors=True)

    def handle_ready_file(self, raw_name: str) -> None:
        cleanup_ready_files()
        name = safe_header_filename(Path(unquote(raw_name)))
        if not name:
            self.send_json(HTTPStatus.NOT_FOUND, shortcut_response("Dosya bulunamadi."))
            return

        file_path = READY_ROOT / name
        if not file_path.exists() or not file_path.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, shortcut_response("Dosya bulunamadi veya suresi doldu."))
            return

        log_event(f"serving ready file={file_path.name} size={file_path.stat().st_size}")
        self.send_file(file_path)

    def handle_job_wait(self, job_id: str) -> None:
        with _download_lock:
            job = _download_jobs.get(job_id)
            event = job.get("event") if job else None

        if job is None or not isinstance(event, threading.Event):
            self.send_json(HTTPStatus.NOT_FOUND, shortcut_response("Indirme isi bulunamadi veya suresi doldu."))
            return

        event.wait(timeout=15)
        with _download_lock:
            current = dict(_download_jobs.get(job_id, {}))

        state = current.get("state")
        if state == "running":
            self.send_redirect(f"/jobs/{job_id}/wait")
            return
        if state == "ready":
            self.send_redirect(f"/files/{current['file_name']}")
            return

        status = HTTPStatus(int(current.get("status", HTTPStatus.BAD_GATEWAY.value)))
        message = str(current.get("message", "Video indirilemedi."))
        self.send_json(status, shortcut_response(message))

    def store_ready_file(self, file_path: Path) -> str:
        return store_ready_file(file_path)

    def public_base_url(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto", "https")
        host = self.headers.get("Host", f"localhost:{PORT}")
        return f"{proto}://{host}"

    def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, status: HTTPStatus, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER.value)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_file(self, file_path: Path) -> None:
        content_type = self.guess_file_content_type(file_path)
        filename = safe_header_filename(file_path)
        size = file_path.stat().st_size

        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("X-File-Size", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()

        with file_path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def guess_file_content_type(self, file_path: Path) -> str:
        if file_path.suffix.lower() == ".mp4":
            return "video/mp4"
        return mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"


def main() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    READY_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Shortcut Video Downloader running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
