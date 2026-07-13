# Smart Grocery Price Scraper — Setup

## One-time setup (run these once on your PC)

```bash
pip install playwright
python -m playwright install chromium
```

## Run it

```bash
# Search for tomato across all 4 stores
python scraper.py --query tomato

# Search for rice on specific stores only
python scraper.py --query rice --stores zepto blinkit

# Search for onion, save to onion.json
python scraper.py --query onion --output onion.json
```

## Output

- Prints a comparison table in terminal
- Saves full data to prices.json (or whatever --output you set)

## What it does (same as Apify)

1. Launches a real Chromium browser (headless — no window)
2. Opens each store's search page for your query
3. Waits for React to finish rendering products
4. Scrolls down to trigger lazy loading
5. Reads product cards from the live DOM
6. Extracts name, price, MRP, discount, quantity
7. Groups same products across stores and finds cheapest
