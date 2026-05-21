"""
교보문고 구매자 리뷰 대규모 크롤러 - 최종 프로덕션
=======================================================
방식:
  1. Naver Open API → 카테고리별 책 목록 (ISBN)
  2. 교보문고 HTML 검색 → saleCmdtid 획득
  3. 교보문고 리뷰 API → 구매자 리뷰 (revwPatrCode=002)
  4. CSV 저장 (증분, 중단/재시작 지원)

장점:
  - Selenium 불필요 (requests만 사용)
  - 교보문고 봇 감지 없음
  - 구매자 리뷰만 수집 (revwPatrCode=002)
  - 빠른 속도 (초당 여러 요청 가능)
"""

import sys, os, re, json, csv, time, random, logging
from datetime import datetime
from bs4 import BeautifulSoup
import requests

# ── 로깅 ─────────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            encoded = msg.encode(stream.encoding or "utf-8", errors="replace")
            stream.write(encoded.decode(stream.encoding or "utf-8", errors="replace") + self.terminator)
            self.flush()
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/kyobo_crawl.log", encoding="utf-8"),
        SafeStreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────
NAVER_CLIENT_ID     = "xaycKafg5L6rPQFiuw0x"
NAVER_CLIENT_SECRET = "nYRS3j1EhY"
NAVER_BOOK_API      = "https://openapi.naver.com/v1/search/book.json"

OUTPUT_CSV   = "kyobo_book_reviews_ALL.csv"
DONE_FILE    = "crawled_kyobo.txt"
BOOKS_FILE   = "kyobo_books.json"

MAX_REVIEWS_PER_BOOK = 200   # 책당 최대 리뷰 수
MAX_PAGES_PER_BOOK   = 20    # 최대 페이지 (페이지당 10개)

CSV_COLUMNS = [
    "카테고리", "도서제목", "저자", "출판사", "ISBN", "출판일",
    "교보ID", "리뷰어ID", "별점", "리뷰내용", "리뷰날짜",
    "감정키워드", "revwPatrCode"
]

# ── 카테고리 & 검색어 ─────────────────────────────────────────────────────────
CATEGORIES = {
    "소설/시/희곡":   ["소설", "시집", "한국소설", "외국소설", "추리소설", "SF소설",
                      "로맨스소설", "판타지소설", "역사소설", "단편소설"],
    "경제/경영":      ["경제", "경영", "마케팅", "재테크", "투자", "주식", "스타트업",
                      "회계", "금융", "부동산"],
    "자기계발":       ["자기계발", "성공", "습관", "리더십", "동기부여", "시간관리",
                      "멘탈관리", "목표설정", "생산성"],
    "인문학":         ["인문학", "철학", "심리학", "언어학", "논리학", "사회심리",
                      "인지심리", "행동경제학"],
    "사회과학":       ["사회학", "정치학", "법학", "교육학", "행정학", "미디어",
                      "젠더", "복지", "환경정책"],
    "역사/문화":      ["한국사", "세계사", "문화사", "역사", "문명", "조선",
                      "근현대사", "고대사", "전쟁역사"],
    "예술/대중문화":  ["미술", "음악", "영화", "사진", "디자인", "건축",
                      "패션", "연극", "애니메이션"],
    "종교/역학":      ["불교", "기독교", "명상", "요가", "영성", "명리학"],
    "컴퓨터/IT":      ["파이썬", "자바", "인공지능", "머신러닝", "데이터분석",
                      "웹개발", "알고리즘", "딥러닝", "클라우드", "보안"],
    "과학":           ["과학", "물리학", "화학", "생물학", "천문학", "수학",
                      "뇌과학", "양자역학", "진화론"],
    "여행":           ["여행", "배낭여행", "국내여행", "유럽여행", "일본여행",
                      "동남아여행", "미국여행", "가이드북"],
    "건강/취미/레저": ["건강", "운동", "다이어트", "헬스", "등산", "취미",
                      "수공예", "요가건강", "명상건강"],
    "요리/살림":      ["요리", "레시피", "베이킹", "살림", "인테리어",
                      "홈케어", "발효음식", "채식"],
    "어린이":         ["동화", "어린이", "초등", "위인전", "아동문학",
                      "과학동화", "역사동화"],
    "유아":           ["그림책", "유아", "아기", "영유아", "보드북"],
    "청소년":         ["청소년소설", "진로", "청소년", "중학생", "고등학생"],
    "만화":           ["만화", "웹툰", "그래픽노블", "순정만화", "일본만화",
                      "학습만화"],
    "수험서/자격증":  ["공무원", "TOEIC", "자격증", "수능", "공인중개사",
                      "취업", "IT자격증"],
    "어학":           ["영어회화", "일본어", "중국어", "영문법", "IELTS",
                      "어학", "스페인어", "프랑스어"],
    "외국도서":       ["foreign novel", "self help english", "business book",
                      "english learning", "science book english"],
}

