# XinDL — Telegram Media Downloader Bot

XinDL is a fast, production-ready Telegram bot for downloading media from **YouTube**, **Instagram**, and **SoundCloud
**. Built with **aiogram 3**, **yt-dlp**, and **ffmpeg**.

---

## Features

### Supported platforms (only 3)

| Platform       | Content               |
|----------------|-----------------------|
| **YouTube**    | Videos, Shorts, music |
| **Instagram**  | Reels, posts, stories |
| **SoundCloud** | Tracks (audio only)   |

### Quality selection (low → high)

- **Video:** 144p → 240p → 360p → 480p → 720p → 1080p → 2K → 4K → *Highest Available*
- Only resolutions the source actually supports are shown
- **Audio:** 128 → 192 → 256 → 320 kbps → *Best Audio* (MP3)
- SoundCloud shows audio options only

### Large files

- Files **≤ 2 GB** → sent as a single message
- Files **> 2 GB** → automatically split with ffmpeg into ~2 GB parts
- Each part is uploaded separately with `Part 1/N`, `Part 2/N`, … in the caption
- Uses local Telegram Bot API (`USE_LOCAL_API=True`) for large uploads via `file://`

### Performance & concurrency

- Separate limits for info fetch and download (no slowdown on rapid requests)
- `MAX_CONCURRENT_INFO=5` — parallel metadata extraction
- `MAX_CONCURRENT_DOWNLOADS=3` — parallel downloads
- In-memory TTL cache for repeated URLs (1 hour)
- Live progress bar during download (speed, ETA, percent)

### No cookies / no proxy required

- Works out of the box without `cookies.txt` or `PROXY_URL`
- Instagram uses `curl-cffi` browser impersonation (not account cookies)
- Public content on all 3 platforms works without extra setup

### Other

- Post-download validation with ffprobe (+ optional ffmpeg repair)
- Download cancellation support
- Structured JSON logging
- Multi-stage Docker image (`python:3.12-slim` + ffmpeg + nodejs)

---

## Quick start (local)

### 1. Configure environment

```bash
git clone https://github.com/yourusername/XinDL.git
cd XinDL
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token_here

# Required for files > 50 MB
USE_LOCAL_API=True
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
```

Get `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from [my.telegram.org](https://my.telegram.org).

### 2. Run with Docker

```bash
docker compose up -d --build
```

This starts:

- `bot` — the Telegram downloader
- `telegram-bot-api` — local API server for large file uploads

### 3. Check logs

```bash
docker compose logs -f bot
```

---

## Remote deployment (`platform.sh`)

For deploying to a remote Linux server:

1. Add server credentials to `.env`:

```env
SERVER_IP=your.server.ip
SERVER_USER=root
SERVER_PASSWORD=your_password
PROJECT_DIR=/opt/XinDL
```

2. Run the interactive manager:

```bash
bash platform.sh
```

Menu options:

1. **Deploy / Update** — upload project + `docker compose up -d --build`
2. **View Live Logs**
3. **Check Docker Status**

Requires `sshpass` on your local machine.

---

## Usage

1. Send `/start` to the bot on Telegram
2. Paste a direct link from YouTube, Instagram, or SoundCloud
3. Pick video quality (low → high) or audio only
4. Wait for download + upload — file arrives in chat

**Tips:**

- Lower quality = faster download and smaller file
- For very large videos, the bot splits and sends multiple parts automatically
- Unsupported platforms get an immediate rejection message

---

## Configuration

| Variable                   | Default | Description                                                  |
|----------------------------|---------|--------------------------------------------------------------|
| `BOT_TOKEN`                | —       | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `USE_LOCAL_API`            | `True`  | Use local Bot API for >50 MB files                           |
| `TELEGRAM_API_ID`          | —       | From my.telegram.org                                         |
| `TELEGRAM_API_HASH`        | —       | From my.telegram.org                                         |
| `MAX_CONCURRENT_DOWNLOADS` | `3`     | Max parallel downloads                                       |
| `MAX_CONCURRENT_INFO`      | `5`     | Max parallel metadata fetches                                |
| `YTDLP_TIMEOUT`            | `300`   | Timeout per download step (seconds)                          |

---

## Project structure

```
src/
├── bot/
│   ├── main.py           # Entry point
│   ├── handlers/base.py  # URL handling, download flow, upload
│   ├── keyboards.py      # Quality selection UI
│   └── middlewares.py    # Request ID + error handling
└── core/
    ├── downloader.py     # yt-dlp wrapper, cache, concurrency, split
    ├── platforms.py      # YouTube / Instagram / SoundCloud whitelist
    ├── validator.py      # ffprobe validation + ffmpeg repair
    └── config.py         # Settings from .env
```

---

## Requirements

- Python 3.12+
- ffmpeg / ffprobe
- nodejs (for yt-dlp JS challenges)
- Docker & Docker Compose (recommended)
