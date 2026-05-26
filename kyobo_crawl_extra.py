"""
교보문고 구매자 리뷰 추가 수집 - 100만건 확장판
================================================
변경사항:
  - MAX_REVIEWS_PER_BOOK: 200 → 1000
  - MAX_PAGES_PER_BOOK: 20 → 100
  - 검색어 대폭 확장 (새 카테고리/쿼리)
  - 출력 파일: kyobo_reviews_extra.csv (기존 보존)
  - done 파일: crawled_kyobo_extra.txt (별도 추적)
"""

import sys, os, re, json, csv, time, random, logging
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
        logging.FileHandler("logs/kyobo_extra.log", encoding="utf-8"),
        SafeStreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────
NAVER_CLIENT_ID     = "xaycKafg5L6rPQFiuw0x"
NAVER_CLIENT_SECRET = "nYRS3j1EhY"
NAVER_BOOK_API      = "https://openapi.naver.com/v1/search/book.json"

OUTPUT_CSV   = "kyobo_reviews_extra.csv"
DONE_FILE    = "crawled_kyobo_extra.txt"
BOOKS_FILE   = "kyobo_books_extra.json"

MAX_REVIEWS_PER_BOOK = 1000   # ↑ 200에서 1000으로 확장
MAX_PAGES_PER_BOOK   = 100    # ↑ 20에서 100으로 확장

CSV_COLUMNS = [
    "카테고리", "도서제목", "저자", "출판사", "ISBN", "출판일",
    "교보ID", "리뷰어ID", "별점", "리뷰내용", "리뷰날짜",
    "감정키워드", "revwPatrCode"
]

