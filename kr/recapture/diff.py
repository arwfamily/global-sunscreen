"""전성분 배열 diff — 리포뮬레이션 감지용."""
import difflib


def diff_ingredients(old: list[str], new: list[str]) -> dict:
    """두 전성분 배열을 비교해 변경 내역을 반환한다.

    Returns:
        {
            "changed": bool,
            "added": [...],      # 새로 추가된 성분
            "removed": [...],    # 제거된 성분
            "reordered": bool,   # 순서만 바뀐 경우
            "summary": str,      # 사람이 읽는 요약
        }
    """
    old_set, new_set = set(old), set(new)
    added = [x for x in new if x not in old_set]
    removed = [x for x in old if x not in new_set]

    # 순서 변경 감지 (공통 성분의 순서가 바뀌었는지)
    common_old = [x for x in old if x in new_set]
    common_new = [x for x in new if x in old_set]
    reordered = common_old != common_new and not added and not removed

    changed = bool(added or removed or reordered)

    parts = []
    if added:
        parts.append(f"추가: {', '.join(added)}")
    if removed:
        parts.append(f"제거: {', '.join(removed)}")
    if reordered:
        parts.append("순서 변경 (성분 동일)")
    summary = "; ".join(parts) if parts else "변경 없음"

    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "reordered": reordered,
        "summary": summary,
    }


def normalize(name: str) -> str:
    """성분명 정규화 — 공백, 대소문자, CI 표기 정리."""
    n = name.strip()
    import re
    n = re.sub(r"\s+", " ", n)
    return n


def normalize_for_compare(name: str) -> str:
    """비교용 정규화 — HTML 파싱 아티팩트(잘못 들어간 공백) 제거."""
    n = normalize(name)
    import re
    # 한글 사이의 공백 제거 ("트로메 타민" → "트로메타민")
    n = re.sub(r"(?<=[가-힣])\s+(?=[가-힣])", "", n)
    # 한글과 영문 사이 공백 제거 ("도데실 p-크레솔" → "도데실p-크레솔")
    n = re.sub(r"(?<=[가-힣])\s+(?=[a-zA-Z])", "", n)
    n = re.sub(r"(?<=[a-zA-Z])\s+(?=[가-힣])", "", n)
    return n


def normalize_list(ingredients: list[str]) -> list[str]:
    return [normalize(x) for x in ingredients if x and x.strip()]
