"""출처별 전성분 추출기."""
import re
import json
import urllib.request


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def fetch(url: str, timeout: int = 40) -> str:
    from urllib.parse import quote, urlsplit, urlunsplit
    # 한글 등 비ASCII URL 인코딩
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%")
    query = quote(parts.query, safe="=&%")
    url = urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    # 인코딩 감지
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def strip_tags(html: str) -> str:
    import html as htmlmod
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmlmod.unescape(text)  # &nbsp; 등 HTML 엔티티 디코딩
    text = re.sub(r"\s+", " ", text)
    return text


def split_ingredients(text: str) -> list[str]:
    """쉼표 구분 전성분 텍스트를 배열로 분리.

    주의: '1,2-헥산다이올' 같은 성분이 쉼표로 잘리지 않도록 처리.
    """
    # 먼저 알려진 패턴 보호
    protected = text.replace("1,2-헥산다이올", "1‚2-헥산다이올")
    protected = protected.replace("1,2-헥산디올", "1‚2-헥산디올")
    parts = [p.strip() for p in protected.split(",")]
    result = []
    for p in parts:
        p = p.replace("1‚2-", "1,2-")
        if p:
            result.append(p)
    return result


def extract_amoremall(url: str) -> list[str] | None:
    """아모레몰 schema.org JSON에서 성분 추출."""
    html = fetch(url)
    # additionalProperty 중 name=="성분" 찾기
    m = re.search(
        r'\{"name":"성분","value":"(.*?)","@type":"PropertyValue"\}',
        html,
    )
    if not m:
        return None
    # \uXXXX 이스케이프만 해제 (한글 원문은 그대로 유지)
    value = m.group(1)
    value = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda mm: chr(int(mm.group(1), 16)),
        value,
    )
    value = value.replace("\\n", " ").replace('\\"', '"')
    return split_ingredients(value)


def extract_illiyoon(url: str) -> list[str] | None:
    """일리윤 직영몰 '전성분 정보' 섹션에서 추출."""
    html = fetch(url)
    text = strip_tags(html)
    m = re.search(r"전성분 정보(.{50,3000}?)상품정보제공고시|전성분 정보(.{50,3000}?)$", text)
    if not m:
        # 대체: 전성분 키워드 뒤 텍스트
        idx = text.find("전성분")
        if idx < 0:
            return None
        chunk = text[idx:idx + 3000]
    else:
        chunk = m.group(1) or m.group(2)
    # 첫 번째 문장군이 성분 목록일 가능성
    return split_ingredients(chunk)


def extract_mongdies(url: str) -> list[str] | None:
    """몽디에스 상품정보제공고시에서 '모든 성분' 추출."""
    html = fetch(url)
    text = strip_tags(html)
    m = re.search(r"모든 성분(.{50,4000}?)사용할 때의 주의사항", text)
    if not m:
        return None
    return split_ingredients(m.group(1))


def is_ingredient_like(text: str) -> bool:
    """성분명답게 생겼는지 휴리스틱 판정."""
    import re
    t = text.strip()
    if not t or len(t) > 60:
        return False
    # 한글/영문/숫자/하이픈/슬래시/괄호/콤마/마침표/공백만 허용
    if re.search(r"[^가-힣a-zA-Z0-9\-/()·.,\s%]", t):
        return False
    # 한글 또는 영문이 포함되어야 함
    if not re.search(r"[가-힣a-zA-Z]", t):
        return False
    # 문장 종결 패턴 제외
    if re.search(r"(합니다|입니다|있습니다|주세요|것$|기$)", t):
        return False
    return True


def extract_generic_text(url: str, start_marker: str = "전성분",
                         end_marker: str | None = None,
                         max_len: int = 4000) -> list[str] | None:
    """범용: 시작 마커 뒤 텍스트를 추출.

    안전장치: 성분명답지 않은 항목이 나오면 거기서 중단.
    """
    html = fetch(url)
    text = strip_tags(html)
    idx = text.find(start_marker)
    if idx < 0:
        return None
    chunk = text[idx + len(start_marker):idx + len(start_marker) + max_len]
    if end_marker:
        eidx = chunk.find(end_marker)
        if eidx > 0:
            chunk = chunk[:eidx]
    # 종료 마커 후보들
    for end in ["사용기한", "사용방법", "제조국", "화장품제조업자",
                "품질보증기준"]:
        eidx = chunk.find(end)
        if eidx > 0:
            chunk = chunk[:eidx]
            break
    parts = split_ingredients(chunk.strip())
    # 성분명다운 항목만 앞에서부터 수집
    ingredients = []
    for p in parts:
        if is_ingredient_like(p):
            ingredients.append(p)
        elif ingredients:
            # 이미 수집 시작 후 비성분 항목 → 종료
            break
    if len(ingredients) < 5:
        return None
    return ingredients


