from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8787"))
SHORTCUT_TOKEN = os.getenv("SHORTCUT_TOKEN", "")
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "900"))
MAX_FILESIZE = os.getenv("MAX_FILESIZE", "750M")
DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_ROOT", tempfile.gettempdir())) / "shortcut-video-downloads"
DEFAULT_FORMAT = os.getenv("YTDLP_FORMAT", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best")
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
_active_downloads = 0

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


def safe_header_filename(path: Path) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in path.name)
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned or f"video-{int(time.time())}.mp4"


def shortcut_response(message: str, *, status: str = "error") -> dict[str, object]:
    return {
        "status": status,
        "message": message,
    }


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
    if not is_valid_video_url(url):
        raise ShortcutDownloadError(HTTPStatus.BAD_REQUEST, "Gecerli bir http/https video URL'si gonder.")

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
        raise ShortcutDownloadError(HTTPStatus.BAD_GATEWAY, last_line[:500])

    return newest_downloaded_file(job_dir), job_dir


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
            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        if parsed.path == "/api/download":
            query = parse_qs(parsed.query)
            url = query.get("url", [""])[0]
            self.handle_download(url)
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
        if not SHORTCUT_TOKEN:
            return True

        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        header_token = self.headers.get("X-Shortcut-Token", "")
        if query_token == SHORTCUT_TOKEN or header_token == SHORTCUT_TOKEN:
            return True

        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Token hatali veya eksik."})
        return False

    def handle_download(self, url: str) -> None:
        global _active_downloads
        if not self.require_token():
            return

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
            self.send_file(file_path)
        except ShortcutDownloadError as exc:
            self.send_json(exc.status, shortcut_response(exc.message))
        finally:
            _active_downloads = max(0, _active_downloads - 1)
            if job_dir is not None:
                shutil.rmtree(job_dir, ignore_errors=True)

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

    def send_file(self, file_path: Path) -> None:
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        filename = safe_header_filename(file_path)
        size = file_path.stat().st_size

        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()

        with file_path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)


def main() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
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
