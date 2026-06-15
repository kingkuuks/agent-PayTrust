# PayTrust Autonomous Content Agent

Four-agent pipeline that monitors Twitter for payment pain points in Ghana, generates a video script via Kimi K2.5, builds scene images + voiceover audio, and renders a final MP4 via Remotion.

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install Remotion dependencies
cd templates/MarketingVideo && npm install && cd ../..

# 3. One-time Twitter login (saves cookies.json)
python tools/twitter_scraper.py --login

# 4. Dry run (Agents 1+2 only, no render)
python run.py --dry-run

# 5. Full pipeline run
python run.py --once

# 6. Scheduled mode (runs daily at 8am)
python run.py
```

## Agents

| # | Agent | File | What it does |
|---|-------|------|-------------|
| 1 | Listener | `agents/listener.py` | Scrapes Twitter for payment-related trends |
| 2 | Strategist | `agents/strategist.py` | Sends trends to Kimi K2.5, gets a production brief |
| 3 | Asset Builder | `agents/asset_builder.py` | Generates scene images + voiceover audio |
| 4 | Assembler | `agents/assembler.py` | Updates Remotion config, renders final MP4 |

## Configuration

All credentials go in `.env` (copy from `.env.example`). Brand settings, keywords, and subreddits are in `config/`.

## Output

Videos are saved to `output/YYYY-MM-DD_HH-MM/video.mp4` along with the brief and script.
