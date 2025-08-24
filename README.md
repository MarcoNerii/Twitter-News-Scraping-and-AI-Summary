# Twitter-News-Scraping-and-Ai-Summary

This project scrapes tweets from [FinancialJuice](https://x.com/financialjuice) (or any X/Twitter account) and summarizes them into a **structured Markdown report** using **Google Gemini** (free API).

## Features
- Scrapes tweets from the last N hours with Playwright (inside a Jupyter notebook).
- Saves text + timestamps (in Geneva time) to `financialjuice_last_hours.txt`.
- Summarizes with Gemini into a clean Markdown briefing grouped by countries.
- Prompt is fully customizable.

## Setup
```bash
git clone https://github.com/MarcoNerii/Twitter-News-Scraping-and-AI-Summary.git
cd Twitter-News-Scraping-and-AI-Summary
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install firefox chromium
```

## Authentication
Export your **X.com cookies** (JSON format, via a browser extension like Cookie-Editor) and save them locally as:
```
x_cookies.json
```
⚠️ This file is in `.gitignore` → **never commit it**.

## Usage
1. Open the notebook `main.ipynb`.
2. Run the cells to:
   - Scrape tweets into `financialjuice_last_hours.txt`
   - Summarize them with Gemini
   - Save the final summary to `summary.md`

## Summarization
- Get a free API key from [Google AI Studio](https://aistudio.google.com/).
- Set it in your environment:  
  ```bash
  export GOOGLE_API_KEY="your_key_here"
  ```
- Edit the notebook `custom_prompt` to control the output format (e.g. group by countries, keep only latest facts).

## Example Output
```markdown
## Europe
- Germany GDP miss: -0.3% QoQ vs -0.1% est..

## U.S.
- Powell (Jackson Hole): cautious on jobs, vigilant on inflation.

## Risks & Watch-Fors
- Payrolls, Eurozone inflation flash, Oil headlines
```

## Notes
- `.gitignore` excludes cookies, secrets, and environments.
- If cookies leak, log out of X to invalidate.
