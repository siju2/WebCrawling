"""교보문고 리뷰 API 구조 확인 + 파라미터 탐색"""
import requests, json

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://product.kyobobook.co.kr/detail/S000000610650",
    "Origin": "https://product.kyobobook.co.kr",
})

SALE_NO = "S000000610650"  # 채식주의자

print("=" * 60)
print("1. 리뷰 API 구조 확인 (revwPatrCode=002 = 구매자 리뷰)")
print("=" * 60)

url = (
    f"https://product.kyobobook.co.kr/api/review/list"
    f"?page=1&pageLimit=10&reviewSort=002"
    f"&revwPatrCode=002"
    f"&saleCmdtids={SALE_NO}&webToonYsno=N&allYsno=N"
    f"&revwSummeryYn=Y&saleCmdtid={SALE_NO}"
)
r = session.get(url, timeout=15)
print(f"상태: {r.status_code}")
if r.status_code == 200:
    try:
        data = r.json()
        print(f"키: {list(data.keys())}")
        print(f"전체 구조:\n{json.dumps(data, ensure_ascii=False, indent=2)[:3000]}")
    except:
        print(f"텍스트 (500자): {r.text[:500]}")

print("\n" + "=" * 60)
print("2. revwPatrCode 값 테스트")
print("=" * 60)
for code in ["000", "001", "002", "003"]:
    url2 = (
        f"https://product.kyobobook.co.kr/api/review/list"
        f"?page=1&pageLimit=3&reviewSort=002"
        f"&revwPatrCode={code}"
        f"&saleCmdtids={SALE_NO}&saleCmdtid={SALE_NO}"
    )
    r2 = session.get(url2, timeout=10)
    try:
        d = r2.json()
        count = d.get("total") or d.get("totalCount") or "?"
        items = (d.get("data", {}) or {})
        if isinstance(items, dict):
            review_list = items.get("list") or items.get("reviewList") or []
        else:
            review_list = []
        print(f"  revwPatrCode={code}: 상태={r2.status_code}, total={count}, 리뷰수={len(review_list)}")
        if review_list:
            rev = review_list[0]
            print(f"    첫 리뷰 키: {list(rev.keys())[:10]}")
            print(f"    텍스트: {str(rev)[:200]}")
    except:
        print(f"  revwPatrCode={code}: [{r2.status_code}] {r2.text[:100]}")

print("\n" + "=" * 60)
print("3. 요약 API (총 리뷰 수, 평점)")
print("=" * 60)
summary_url = f"https://product.kyobobook.co.kr/api/gw/pdt/review/summary?saleCmdtid={SALE_NO}"
r3 = session.get(summary_url, timeout=10)
print(f"상태: {r3.status_code}")
if r3.status_code == 200:
    try:
        print(json.dumps(r3.json(), ensure_ascii=False, indent=2)[:1000])
    except:
        print(r3.text[:500])

print("\n완료!")
