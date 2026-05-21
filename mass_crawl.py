"""
네이버 도서 구매자 리뷰 대규모 크롤러 - 최종 프로덕션 버전
============================================================
핵심 발견:
  - __NEXT_DATA__ (SSR)에 MallReviews 구매자 리뷰 데이터가 포함됨
  - 로그인 없이 접근 가능
  - 필드: reviewText, starScore, userId, registeredDate, mallName

전략:
  1. Naver Open API → 전 카테고리 책 목록 (nvMid) 수집
  2. Selenium → 각 책 리뷰 페이지 방문 + __NEXT_DATA__ 파싱
  3. 페이지네이션으로 추가 리뷰 수집
  4. CSV 증분 저장 (중단/재시작 지원)
"""

import sys, os, re, json, csv, time, random, logging
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import requests

# ── 로깅 ─────────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
# stdout 핸들러: 이모지/한글 인코딩 오류 방지
class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg.encode(stream.encoding or 'utf-8', errors='replace').decode(stream.encoding or 'utf-8', errors='replace') + self.terminator)
            self.flush()
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/crawl.log", encoding="utf-8"),
        SafeStreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────
NAVER_CLIENT_ID     = "xaycKafg5L6rPQFiuw0x"
NAVER_CLIENT_SECRET = "nYRS3j1EhY"
NAVER_BOOK_API      = "https://openapi.naver.com/v1/search/book.json"

OUTPUT_CSV   = "naver_book_reviews_ALL.csv"
DONE_FILE    = "crawled_nvmids.txt"
BOOKS_FILE   = "collected_books.json"

MAX_REVIEWS_PER_BOOK = 100   # 책당 최대 리뷰 수
MAX_PAGES_PER_BOOK   = 10    # 책당 최대 페이지 수 (페이지당 10개)
REFRESH_EVERY        = 150   # N권마다 드라이버 재시작

CSV_COLUMNS = [
    "카테고리", "도서제목", "저자", "출판사", "ISBN", "출판일",
    "nvMid", "구매처", "리뷰어ID", "별점", "리뷰내용", "리뷰날짜", "출처URL"
]

# ── 전체 카테고리 & 검색어 ────────────────────────────────────────────────────
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
    "유아":           ["그림책", "유아", "아기", "영유아", "보드북",
                      "아기그림책"],
    "청소년":         ["청소년소설", "진로", "청소년", "중학생", "고등학생"],
    "만화":           ["만화", "웹툰", "그래픽노블", "순정만화", "일본만화",
                      "학습만화"],
    "수험서/자격증":  ["공무원", "TOEIC", "자격증", "수능", "공인중개사",
                      "취업", "IT자격증", "한국어능력시험"],
    "어학":           ["영어회화", "일본어", "중국어", "영문법", "IELTS",
                      "어학", "스페인어", "프랑스어"],
    "외국도서":       ["foreign novel", "self help english", "business book",
                      "english learning", "science book english"],
}

# ── Selenium 드라이버 ─────────────────────────────────────────────────────────
def build_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(20)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    })
    return driver


def extract_next_data_reviews(page_source: str) -> tuple[list[dict], int]:
    """__NEXT_DATA__에서 MallReviews 리뷰 목록과 총 개수를 추출합니다."""
    reviews = []
    total = 0
    try:
        soup = BeautifulSoup(page_source, "html.parser")
        nd_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not nd_tag:
            return [], 0

        nd = json.loads(nd_tag.string)
        queries = nd["props"]["pageProps"]["dehydratedState"]["queries"]

        for q in queries:
            qk = str(q.get("queryKey", ""))
            if "MallReviews" not in qk:
                continue
            pages_data = q.get("state", {}).get("data", {}).get("pages", [])
            for page_data in pages_data:
                mr = page_data.get("MallReviews", {})
                if not total:
                    total = mr.get("totalCount", 0)
                for item in mr.get("reviewList", []):
                    text = item.get("reviewText", "").strip()
                    if text:
                        reviews.append({
                            "text":     text,
                            "score":    item.get("starScore", ""),
                            "user":     item.get("userId", ""),
                            "date":     item.get("registeredDate", ""),
                            "mall":     item.get("mallName", ""),
                        })
    except Exception as e:
        log.debug(f"  __NEXT_DATA__ 파싱 오류: {e}")
    return reviews, total


def get_book_reviews(driver, nv_mid: str, max_reviews: int = 100) -> list[dict]:
    """책 하나의 리뷰를 수집합니다 (페이지네이션 포함)."""
    all_reviews = []
    seen_texts  = set()
    base_url    = f"https://search.shopping.naver.com/book/catalog/{nv_mid}"

    for page_num in range(1, MAX_PAGES_PER_BOOK + 1):
        if len(all_reviews) >= max_reviews:
            break

        url = f"{base_url}?tab=review" + (f"&page={page_num}" if page_num > 1 else "")
        try:
            driver.get(url)
            time.sleep(random.uniform(2.5, 4.0))
        except Exception as e:
            log.warning(f"  페이지 로드 실패: {e}")
            break

        reviews, total = extract_next_data_reviews(driver.page_source)

        if not reviews:
            break   # 더 이상 리뷰 없음

        new_count = 0
        for r in reviews:
            key = r["text"][:50]
            if key not in seen_texts:
                seen_texts.add(key)
                all_reviews.append(r)
                new_count += 1

        if new_count == 0:
            break   # 중복만 나오면 더 이상 진행 불필요

        # 총 리뷰 수가 한 페이지 분량이면 종료
        if total <= 10 or len(all_reviews) >= total:
            break

        time.sleep(random.uniform(0.5, 1.0))

    return all_reviews


