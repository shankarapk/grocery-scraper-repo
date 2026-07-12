"""
Smart Grocery Price Scraper
Run: python scraper.py "tomato,onion,rice,milk"
"""

import asyncio, json, re, os, sys
from datetime import datetime
from playwright.async_api import async_playwright

# Default grocery list — overridden by command line argument
DEFAULT_ITEMS = [
    "tomato", "onion", "potato", "carrot", "beans",
    "rice", "wheat flour", "milk", "eggs", "oil",
    "garlic", "ginger", "chilli", "banana", "brinjal",
]

STORES = {
    'zepto':     {'label':'Zepto',           'color':'#6c2bd9', 'url':'https://www.zepto.com/search?query={query}',                    'wait_ms':5000},
    'blinkit':   {'label':'Blinkit',         'color':'#f8c100', 'url':'https://blinkit.com/s/?q={query}',                              'wait_ms':5000},
    'instamart': {'label':'Swiggy Instamart','color':'#fc8019', 'url':'https://www.swiggy.com/instamart/search?query={query}',         'wait_ms':6000},
    'bigbasket': {'label':'BigBasket',       'color':'#84c225', 'url':'https://www.bigbasket.com/ps/?q={query}',                       'wait_ms':5000},
}

EXTRACTOR_JS = """
() => {
    const JUNK = new Set(['add','notify','notify me','out of stock','subscribe',
        'view','see all','remove','wishlist','share','login','signup',
        'buy now','sold out','in stock','new','trending','search','home']);

    function parsePrice(t) {
        if (!t) return null;
        const n = parseFloat(t.replace(/[₹,\\s]/g,'').trim());
        return isNaN(n)||n<1||n>100000 ? null : n;
    }
    function isPrice(t) { return /^₹\\s*[\\d,]+(\\.[\\d]+)?$/.test(t.trim()); }

    function findCards() {
        const s1 = document.querySelectorAll(
            '[class*="product-card"],[class*="ProductCard"],[class*="plp-product"],' +
            '[class*="item-card"],[class*="ItemCard"],[class*="prod-deck"],' +
            '[class*="ProductGridItem"],[class*="productCard"],[class*="GridItem"]'
        );
        if (s1.length > 2) return Array.from(s1);

        const anchors = Array.from(document.querySelectorAll('a[href]'))
            .filter(a => /₹\\s*\\d+/.test(a.innerText||'') &&
                (a.href.includes('/pn/')||a.href.includes('/product')||a.href.includes('/p/')));
        if (anchors.length > 2) return anchors;

        return Array.from(document.querySelectorAll('div,li,article')).filter(el => {
            const r = el.getBoundingClientRect();
            if (r.width<80||r.width>520) return false;
            if (r.height<80||r.height>750) return false;
            const t = el.innerText||'';
            const pc = (t.match(/₹\\s*\\d+/g)||[]).length;
            return pc>=1&&pc<=5&&t.length>10&&t.length<400;
        });
    }

    const cards = findCards();
    const products = [], seen = new Set();

    cards.forEach(card => {
        try {
            const leaves = Array.from(card.querySelectorAll('*'))
                .filter(e=>e.children.length===0)
                .map(e=>e.innerText?.trim()||'')
                .filter(t=>t.length>0);

            const prices = leaves.filter(isPrice).map(parsePrice).filter(Boolean);
            const texts  = leaves.filter(t=>
                !isPrice(t)&&!JUNK.has(t.toLowerCase())&&
                t.length>2&&!/^\\d+(\\.\\d+)?[kK]?$/.test(t));

            if (!prices.length||!texts.length) return;

            const price = Math.min(...prices);
            const mrp   = Math.max(...prices)>price ? Math.max(...prices) : null;
            const name  = texts.filter(t=>/[a-zA-Z]/.test(t))
                               .reduce((a,b)=>a.length>=b.length?a:b,'');
            if (!name||name.length<3) return;

            const key = name.toLowerCase().substring(0,30)+'|'+price;
            if (seen.has(key)) return;
            seen.add(key);

            const qty      = texts.find(t=>/\\d+\\s*(g|kg|ml|l|litre|pc|pcs|pack)\\b/i.test(t))||'';
            const discount = texts.find(t=>/\\d+\\s*%\\s*off|₹\\s*\\d+\\s*off/i.test(t))||null;
            const link     = card.closest('a')||card.querySelector('a');

            products.push({name,quantity:qty,price,mrp,discount,
                url:link?.href||location.href});
        } catch(_){}
    });

    return {products, cardCount:cards.length, url:location.href};
}
"""

