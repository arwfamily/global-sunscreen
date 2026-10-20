"""전성분 재수집 — 리포뮬레이션 감지.

사용법:
    python3 recapture.py                  # 전체 재수집 (dry-run)
    python3 recapture.py --apply          # 변경사항을 kr_ingredients.jsonl에 반영
    python3 recapture.py --id KR-20261008-110  # 특정 제품만

동작:
1. kr_ingredients.jsonl의 각 레코드에서 source_url 로드
2. 텍스트 추출 가능한 출처만 자동 재수집 (이미지 출처는 수동 큐에 추가)
3. 새 전성분 배열과 기존 배열 비교
4. 변경 감지 시 snapshots/reformulation_history 기록
5. --apply 없이 실행하면 변경사항만 리포트 (fail-closed)
"""
import json
import re
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diff import diff_ingredients, normalize_list, normalize_for_compare
from extractors import extract

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "kr_ingredients.jsonl")
LOG_DIR = os.path.join(BASE, "recapture", "logs")

# 자동 재수집 가능한 출처 (텍스트 기반)
AUTO_SOURCES = {
    "brand-official-text",
    "amoremall-schema-text",
    "danawa-spec-text",
}


def load_db():
    with open(DB_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_db(records):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, DB_PATH)


def recapture_record(rec: dict, today: str) -> dict:
    """단일 레코드 재수집. 결과 dict 반환."""
    result = {
        "id": rec["id"],
        "product": rec["product"],
        "source": rec.get("source", ""),
        "status": "",
        "diff": None,
    }

    source = rec.get("source", "")
    url = rec.get("source_url", "")

    if source not in AUTO_SOURCES or not url:
        result["status"] = "manual-queue"
        result["reason"] = f"이미지/수동 출처 ({source}) — 수동 재확인 필요"
        return result

    try:
        new_ingredients = extract(url)
    except Exception as e:
        result["status"] = "fetch-failed"
        result["reason"] = str(e)[:200]
        return result

    if not new_ingredients:
        result["status"] = "extract-failed"
        result["reason"] = "전성분 텍스트를 추출하지 못함"
        return result

    new_ingredients = normalize_list(new_ingredients)
    old_ingredients = normalize_list(rec.get("ingredients_ko", []))

    # 2026-10-20: a page footer (주소 "5층", 배송비 "000원 부과", "온라인 광고") was read as
    # ingredients and logged as a reformulation. Such a read is never applied.
    junk = [x for x in new_ingredients if JUNK.search(x)]
    if junk or (old_ingredients and len(new_ingredients) > 1.4 * len(old_ingredients) + 3):
        result["status"] = "extract-suspect"
        result["reason"] = ("non-ingredient text in the extracted list: " + ", ".join(junk[:3])) if junk else \
            f"list grew from {len(old_ingredients)} to {len(new_ingredients)} items"
        return result

    # 비교는 공백 아티팩트 제거 후 수행
    d = diff_ingredients(
        [normalize_for_compare(x) for x in old_ingredients],
        [normalize_for_compare(x) for x in new_ingredients],
    )
    result["diff"] = d

    if not d["changed"]:
        result["status"] = "unchanged"
        return result

    result["status"] = "changed"
    result["new_ingredients"] = new_ingredients
    return result


JUNK = re.compile(r"\d+\s*층|광고|배송|부과|교환|반품|고객센터|사업자|통신판매|대표|주소|전화|\d{1,3},?000\s*원|^\d+$|^\d+원")


def apply_change(rec: dict, result: dict, today: str):
    """변경사항을 레코드에 반영 (fail-closed: --apply 명시 시에만 호출)."""
    d = result["diff"]
    new_ingredients = result["new_ingredients"]

    rec["snapshots"].append({
        "date": today,
        "ingredients_ko": new_ingredients,
        "source": rec.get("source", ""),
        "source_url": rec.get("source_url", ""),
    })
    rec["reformulation_history"].append({
        "date": today,
        "summary": d["summary"],
        "added": d["added"],
        "removed": d["removed"],
        "reordered": d["reordered"],
    })
    rec["reformulation_detected"] = True
    rec["ingredients_ko"] = new_ingredients
    rec["last_captured"] = today
    # UV 필터 재계산은 수동 검수 후 — 자동 판정하지 않음
    rec["review_status"] = "reformulation-detected-needs-human-check"


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    target_id = None
    for a in args:
        if a.startswith("--id="):
            target_id = a.split("=", 1)[1]
        elif a == "--id" and args.index(a) + 1 < len(args):
            target_id = args[args.index(a) + 1]

    today = date.today().isoformat()
    records = load_db()
    if target_id:
        records = [r for r in records if r["id"] == target_id]
        if not records:
            print(f"ID를 찾을 수 없음: {target_id}")
            return

    os.makedirs(LOG_DIR, exist_ok=True)

    results = []
    changed_count = 0
    for rec in records:
        r = recapture_record(rec, today)
        results.append(r)
        if r["status"] == "changed":
            changed_count += 1
            print(f"[CHANGED] {r['id']} {r['product']}")
            print(f"  {r['diff']['summary']}")
            if apply:
                apply_change(rec, r, today)
        elif r["status"] == "unchanged":
            if apply:
                rec["last_captured"] = today
        else:
            print(f"[{r['status'].upper()}] {r['id']} {r['product']}: {r.get('reason', '')}")

    if apply:
        save_db(load_db() if target_id else records)
        # target_id가 있으면 전체 DB 로드 후 해당 레코드만 교체
        if target_id:
            all_recs = load_db()
            by_id = {r["id"]: r for r in records}
            for i, r in enumerate(all_recs):
                if r["id"] in by_id:
                    all_recs[i] = by_id[r["id"]]
            save_db(all_recs)
        print(f"\n반영 완료: {changed_count}개 변경")
    else:
        print(f"\n[dry-run] {changed_count}개 변경 감지 — 반영하려면 --apply")

    # 로그 저장
    log_path = os.path.join(LOG_DIR, f"recapture-{today}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"로그: {log_path}")


if __name__ == "__main__":
    main()