# ── Naver Open API: 책 목록 수집 ─────────────────────────────────────────────
def search_books(query: str, max_books: int = 100) -> list[dict]:
    books, seen, start = [], set(), 1
    while len(books) < max_books:
        try:
            resp = requests.get(
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
            log.warning(f"  API 오류: {e}")
            break

        for item in items:
            link = item.get("link", "")
            m = re.search(r"/catalog/(\d+)", link)
            nv_mid = m.group(1) if m else ""
            if not nv_mid or nv_mid in seen:
                continue
            seen.add(nv_mid)
            isbn_raw = item.get("isbn", "")
            isbn = isbn_raw.split()[0] if isbn_raw.strip() else ""
            books.append({
                "title":     re.sub(r"<[^>]+>", "", item.get("title", "")),
                "author":    re.sub(r"<[^>]+>", "", item.get("author", "")),
                "publisher": item.get("publisher", ""),
                "isbn":      isbn,
                "pubdate":   item.get("pubdate", ""),
                "nv_mid":    nv_mid,
            })
            if len(books) >= max_books:
                break

        if len(items) < 100:
            break
        start += 100
        time.sleep(0.2)

    return books


# ── CSV & 상태 관리 ───────────────────────────────────────────────────────────
def init_csv():
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
        log.info(f"📄 CSV 생성: {OUTPUT_CSV}")


def append_csv(reviews: list[dict], category: str, book: dict):
    rows = []
    for r in reviews:
        rows.append({
            "카테고리":  category,
            "도서제목":  book["title"],
            "저자":      book["author"],
            "출판사":    book["publisher"],
            "ISBN":      book["isbn"],
            "출판일":    book["pubdate"],
            "nvMid":     book["nv_mid"],
            "구매처":    r["mall"],
            "리뷰어ID":  r["user"],
            "별점":      r["score"],
            "리뷰내용":  r["text"],
            "리뷰날짜":  r["date"],
            "출처URL":   f"https://search.shopping.naver.com/book/catalog/{book['nv_mid']}",
        })
    if rows:
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerows(rows)


def load_done() -> set:
    if not os.path.exists(DONE_FILE):
        return set()
    with open(DONE_FILE, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def mark_done(nv_mid: str):
    with open(DONE_FILE, "a", encoding="utf-8") as f:
        f.write(nv_mid + "\n")


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 70)
    log.info("🚀 네이버 도서 구매자 리뷰 대규모 크롤러 시작!")
    log.info(f"   방식: __NEXT_DATA__ SSR 파싱 (로그인 불필요)")
    log.info(f"   카테고리: {len(CATEGORIES)}개")
    log.info(f"   출력 파일: {OUTPUT_CSV}")
    log.info("=" * 70)

    init_csv()
    done = load_done()
    log.info(f"   이미 완료된 책: {len(done)}개")

    # ── 1단계: 전 카테고리 책 목록 수집 ──────────────────────────────────────
    all_books = {}   # nv_mid → book dict

    if os.path.exists(BOOKS_FILE):
        with open(BOOKS_FILE, encoding="utf-8") as f:
            all_books = json.load(f)
        log.info(f"📚 저장된 책 목록 로드: {len(all_books)}권")
    else:
        log.info("📚 전 카테고리 책 목록 수집 중...")
        for cat_name, queries in CATEGORIES.items():
            cat_count = 0
            for q in queries:
                books = search_books(q, 100)
                for b in books:
                    if b["nv_mid"] not in all_books:
                        all_books[b["nv_mid"]] = {**b, "category": cat_name}
                        cat_count += 1
                time.sleep(random.uniform(0.2, 0.5))
            log.info(f"  [{cat_name}]: {cat_count}권 수집")

        with open(BOOKS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_books, f, ensure_ascii=False, indent=2)
        log.info(f"   총 {len(all_books)}권 수집 완료 → {BOOKS_FILE} 저장")

    log.info(f"\n📊 크롤링 대상: {len(all_books):,}권")

    # ── 2단계: 각 책 리뷰 크롤링 ─────────────────────────────────────────────
    driver = build_driver()
    total_reviews = 0
    processed     = 0
    books_list    = list(all_books.items())

    try:
        for i, (nv_mid, book) in enumerate(books_list, 1):
            if nv_mid in done:
                continue

            # 주기적 드라이버 재시작
            if processed > 0 and processed % REFRESH_EVERY == 0:
                log.info("🔄 드라이버 재시작...")
                driver.quit()
                driver = build_driver()
                time.sleep(2)

            cat = book.get("category", "기타")
            log.info(f"[{i:,}/{len(books_list):,}] [{cat}] {book['title'][:35]} ({nv_mid})")

            reviews = get_book_reviews(driver, nv_mid, MAX_REVIEWS_PER_BOOK)

            if reviews:
                append_csv(reviews, cat, book)
                total_reviews += len(reviews)
                log.info(f"   ✅ {len(reviews)}개 수집 (누계: {total_reviews:,}개)")
            else:
                log.info(f"   ℹ️  리뷰 없음")

            mark_done(nv_mid)
            processed += 1

            # 진행 보고
            if total_reviews > 0 and total_reviews % 5000 == 0:
                log.info(f"\n{'='*50}")
                log.info(f"📊 중간 집계: {total_reviews:,}개 리뷰 / {processed:,}권 처리")
                log.info(f"{'='*50}\n")

            time.sleep(random.uniform(1.0, 2.5))

    except KeyboardInterrupt:
        log.info("\n⚠️  중단됨. 데이터 저장 완료.")
    finally:
        driver.quit()

    log.info("\n" + "=" * 70)
    log.info(f"✅ 크롤링 완료!")
    log.info(f"   처리된 책: {processed:,}권")
    log.info(f"   수집된 리뷰: {total_reviews:,}개")
    log.info(f"   저장 위치: {os.path.abspath(OUTPUT_CSV)}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