async def scrape_one(browser, store_key, query):
    store  = STORES[store_key]
    url    = store['url'].format(query=query.replace(' ', '+'))
    page   = await browser.new_page()
    result = []
    try:
        await page.set_extra_http_headers({'Accept-Language':'en-IN,en;q=0.9'})
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(store['wait_ms'])
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(700)
        data  = await page.evaluate(EXTRACTOR_JS)
        prods = data.get('products', [])
        print(f"  [{store_key:<10}] {query:<18} → {len(prods)} products "
              f"(cards: {data.get('cardCount',0)})")
        result = [{**p, 'store':store_key, 'store_label':store['label'],
                   'query':query, 'capturedAt':datetime.now().isoformat()}
                  for p in prods]
    except Exception as e:
        print(f"  [{store_key:<10}] {query:<18} → ERROR: {e}")
    finally:
        await page.close()
    return result

def best_per_store(products, query):
    def relevance(p):
        name = p['name'].lower()
        q    = query.lower()
        if q in name: return 2
        if any(w in name for w in q.split()): return 1
        return 0
    relevant = [p for p in products if relevance(p)>0] or products
    best = {}
    for p in relevant:
        sk = p['store']
        if sk not in best or p['price'] < best[sk]['price']:
            best[sk] = p
    return sorted(best.values(), key=lambda x: x['price'])

async def main():
    items = DEFAULT_ITEMS
    if len(sys.argv) > 1:
        items = [i.strip() for i in sys.argv[1].split(',') if i.strip()]

    print(f"\n🛒 Smart Grocery Scraper — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"   Items  : {', '.join(items)}")
    print(f"   Stores : {', '.join(STORES.keys())}\n")

    all_data = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-setuid-sandbox',
                  '--disable-blink-features=AutomationControlled',
                  '--disable-dev-shm-usage','--disable-gpu'])

        BATCH = 3
        for i in range(0, len(items), BATCH):
            batch = items[i:i+BATCH]
            print(f"\n── Batch {i//BATCH+1}: {batch}")
            tasks   = [asyncio.gather(*[scrape_one(browser, sk, q) for sk in STORES])
                       for q in batch]
            results = await asyncio.gather(*tasks)
            for query, store_results in zip(batch, results):
                all_products = [p for sr in store_results for p in sr]
                all_data[query] = best_per_store(all_products, query)
            await asyncio.sleep(1)

        await browser.close()

    os.makedirs('output', exist_ok=True)

    # Save JSON
    with open('output/prices.json','w',encoding='utf-8') as f:
        json.dump({'scraped_at':datetime.now().isoformat(),'items':all_data},
                  f, ensure_ascii=False, indent=2)

    # Print table
    print(f"\n{'═'*70}")
    print(f"  {'Item':<18} {'Best Store':<16} {'Price':>6}  {'All Prices'}")
    print(f"{'─'*70}")
    total_save = 0
    for query, options in all_data.items():
        if not options:
            print(f"  {'⬜ '+query:<18} {'—':<16} {'—':>6}")
            continue
        best   = options[0]
        others = '  '.join(f"{o['store_label']} ₹{o['price']:.0f}" for o in options[1:])
        saving = options[-1]['price']-options[0]['price'] if len(options)>1 else 0
        total_save += saving
        print(f"  {'✅ '+query:<18} {best['store_label']:<16} "
              f"₹{best['price']:>5.0f}  {others[:35]}")
    print(f"{'─'*70}")
    print(f"  💰 Total potential saving today: ₹{total_save:.0f}\n")

    # Generate HTML report
    generate_html(all_data)
    print("📄 Report saved → output/report.html")
    print("📦 JSON saved  → output/prices.json")