# ── HTTP 세션 ─────────────────────────────────────────────────────────────────
def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer":  "https://product.kyobobook.co.kr/",
        "Origin":   "https://product.kyobobook.co.kr",
    })
    return s

SESSION = make_session()

# ── Naver Open API ─────────────────────────────────────────────────────────────
def search_naver_books(query: str, max_books: int = 100) -> list[dict]:
    books, seen, start = [], set(), 1
    while len(books) < max_books:
        try:
            resp = SESSION.get(
                NAVER_BOOK_API,
                params={"query": query, "display": 100, "start": start, "sort": "sim"},
                headers={
                    "X-Naver-Client-Id": NAVER_CLIENT_ID,
                    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
                },
                timeout=10,
            )
            items = resp.json().get("items", [])
            if not items:
                break
        except Exception as e:
            log.warning(f"Naver API 오류: {e}")
            break

        for item in items:
            isbn_raw = item.get("isbn", "").strip()
            isbn = isbn_raw.split()[0] if isbn_raw else ""
            if not isbn or isbn in seen:
                continue
            seen.add(isbn)
            books.append({
                "title":     re.sub(r"<[^>]+>", "", item.get("title", "")),
                "author":    re.sub(r"<[^>]+>", "", item.get("author", "")),
                "publisher": item.get("publisher", ""),
                "isbn":      isbn,
                "pubdate":   item.get("pubdate", ""),
            })
            if len(books) >= max_books:
                break
        if len(items) < 100:
            break
        start += 100
        time.sleep(0.2)
    return books

# ── 교보문고 saleCmdtid 검색 ──────────────────────────────────────────────────
def get_kyobo_sale_ids(isbn: str) -> list[str]:
    """ISBN으로 교보문고 saleCmdtid 목록 반환"""
    try:
        url = f"https://search.kyobobook.co.kr/search?keyword={isbn}&target=total&gbCd=KOR"
        r = SESSION.get(url, timeout=10)
        if r.status_code != 200:
            return []
        # product.kyobobook.co.kr/detail/S... 링크 추출
        sale_ids = re.findall(r'product\.kyobobook\.co\.kr/detail/(S\d+)', r.text)
        # JavaScript 데이터에서도 추출
        sale_ids += re.findall(r'saleCmdtid["\s:\']+([Ss]\d{10,})', r.text)
        seen = set()
        result = []
        for s in sale_ids:
            s = s.upper()
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result[:5]
    except Exception as e:
        log.debug(f"saleCmdtid 조회 실패: {e}")
        return []

# ── 교보문고 리뷰 API ─────────────────────────────────────────────────────────
REVIEW_API = "https://product.kyobobook.co.kr/api/review/list"

def get_kyobo_reviews(sale_id: str, max_reviews: int = 200) -> tuple[list[dict], int]:
    """교보문고 구매자 리뷰 수집 (revwPatrCode=002)"""
    all_reviews = []
    total = 0

    for page in range(1, MAX_PAGES_PER_BOOK + 1):
        if len(all_reviews) >= max_reviews:
            break
        try:
            params = {
                "page":          page,
                "pageLimit":     10,
                "reviewSort":    "002",     # 최신순
                "revwPatrCode":  "002",     # 구매자 리뷰
                "saleCmdtids":   sale_id,
                "webToonYsno":   "N",
                "allYsno":       "N",
                "revwSummeryYn": "Y",
                "saleCmdtid":    sale_id,
            }
            r = SESSION.get(REVIEW_API, params=params, timeout=10)
            if r.status_code != 200:
                break
            data = r.json().get("data", {})
            if not data:
                break
            review_list = data.get("reviewList", [])
            if not review_list:
                break

            for item in review_list:
                text = (item.get("revwCntt") or "").strip()
                if text:
                    all_reviews.append({
                        "kyobo_id":  sale_id,
                        "user_id":   item.get("mmbrId", ""),
                        "score":     item.get("revwRvgr", ""),
                        "text":      text,
                        "date":      item.get("cretDttm", "")[:10],
                        "emotion":   item.get("revwEmtnKywrName", ""),
                        "patr_code": item.get("revwPatrCode", ""),
                    })

            if len(review_list) < 10:
                break   # 마지막 페이지
        except Exception as e:
            log.debug(f"리뷰 API 오류 ({sale_id} p{page}): {e}")
            break

        time.sleep(random.uniform(0.3, 0.7))

    return all_reviews, total

# ── CSV & 상태 관리 ───────────────────────────────────────────────────────────
def init_csv():
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()

