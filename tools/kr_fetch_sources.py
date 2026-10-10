"""Fetch the source pages of the Korean baby-sunscreen sheet for verification.

For each job in tools/kr_jobs.json: save the page HTML, pull every ingredient
passage found as text (전성분 / 모든 성분), and download the page's product
images, cut into slices no taller than 2000 px so each slice can be read.
Output: kr_sources/<id>/{page.html, text.json, img_###_s#.jpg} + index.json.
"""
import hashlib, html, io, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
OUT = "kr_sources"

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read(), r.geturl()
        except Exception as e:
            err = str(e)
            time.sleep(3 * (i + 1))
    return None, err

def quote(u):
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(urllib.parse.unquote(p.path)), p.query, p.fragment))

def text_of(raw):
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)

def passages(t):
    out = []
    for m in re.finditer(r"(전성분|모든\s*성분|화장품법에 따라[^.]{0,40}성분|Ingredients?)", t):
        out.append(t[m.start(): m.start() + 3000])
    return out[:12]

def imgs(raw, base):
    t = raw.decode("utf-8", "replace")
    srcs = re.findall(r'(?:ec-data-src|data-src|data-original|src)\s*=\s*["\']([^"\']+\.(?:jpe?g|png|gif|webp)[^"\']*)', t, re.I)
    srcs += re.findall(r'((?:https?:)?//[^\s"\'<>()]+?\.(?:jpe?g|png|gif))', t, re.I)
    srcs += re.findall(r'(/web/upload/[^\s"\'<>()]+?\.(?:jpe?g|png|gif))', t, re.I)
    seen, out = set(), []
    for s in srcs:
        u = urllib.parse.urljoin(base, html.unescape(s))
        if u in seen or re.search(r"icon|logo|btn|banner_|sns|common/|/layout/|spacer|blank", u, re.I):
            continue
        seen.add(u); out.append(u)
    return out[:120]

def job(j):
    d = os.path.join(OUT, j["id"]); os.makedirs(d, exist_ok=True)
    rec = {"id": j["id"], "url": j["url"], "pages": []}
    urls = [x for x in (j.get("url"),) if x] + list(j.get("extra") or [])
    m = re.search(r"11st\.co\.kr/products/(\d+)", j.get("url") or "")
    if m:
        urls += [f"https://www.11st.co.kr/products/{m.group(1)}/view-desc",
                 f"https://www.11st.co.kr/product/SellerProductDetail.tmall?method=getSellerProductDetailDesc&prdNo={m.group(1)}"]
    for n_url, url in enumerate(urls):
        raw, final = get(quote(url))
        if raw is None:
            rec["pages"].append({"url": url, "error": final}); continue
        kind = "source" if n_url == 0 else f"extra{n_url}"
        if re.search(r"\.(jpe?g|png|gif)$", url, re.I):
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            page = {"url": url, "final": final, "bytes": len(raw), "passages": [], "images": []}
            for s_, top in enumerate(range(0, im.height, 1800)):
                fn = f"{kind}_direct_s{s_}.jpg"
                im.crop((0, top, im.width, min(im.height, top + 1900))).save(os.path.join(d, fn), quality=90)
                page["images"].append({"file": fn, "src": url})
            rec["pages"].append(page)
            continue
        open(os.path.join(d, f"{kind}.html"), "wb").write(raw)
        t = text_of(raw)
        page = {"url": url, "final": final, "bytes": len(raw), "passages": passages(t), "images": []}
        n = 0
        for u in imgs(raw, final):
            b, _ = get(quote(u), tries=2)
            if not b or len(b) < 15000:
                continue
            try:
                im = Image.open(io.BytesIO(b)).convert("RGB")
            except Exception:
                continue
            if im.width < 300:
                continue
            if im.width > 1100:
                im = im.resize((1100, int(im.height * 1100 / im.width)))
            n += 1
            for s, top in enumerate(range(0, im.height, 1800)):
                fn = f"{kind}_img{n:03d}_s{s}.jpg"
                im.crop((0, top, im.width, min(im.height, top + 1900))).save(os.path.join(d, fn), quality=85)
                page["images"].append({"file": fn, "src": u, "sha1": hashlib.sha1(b).hexdigest()})
        rec["pages"].append(page)
    json.dump(rec, open(os.path.join(d, "text.json"), "w"), ensure_ascii=False, indent=1)
    return rec

if __name__ == "__main__":
    jobs = json.load(open(os.environ.get("KR_JOBS", "tools/kr_jobs.json")))
    only = set(sys.argv[1:])
    if only:
        jobs = [j for j in jobs if j["id"] in only]
    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(job, jobs))
    json.dump(res, open(os.path.join(OUT, "index.json"), "w"), ensure_ascii=False, indent=1)
    ok = sum(1 for r in res for p in r["pages"] if "error" not in p)
    print(f"[kr] {len(res)} products, {ok} pages fetched, {sum(len(p.get('images', [])) for r in res for p in r['pages'])} image slices")