def extract_zeroid(url: str) -> list[str] | None:
    """제로이드: '전성분 [제품명] 성분1, 성분2, ... 상품정보' 패턴."""
    html = fetch(url)
    text = strip_tags(html)
    idx = text.find("전성분")
    if idx < 0:
        return None
    chunk = text[idx + 3:idx + 4000]
    # 제품명 부분 건너뛰기: 첫 번째 쉼표 전까지가 제품명일 수 있음
    # 실제로는 "전성분 이지워시 마일드 선크림 SPF30 PA++++ 정제수, ..." 형태
    # "PA++++" 뒤부터가 성분 목록
    m = re.search(r"PA\+{2,4}\s+", chunk)
    if m:
        chunk = chunk[m.end():]
    # 종료 마커
    for end in ["상품정보", "리뷰", "사용방법"]:
        eidx = chunk.find(end)
        if 50 < eidx:
            chunk = chunk[:eidx]
            break
    chunk = chunk.strip()
    if chunk.count(",") < 5 or len(chunk) > 3000:
        return None
    return split_ingredients(chunk)


def extract_atopalm(url: str) -> list[str] | None:
    """아토팜 공식몰: EWG 등급 형식 '전성분 ... N 성분명 N 성분명 ...' 파싱."""
    html = fetch(url)
    text = strip_tags(html)
    idx = text.find("전성분")
    if idx < 0:
        return None
    chunk = text[idx:idx + 5000]
    # 범례 부분 건너뛰기: "1-2 낮은 위험도 3-6 보통 위험도 7-10 높은 위험도" 뒤부터
    m = re.search(r"7-10 높은 위험도\s*", chunk)
    if m:
        chunk = chunk[m.end():]
    # 종료 마커
    for end in ["2025.", "2026.", "REEF SAFE", "이렇게 사용해보세요", "사용방법"]:
        eidx = chunk.find(end)
        if eidx > 100:
            chunk = chunk[:eidx]
            break
    # 패턴: 숫자 + 성분명 (숫자는 EWG 등급)
    # "*자외선 차단 성분" 같은 주석은 구분자로 교체 (성분 경계 유지)
    chunk = re.sub(r"\*\S+(\s+\S+){0,3}", " @@ ", chunk)
    # "N 성분명 N 성분명 ..." → 숫자로 split (화학명 안의 숫자는 제외)
    tokens = re.split(r"(?<![\d\-/])(\d{1,2})(?!\d)\s+", chunk)
    ingredients = []
    for i in range(1, len(tokens) - 1, 2):
        name = tokens[i + 1].strip().rstrip(",").strip()
        if name and not re.fullmatch(r"[\d\s\-.,@]+", name):
            # @@ 구분자가 있으면 분리
            for part in name.split("@@"):
                part = part.strip()
                if part:
                    ingredients.append(part)
    if len(ingredients) < 5:
        return None
    return ingredients


def extract_goongbe(url: str) -> list[str] | None:
    """궁중비책 공식몰: '주요성분' 또는 전성분 텍스트."""
    html = fetch(url)
    text = strip_tags(html)
    for marker in ["주요성분", "전성분", "모든 성분"]:
        idx = text.find(marker)
        if idx < 0:
            continue
        chunk = text[idx + len(marker):idx + len(marker) + 4000]
        parts = split_ingredients(chunk.strip())
        ingredients = [p for p in parts if is_ingredient_like(p)]
        # 앞에서부터 성분명다운 것만
        result = []
        for p in ingredients:
            if is_ingredient_like(p):
                result.append(p)
            elif result:
                break
        if len(result) >= 5:
            return result
    return None


EXTRACTORS = {
    "amoremall": extract_amoremall,
    "illiyoon": extract_illiyoon,
    "mongdies": extract_mongdies,
    "zeroid": extract_zeroid,
    "atopalm": extract_atopalm,
    "goongbe": extract_goongbe,
}


def extract(url: str, extractor_name: str | None = None) -> list[str] | None:
    """URL에서 전성분 추출. extractor_name이 없으면 도메인으로 추론."""
    if extractor_name and extractor_name in EXTRACTORS:
        return EXTRACTORS[extractor_name](url)
    if "amoremall.com" in url:
        return extract_amoremall(url)
    if "illiyoon.com" in url:
        return extract_illiyoon(url)
    if "mongdies.com" in url:
        return extract_mongdies(url)
    if "zeroid.co.kr" in url:
        return extract_zeroid(url)
    if "neopharmshop.co.kr" in url:
        return extract_atopalm(url)
    if "goongbe.com" in url:
        return extract_goongbe(url)
    return extract_generic_text(url)
