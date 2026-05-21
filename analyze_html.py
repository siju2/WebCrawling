"""Book 1 저장된 HTML 파싱 분석 + 구조 확인"""
import json
from bs4 import BeautifulSoup

with open("debug_32463527641.html", encoding="utf-8") as f:
    src = f.read()

print(f"HTML 크기: {len(src):,}")

soup = BeautifulSoup(src, "html.parser")
nd_tag = soup.find("script", {"id": "__NEXT_DATA__"})
if not nd_tag:
    print("__NEXT_DATA__ 없음!")
    exit()

nd = json.loads(nd_tag.string)
queries = nd["props"]["pageProps"]["dehydratedState"]["queries"]
print(f"queries 수: {len(queries)}")

for i, q in enumerate(queries):
    qk = q.get("queryKey", "")
    state = q.get("state", {})
    data = state.get("data")
    print(f"\n[{i}] queryKey: {str(qk)[:80]}")
    print(f"     data type: {type(data).__name__}")
    
    if isinstance(data, dict):
        print(f"     data keys: {list(data.keys())[:10]}")
        pages = data.get("pages")
        if pages is not None:
            print(f"     pages type: {type(pages).__name__}, len: {len(pages) if pages else 0}")
            if pages and isinstance(pages, list):
                p0 = pages[0]
                print(f"     pages[0] type: {type(p0).__name__}")
                if isinstance(p0, dict):
                    print(f"     pages[0] keys: {list(p0.keys())}")
                    # MallReviews 확인
                    if "MallReviews" in p0:
                        mr = p0["MallReviews"]
                        print(f"     MallReviews type: {type(mr).__name__}")
                        if isinstance(mr, dict):
                            print(f"     totalCount: {mr.get('totalCount')}")
                            reviews = mr.get("reviewList", [])
                            print(f"     reviewList: {len(reviews)}개")
                            if reviews:
                                r0 = reviews[0]
                                print(f"     첫리뷰: {json.dumps(r0, ensure_ascii=False)[:300]}")
    elif isinstance(data, list):
        print(f"     data (list) len: {len(data)}")
        if data:
            print(f"     data[0] type: {type(data[0]).__name__}")
            print(f"     data[0]: {str(data[0])[:100]}")
    else:
        print(f"     data: {str(data)[:100]}")