def append_csv(reviews: list[dict], cat: str, book: dict):
    rows = []
    for r in reviews:
        rows.append({
            "카테고리":    cat,
            "도서제목":    book["title"],
            "저자":        book["author"],
            "출판사":      book["publisher"],
            "ISBN":        book["isbn"],
            "출판일":      book["pubdate"],
            "교보ID":      r["kyobo_id"],
            "리뷰어ID":    r["user_id"],
            "별점":        r["score"],
            "리뷰내용":    r["text"],
            "리뷰날짜":    r["date"],
            "감정키워드":  r["emotion"],
            "revwPatrCode": r["patr_code"],
        })
    if rows:
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerows(rows)

def load_done() -> set:
    if not os.path.exists(DONE_FILE):
        return set()
    with open(DONE_FILE, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}

def mark_done(isbn: str):
    with open(DONE_FILE, "a", encoding="utf-8") as f:
        f.write(isbn + "\n")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 70)
    log.info("교보문고 구매자 리뷰 대규모 크롤러 시작!")
    log.info(f"   방식: requests 직접 (Selenium 불필요)")
    log.info(f"   API: product.kyobobook.co.kr/api/review/list")
    log.info(f"   revwPatrCode=002 (구매자 리뷰)")
    log.info(f"   출력: {OUTPUT_CSV}")
    log.info("=" * 70)

    init_csv()
    done = load_done()
    log.info(f"   이미 완료: {len(done)}개")

    # ── 1단계: 책 목록 수집 ─────────────────────────────────────────────────
    all_books = {}  # isbn → {category, ...}

    if os.path.exists(BOOKS_FILE):
        with open(BOOKS_FILE, encoding="utf-8") as f:
            all_books = json.load(f)
        log.info(f"책 목록 로드: {len(all_books):,}권")
    else:
        log.info("전 카테고리 책 목록 수집 중...")
        for cat_name, queries in CATEGORIES.items():
            cat_count = 0
            for q in queries:
                books = search_naver_books(q, 100)
                for b in books:
                    if b["isbn"] not in all_books:
                        all_books[b["isbn"]] = {**b, "category": cat_name}
                        cat_count += 1
                time.sleep(random.uniform(0.2, 0.5))
            log.info(f"  [{cat_name}]: {cat_count:,}권 수집")

        with open(BOOKS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_books, f, ensure_ascii=False, indent=2)
        log.info(f"   총 {len(all_books):,}권 → {BOOKS_FILE} 저장")

    log.info(f"\n크롤링 대상: {len(all_books):,}권")

    # ── 2단계: 각 책 리뷰 크롤링 ─────────────────────────────────────────────
    total_reviews = 0
    processed = 0
    books_list = list(all_books.items())

    try:
        for i, (isbn, book) in enumerate(books_list, 1):
            if isbn in done:
                continue

            cat = book.get("category", "기타")

            # saleCmdtid 조회
            sale_ids = get_kyobo_sale_ids(isbn)
            if not sale_ids:
                log.debug(f"  [{i:,}/{len(books_list):,}] {book['title'][:30]} → saleCmdtid 없음")
                mark_done(isbn)
                processed += 1
                time.sleep(random.uniform(0.5, 1.0))
                continue

            # 모든 saleCmdtid에서 리뷰 수집
            book_reviews = []
            for sale_id in sale_ids[:2]:   # 최대 2개 edition
                reviews, _ = get_kyobo_reviews(sale_id, MAX_REVIEWS_PER_BOOK)
                book_reviews.extend(reviews)
                if len(book_reviews) >= MAX_REVIEWS_PER_BOOK:
                    break

            # 중복 제거
            seen_texts = set()
            unique_reviews = []
            for rv in book_reviews:
                key = rv["text"][:50]
                if key not in seen_texts:
                    seen_texts.add(key)
                    unique_reviews.append(rv)

            if unique_reviews:
                append_csv(unique_reviews, cat, book)
                total_reviews += len(unique_reviews)
                log.info(f"[{i:,}/{len(books_list):,}] [{cat}] {book['title'][:35]}"
                         f" → {len(unique_reviews)}개 (누계: {total_reviews:,})")
            else:
                log.info(f"[{i:,}/{len(books_list):,}] {book['title'][:35]} → 리뷰 없음")

            mark_done(isbn)
            processed += 1

            # 진행 보고
            if processed % 200 == 0:
                log.info(f"\n{'='*50}")
                log.info(f"중간 집계: {total_reviews:,}개 리뷰 / {processed:,}권")
                log.info(f"{'='*50}\n")

            time.sleep(random.uniform(0.5, 1.5))

    except KeyboardInterrupt:
        log.info("\n중단됨. 진행 상황 저장 완료.")
    except Exception as e:
        log.error(f"예상치 못한 오류: {e}", exc_info=True)

    log.info("\n" + "=" * 70)
    log.info("크롤링 완료!")
    log.info(f"   처리된 책: {processed:,}권")
    log.info(f"   수집된 리뷰: {total_reviews:,}개")
    log.info(f"   저장 위치: {os.path.abspath(OUTPUT_CSV)}")
    log.info("=" * 70)

if __name__ == "__main__":
    main()