def generate_html(all_data):
    store_colors = {k:v['color'] for k,v in STORES.items()}
    rows = []
    total_cheap = total_exp = 0

    for query, options in all_data.items():
        if not options:
            rows.append(f'<tr><td class="item-name">{query.title()}</td>'
                        f'<td colspan="5" style="color:#555;text-align:center">No data found</td></tr>')
            continue
        total_cheap += options[0]['price']
        total_exp   += options[-1]['price']
        for i, opt in enumerate(options):
            color   = store_colors.get(opt['store'], '#888')
            is_best = i == 0
            saving  = options[-1]['price'] - opt['price']
            rows.append(f"""
        <tr class="{'best-row' if is_best else ''}">
          {'<td rowspan="'+str(len(options))+'" class="item-name">'+query.title()+'</td>' if i==0 else ''}
          <td><span class="dot" style="background:{color}"></span>{opt['store_label']}
            {'<span class="badge">மலிவு ✓</span>' if is_best else ''}</td>
          <td>{opt.get('quantity','—')}</td>
          <td class="price {'best-p' if is_best else ''}">₹{opt['price']:.0f}</td>
          <td class="mrp">{'₹'+str(int(opt['mrp'])) if opt.get('mrp') else '—'}</td>
          <td>{'<span class="save">Save ₹'+str(int(saving))+'</span>' if is_best and saving>0 else (opt.get('discount') or '—')}</td>
        </tr>""")

    ts = datetime.now().strftime('%d %b %Y, %I:%M %p IST')
    html = f"""<!DOCTYPE html><html lang="ta"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ஸ்மார்ட் கிரோசரி — விலை ஒப்பீடு</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a1a0a;color:#e8f5e9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}}
header{{background:#1b5e20;padding:22px 28px}}
header h1{{font-size:22px;font-weight:800}}
header p{{font-size:13px;color:#c8e6c9;margin-top:4px}}
.banner{{background:linear-gradient(135deg,#1b5e20,#0a2a0a);border:1px solid #4caf50;
  border-radius:12px;margin:20px 28px;padding:20px 24px;display:flex;align-items:center;gap:20px}}
.banner .amt{{font-size:38px;font-weight:800;color:#00e676}}
.banner p{{font-size:14px;color:#a5d6a7;line-height:1.5}}
.search{{padding:14px 28px}}
.search input{{width:100%;padding:12px 16px;background:#0f2a0f;border:2px solid #1e3d1e;
  border-radius:10px;color:#e8f5e9;font-size:17px;outline:none;transition:border .2s}}
.search input:focus{{border-color:#4caf50}}
.wrap{{overflow-x:auto;padding:0 28px 40px}}
table{{width:100%;border-collapse:collapse;border-radius:10px;overflow:hidden}}
th{{background:#0f2a0f;padding:11px 14px;text-align:left;font-size:12px;
  color:#81c784;text-transform:uppercase;letter-spacing:.5px}}
td{{padding:11px 14px;border-top:1px solid #1a3a1a;font-size:15px;vertical-align:middle}}
tr.best-row td{{background:#071a07}}
.item-name{{font-weight:700;font-size:16px;text-transform:capitalize;color:#a5d6a7;white-space:nowrap}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}}
.badge{{background:#00e676;color:#000;font-size:11px;font-weight:800;
  padding:2px 7px;border-radius:8px;margin-left:6px}}
.best-p{{font-size:18px;font-weight:800;color:#00e676}}
.mrp{{color:#555;text-decoration:line-through;font-size:13px}}
.save{{background:#1b3a1b;color:#69f0ae;font-size:12px;padding:2px 8px;border-radius:8px}}
.hidden{{display:none}}
footer{{text-align:center;padding:20px;font-size:12px;color:#2e5c2e}}
</style></head><body>
<header>
  <h1>🛒 ஸ்மார்ட் கிரோசரி — விலை ஒப்பீடு</h1>
  <p>Zepto · Blinkit · Swiggy Instamart · BigBasket &nbsp;|&nbsp; {ts}</p>
</header>
<div class="banner">
  <div>
    <div class="amt">₹{total_exp-total_cheap:.0f}</div>
    <p>மலிவான கடைகளில் வாங்கினால் சேமிக்கலாம்<br>
       Potential savings by always choosing the cheapest store</p>
  </div>
</div>
<div class="search">
  <input id="s" type="text" placeholder="தேடுங்கள் / Search items..."
    oninput="document.querySelectorAll('tr.item-group').forEach(r=>{{
      r.classList.toggle('hidden', this.value&&!r.dataset.name.includes(this.value.toLowerCase()))
    }})">
</div>
<div class="wrap">
<table>
<thead><tr>
  <th>பொருள்</th><th>கடை (Store)</th><th>அளவு (Qty)</th>
  <th>விலை (Price)</th><th>MRP</th><th>சேமிப்பு</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
<footer>Personal use only · Data captured via browser automation</footer>
</body></html>"""

    with open('output/report.html','w',encoding='utf-8') as f:
        f.write(html)

if __name__ == '__main__':
    asyncio.run(main())