# ── 확장된 카테고리 & 검색어 ─────────────────────────────────────────────────
CATEGORIES = {
    "소설/시/희곡": [
        "베스트셀러 소설", "한국 소설", "일본 소설", "영미 소설",
        "SF 판타지", "무협 소설", "로맨스", "공포 소설", "성장소설",
        "노벨문학상", "맨부커상", "아쿠타가와상", "문학동네", "창비소설",
        "현대문학", "민음사 소설", "단편소설", "연작소설", "가족소설",
        "직장소설", "청춘소설", "페미니즘 소설", "추리 미스터리",
        "스릴러 소설", "범죄소설", "탐정소설", "역사소설 한국",
    ],
    "경제/경영": [
        "부자아빠 가난한아빠", "돈의 심리학", "주식 투자", "부동산 재테크",
        "경영전략", "마케팅 전략", "스타트업 창업", "리더십 경영",
        "회계 재무", "금융 투자", "ESG 경영", "디지털 전환",
        "비즈니스 모델", "협상 전략", "인사 조직", "컨설팅",
        "워런 버핏", "피터 드러커", "경영 명저", "기업 분석",
    ],
    "자기계발": [
        "아침 루틴", "독서법", "글쓰기", "말하기 스피치", "메모 노트",
        "시간 관리", "목표 달성", "의지력", "마인드셋", "성장 마인드",
        "인간관계", "설득력", "부자 마인드", "긍정 심리",
        "번아웃 회복", "자존감", "미라클 모닝", "집중력",
        "완벽주의 극복", "행복 심리학", "인생 설계",
    ],
    "인문학": [
        "서양철학", "동양철학", "소크라테스", "니체", "하이데거",
        "공자 논어", "장자", "인문학 입문", "교양 철학",
        "존재론", "인식론", "윤리학", "미학", "정치철학",
        "언어철학", "심리철학", "행복론", "죽음 철학",
        "신화학", "문화인류학", "기호학",
    ],
    "심리학": [
        "심리학 입문", "인지심리학", "사회심리학", "발달심리학",
        "임상심리학", "상담 심리", "트라우마", "MBTI 성격",
        "애착이론", "자아심리학", "무의식", "꿈 해몽",
        "행동심리학", "신경심리학", "정신분석", "심리치료",
        "감정 조절", "분노 조절", "우울증 극복", "불안 극복",
    ],
    "역사/문화": [
        "조선왕조", "고려시대", "삼국시대", "한국 근현대사",
        "일제강점기", "6.25전쟁", "민주화운동", "세계2차대전",
        "로마 제국", "중국 역사", "일본 역사", "유럽 역사",
        "문명의 충돌", "문화사", "동서양 교류", "고고학",
        "역사 인물", "왕의 역사", "전쟁의 역사",
    ],
    "사회과학": [
        "사회학 입문", "민주주의", "자본주의", "불평등",
        "젠더 연구", "페미니즘", "다문화", "이민 난민",
        "환경 문제", "기후변화", "에너지 정책", "복지 국가",
        "노동 문제", "청년 문제", "인구 문제", "도시 사회학",
        "미디어 사회학", "소비 사회", "디지털 사회",
    ],
    "컴퓨터/IT": [
        "ChatGPT 활용", "생성형 AI", "머신러닝 입문",
        "딥러닝 파이썬", "데이터 사이언스", "빅데이터",
        "자바스크립트", "리액트", "스프링 부트", "클린코드",
        "시스템 디자인", "알고리즘 자료구조", "코딩 테스트",
        "사이버 보안", "블록체인", "클라우드 AWS", "DevOps",
        "UX UI 디자인", "프로덕트 매니저", "데이터베이스",
    ],
    "과학": [
        "우주론", "천체물리학", "양자역학 입문", "상대성 이론",
        "진화론", "인체 해부학", "뇌과학 신경과학",
        "기후과학", "생태학", "분자생물학", "유전공학",
        "화학 반응", "소립자", "블랙홀", "빅뱅",
        "과학혁명", "과학사", "과학철학",
    ],
    "건강": [
        "단식 다이어트", "근력 운동", "요가 필라테스",
        "명상 마음챙김", "수면 건강", "면역력 강화",
        "암 예방", "당뇨 관리", "고혈압 심장", "정신건강",
        "노화 방지", "장 건강", "피부 관리", "두뇌 건강",
        "통증 관리", "재활 운동", "한의학", "영양학",
    ],
    "요리": [
        "한식 요리법", "중식 요리법", "일식 요리법", "이탈리안 요리",
        "베이킹 빵", "케이크 디저트", "채식 비건", "발효식품",
        "반찬 레시피", "다이어트 요리", "간단 요리", "밀프렙",
        "커피 바리스타", "와인 소믈리에", "칵테일 음료",
    ],
    "여행": [
        "유럽 자유여행", "일본 교토 오사카", "동남아 여행",
        "미국 여행", "제주도 여행", "부산 경주", "강원도 여행",
        "혼자 여행", "배낭여행 유럽", "세계일주",
        "캠핑 백패킹", "크루즈 여행", "남미 여행",
    ],
    "어린이/청소년": [
        "어린이 과학", "어린이 역사", "어린이 철학",
        "초등 국어", "초등 수학", "중학교 영어",
        "고등학교 국어", "수능 준비", "대입 전략",
        "진로 직업", "자녀교육", "창의력 교육",
        "독서교육", "영재교육",
    ],
    "종교/철학": [
        "성경 묵상", "불교 명상", "천주교 신앙",
        "이슬람 이해", "힌두교", "도교 노자",
        "명리학 사주", "풍수지리", "타로카드",
        "영적 성장", "깨달음", "수행 명상",
    ],
    "예술": [
        "미술 감상", "현대미술", "서양미술사",
        "동양화", "수채화 그림", "사진 촬영",
        "영화 감상", "영화 역사", "클래식 음악",
        "재즈 음악", "K팝", "뮤지컬",
        "건축 설계", "인테리어 디자인", "패션 디자인",
    ],
    "만화/라이트노벨": [
        "일본 만화", "웹툰", "순정만화", "소년만화",
        "BL 만화", "그래픽노벨", "미국 코믹스",
        "라이트노벨", "이세계 소설", "판타지 소설",
        "학습만화 역사", "학습만화 과학",
    ],
    "수험서": [
        "공무원 국어", "공무원 영어", "공무원 한국사",
        "TOEIC 토익", "TOEFL 토플", "OPIc 영어",
        "한국어능력시험 TOPIK", "컴퓨터활용능력",
        "공인중개사 시험", "회계사 세무사",
        "간호사 국가고시", "의사국시",
        "변호사 시험", "9급 공무원",
    ],
    "경제경영심화": [
        "Warren Buffett", "Steve Jobs biography",
        "Elon Musk biography", "Jeff Bezos Amazon",
        "McKinsey strategy", "Harvard Business",
        "startup funding", "venture capital",
        "behavioral economics", "game theory",
    ],
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
    try:
        url = f"https://search.kyobobook.co.kr/search?keyword={isbn}&target=total&gbCd=KOR"
        r = SESSION.get(url, timeout=10)
        if r.status_code != 200:
            return []
        sale_ids = re.findall(r'product\.kyobobook\.co\.kr/detail/(S\d+)', r.text)
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

def get_kyobo_reviews(sale_id: str, max_reviews: int = 1000) -> list[dict]:
    all_reviews = []

    for page in range(1, MAX_PAGES_PER_BOOK + 1):
        if len(all_reviews) >= max_reviews:
            break
        try:
            params = {
                "page":          page,
                "pageLimit":     10,
                "reviewSort":    "002",
                "revwPatrCode":  "002",   # 구매자 리뷰
                "saleCmdtids":   sale_id,
                "webToonYsno":   "N",
                "allYsno":       "N",
                "revwSummeryYn": "Y",
                "saleCmdtid":    sale_id,
            }
            r = SESSION.get(REVIEW_API, params=params, timeout=10)
            if r.status_code != 200:
                break
            review_list = r.json().get("data", {}).get("reviewList", [])
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
                break
        except Exception as e:
            log.debug(f"리뷰 오류 ({sale_id} p{page}): {e}")
            break

        time.sleep(random.uniform(0.2, 0.5))

    return all_reviews

# ── CSV & 상태 관리 ───────────────────────────────────────────────────────────
def init_csv():
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()

def append_csv(reviews: list[dict], cat: str, book: dict):
    rows = [{
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
    } for r in reviews]
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

# ── 기존 완료 목록 로드 (중복 방지) ──────────────────────────────────────────
def load_prev_done() -> set:
    """이전 크롤링에서 완료된 ISBN도 로드 (중복 수집 방지)"""
    s = set()
    if os.path.exists("crawled_kyobo.txt"):
        with open("crawled_kyobo.txt", encoding="utf-8") as f:
            s.update(l.strip() for l in f if l.strip())
    return s

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 70)
    log.info("교보문고 리뷰 100만건 확장 크롤러 시작!")
    log.info(f"   MAX_REVIEWS_PER_BOOK: {MAX_REVIEWS_PER_BOOK}")
    log.info(f"   검색 카테고리: {len(CATEGORIES)}개")
    log.info(f"   출력: {OUTPUT_CSV}")
    log.info("=" * 70)

    init_csv()
    done = load_done()
    prev_done = load_prev_done()   # 이전에 이미 수집한 책
    skip = done | prev_done        # 둘 다 건너뜀
    log.info(f"   이미 완료: {len(done)}개 / 이전 수집: {len(prev_done)}개")

    # ── 책 목록 수집 ─────────────────────────────────────────────────────────
    all_books = {}

    if os.path.exists(BOOKS_FILE):
        with open(BOOKS_FILE, encoding="utf-8") as f:
            all_books = json.load(f)
        log.info(f"책 목록 로드: {len(all_books):,}권")
    else:
        log.info("확장 카테고리 책 목록 수집 중...")
        for cat_name, queries in CATEGORIES.items():
            cat_count = 0
            for q in queries:
                books = search_naver_books(q, 100)
                for b in books:
                    if b["isbn"] not in all_books and b["isbn"] not in skip:
                        all_books[b["isbn"]] = {**b, "category": cat_name}
                        cat_count += 1
                time.sleep(random.uniform(0.2, 0.4))
            log.info(f"  [{cat_name}]: {cat_count:,}권 신규")

        with open(BOOKS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_books, f, ensure_ascii=False, indent=2)
        log.info(f"   총 {len(all_books):,}권 신규 → {BOOKS_FILE} 저장")

    # 이전에 수집했지만 리뷰를 더 가져올 수 있는 책도 포함
    # (기존 done 목록의 책들도 리뷰 1000개까지 재수집)
    log.info(f"\n크롤링 대상 (신규): {len(all_books):,}권")

    # ── 리뷰 크롤링 ─────────────────────────────────────────────────────────
    total_reviews = 0
    processed = 0
    books_list = list(all_books.items())

    try:
        for i, (isbn, book) in enumerate(books_list, 1):
            if isbn in done:
                continue

            cat = book.get("category", "기타")
            sale_ids = get_kyobo_sale_ids(isbn)
            if not sale_ids:
                mark_done(isbn)
                processed += 1
                time.sleep(random.uniform(0.3, 0.6))
                continue

            book_reviews = []
            for sale_id in sale_ids[:2]:
                reviews = get_kyobo_reviews(sale_id, MAX_REVIEWS_PER_BOOK)
                book_reviews.extend(reviews)
                if len(book_reviews) >= MAX_REVIEWS_PER_BOOK:
                    break

            # 중복 제거
            seen_texts = set()
            unique = []
            for rv in book_reviews:
                key = rv["text"][:50]
                if key not in seen_texts:
                    seen_texts.add(key)
                    unique.append(rv)

            if unique:
                append_csv(unique, cat, book)
                total_reviews += len(unique)
                log.info(f"[{i:,}/{len(books_list):,}] [{cat}] {book['title'][:35]}"
                         f" → {len(unique)}개 (누계: {total_reviews:,})")
            else:
                log.debug(f"[{i:,}] {book['title'][:35]} → 리뷰 없음")

            mark_done(isbn)
            processed += 1

            if processed % 500 == 0:
                log.info(f"\n{'='*50}")
                log.info(f"중간 집계: {total_reviews:,}개 / {processed:,}권")
                log.info(f"{'='*50}\n")

            time.sleep(random.uniform(0.4, 1.0))

    except KeyboardInterrupt:
        log.info("\n중단됨. 재시작하면 이어서 진행됩니다.")
    except Exception as e:
        log.error(f"오류: {e}", exc_info=True)

    log.info("\n" + "=" * 70)
    log.info("완료!")
    log.info(f"   처리: {processed:,}권 / 수집: {total_reviews:,}개")
    log.info(f"   파일: {os.path.abspath(OUTPUT_CSV)}")
    log.info("=" * 70)

if __name__ == "__main__":
    import json
    main()
