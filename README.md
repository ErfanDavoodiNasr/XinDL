# XinDL - Premium Telegram Downloader Bot

XinDL is a highly optimized, lightning-fast, and completely unrestricted Telegram Bot that downloads media from major
platforms in the exact quality you choose. Now featuring **Smart Search** and **2GB Large File Support**!

## 🌟 Premium Features

* **Universal Compatibility:** Seamlessly download videos and audio from YouTube, Instagram, TikTok, and Twitter/X by
  simply pasting a link.
* **Smart Search:** Type any text into the bot to instantly search for media across YouTube. Navigate through paginated
  results and download directly from the chat.
* **Granular Quality Selection:** Enjoy an elegant inline keyboard to select your exact preferred resolution (up to **4K
  2160p**) or audio bitrate (up to **320kbps**).
* **Unrestricted & Unlimited (2GB):** Fully open architecture with absolutely zero daily limits. Powered by the Local
  Bot API server, XinDL smoothly handles massive file uploads up to **2GB**.
* **Live Progress Tracking:** See exactly how fast your file is downloading with a beautiful, real-time progress bar UI.
* **Ultra-Lightweight:** Packaged in a highly optimized, multi-stage Docker image using `python:3.11-slim` for maximum
  performance and minimal disk footprint.

## 🚀 Installation & Deployment

Deploying XinDL is incredibly simple using Docker.

### 1. Configure the Environment

Clone the repository and set up your `.env` file:

```bash
git clone https://github.com/yourusername/XinDL.git
cd XinDL
cp .env.example .env
```

Edit `.env` and insert your Telegram Bot Token:

```env
BOT_TOKEN=your_telegram_bot_token_here
```

### 2. Deploy using Docker (Recommended)

This project includes a bundled `telegram-bot-api` local server to bypass standard Telegram bot limits.
Run the following command to build the optimized image and start the bot in the background:

```bash
docker compose up -d --build
```

### 3. Remote Automated Deployment

If you are deploying to a remote Linux server, you can use the included `deploy.sh` script for a robust, one-click
deployment.

1. Open `deploy.sh` and update `SERVER_IP`, `SERVER_USER`, `SERVER_PASSWORD`, and `REPO_URL`.
2. Run the script:

```bash
bash deploy.sh
```

## 🎮 Usage

1. Start the bot on Telegram by sending `/start`.
2. **Download URL:** Paste any valid public URL from YouTube, Instagram, TikTok, or Twitter/X.
3. **Search:** Simply type a query like "Nature 4k video" to browse paginated search results!
4. Click the inline button for the specific quality you want.
5. Watch the live progress bar as the bot downloads and sends the file directly to your chat!
