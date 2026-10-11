# Find Identity 🔍

A modular, high-performance OSINT toolkit designed for cross-platform public profile reconnaissance, image forensics, and deep reverse visual matching.

Built with **Python**, **FastAPI**, **HTTPX**, and **Pillow**, featuring both a real-time web dashboard (Server-Sent Events) and a terminal interface.

---

## ✨ Features

### 1. Username Reconnaissance Engine
- **Asynchronous Concurrent Scanning**: Queries public platforms concurrently with non-blocking I/O and tunable concurrency semaphores.
- **Strict Anti-False-Positive Filtering**:
  - **TikTok**: Validated via official oEmbed creator endpoints, avoiding bot WAF challenges.
  - **Medium**: Validates live RSS creator feeds to guarantee genuine accounts.
  - **Pinterest**: Implements negative marker scanning against client-side single-page applications.
  - **Telegram & Keybase**: Confirms public presence via structural markers and status codes.
  - **GitHub, GitLab, Mastodon, Wikipedia, HackerNews, Dev.to**.
- **User-Agent Rotation**: Randomized browser identity rotation to minimize rate-limiting triggers.

### 2. Deep Visual Forensics & Reverse Image Search
- **Drag-and-Drop Multi-Image Support**: Process up to 10 photos simultaneously.
- **Automated Google Lens API**: Automated 2-stage upload bridge to SerpApi Google Lens returning visual matches, source URLs, and knowledge graph cards.
- **Direct Multi-Engine Search Hub**: Instant 1-click query buttons for:
  - **Google Lens**
  - **Yandex Visual Search** (top global engine for facial recognition)
  - **Bing Visual Search**
  - **TinEye Reverse Search**
- **Image Forensics**:
  - **Perceptual Hash (`dHash`)**: 64-bit structural fingerprinting to detect resized, cropped, or filtered copies.
  - **EXIF Extraction**: Camera manufacturer, model, software, and timestamp.
  - **GPS Geolocation Mapping**: Automatic conversion of EXIF GPS coordinates into direct Google Maps links.
  - **Cryptographic Signatures**: MD5 and SHA-256 hashes.

### 3. Real-Time Web GUI & CLI
- **Live SSE Streaming**: Progress bars and live terminal feeds update incrementally as each platform responds.
- **One-Click JSON Export**: Download structured investigation reports directly from the browser or CLI.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- (Optional) [SerpApi](https://serpapi.com) API Key for live Google Lens lookups.

### 1. Clone & Install
```bash
git clone https://github.com/Rohan-Reyes/find_identity.git
cd find_identity

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration (`.env`)
Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` to supply your API key:
```env
SERPAPI_API_KEY=your_serpapi_key_here
```
*(If no API key is supplied, local image forensics, dHash, EXIF, and 1-click external search buttons remain fully operational.)*

---

## 🖥️ Usage

### Web Dashboard (Localhost)
Launch the web interface:
```bash
python app.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.
- Enter one or multiple usernames (separated by commas, spaces, or newlines).
- Drag and drop up to 10 image files into the upload zone.
- Click **Launch Reconnaissance Scan** to view real-time discoveries.

### Command Line Interface (CLI)
```bash
# Scan a single username
python main.py -u torvalds

# Scan username and analyze a local image file
python main.py -u torvalds -f photo.jpg

# Custom output file
python main.py -u torvalds -f photo.jpg -o report.json
```

---

## 📁 Project Structure

```
find_identity/
├── .env.example          # Environment variables template
├── .gitignore            # Git exclusions (protects secrets & uploads)
├── requirements.txt      # Python dependencies
├── config.py             # Target platforms and validation rules
├── username_recon.py     # Asynchronous profile scanner
├── image_search.py       # Deep image forensics & Google Lens integration
├── app.py                # FastAPI web server and SSE GUI
├── main.py               # Command-line interface
└── README.md             # Project documentation
```

---

## 🔒 Security & Privacy Notice
This tool is intended for defensive security assessments, digital footprint discovery, and OSINT research on public data. Please adhere to the terms of service of each respective platform.

## 📄 License
MIT License.
