"""매일 아침 재테크 뉴스 브리핑 메일 발송 (무료, 유료 API 미사용).

1. 국내외 신뢰할 수 있는 언론사 RSS에서 전날(KST) 이후 기사를 수집
   (쿠키 동의창·페이월로 요약을 못 가져오는 매체는 제외)
2. 재테크 키워드 점수로 국내 5건 / 해외 5건 선정 (중복·같은 주제 편중 제거)
3. 기사 요약문(RSS 설명 + 원문 페이지의 요약 메타태그)에서 2~3문장 발췌
4. 해외 뉴스는 국내 언론사의 국제 보도(이미 한글)를 우선 쓰고, 부족하면 해외
   매체 기사를 무료 번역(Google 번역 웹)으로 한국어 변환. 모든 해외 뉴스는
   한국어로 발송되며, 번역 실패 시에만 원문을 함께 표기
5. 키워드·기업명 사전으로 관련 주식 연결
6. 주요 지수·환율·유가 스냅샷과 함께 HTML 이메일로 발송
"""
import html
import os
import re
import smtplib
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import yfinance as yf
from deep_translator import GoogleTranslator, MyMemoryTranslator

KST = timezone(timedelta(hours=9))
USER_AGENT = "Mozilla/5.0 (compatible; news-digest/1.0)"

# =========================
# 신뢰할 수 있는 언론사 RSS
# =========================
KOREAN_FEEDS = [
    ("연합뉴스", "https://www.yna.co.kr/rss/economy.xml"),
    ("연합뉴스", "https://www.yna.co.kr/rss/market.xml"),
    ("한국경제", "https://www.hankyung.com/feed/economy"),
    ("한국경제", "https://www.hankyung.com/feed/finance"),
    ("매일경제", "https://www.mk.co.kr/rss/30100041/"),  # 경제
    ("매일경제", "https://www.mk.co.kr/rss/50200011/"),  # 증권
]

# 국내 언론사가 이미 한글로 보도한 해외(국제) 뉴스 - 번역 없이 그대로 사용
KOREAN_WORLD_FEEDS = [
    ("연합뉴스", "https://www.yna.co.kr/rss/international.xml"),
    ("한국경제", "https://www.hankyung.com/feed/international"),
    ("매일경제", "https://www.mk.co.kr/rss/30300018/"),  # 국제
]

# 해외 원문 매체 - 번역해서 사용. 쿠키 동의창을 띄우거나 접속 시 페이월로 막는
# 매체(Bloomberg 등)는 요약문을 못 가져오므로 제외.
GLOBAL_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),  # Top News
    ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),  # Economy
    ("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),  # Finance
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Wall Street Journal", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
]

MAX_ITEMS_PER_FEED = 30
PICKS_PER_REGION = 5
MAX_PER_SOURCE = 2
MAX_PER_TOPIC = 2
MAX_SUMMARY_CHARS = 320

# =========================
# 재테크 주제 사전: 키워드 → 가중치, 관련 주식
# 키워드는 소문자 비교 (영문은 단어 단위 일치, 복수형 s/es 허용)
# =========================
TOPICS = [
    {
        "name": "환율",
        "weight": 5,
        "keywords": ["환율", "원/달러", "원·달러", "원달러", "달러 강세", "달러 약세", "외환", "exchange rate", "dollar", "currency", "forex"],
        "stocks": [("현대차", "005380.KS", "원화 약세 시 수출 채산성 개선 수혜 대표 수출주"),
                   ("삼성전자", "005930.KS", "달러 매출 비중이 높아 환율 변동 영향이 큰 종목"),
                   ("대한항공", "003490.KS", "달러 부채·유류비 비중이 커 환율에 민감한 종목")],
    },
    {
        "name": "금리·통화정책",
        "weight": 5,
        "keywords": ["금리", "기준금리", "연준", "fomc", "한국은행", "한은", "파월", "국채", "금통위", "fed", "federal reserve", "interest rate", "rate cut", "rate hike", "treasury", "yield", "powell", "bond"],
        "stocks": [("KB금융", "105560.KS", "금리 수준이 순이자마진에 직결되는 대표 은행주"),
                   ("JPMorgan Chase", "JPM", "미국 금리·경기 방향에 민감한 대표 은행주"),
                   ("iShares 20+ Year Treasury Bond ETF", "TLT", "금리 인하 기대 시 가격이 오르는 장기 국채 ETF")],
    },
    {
        "name": "유가·에너지",
        "weight": 5,
        "keywords": ["유가", "원유", "wti", "브렌트", "opec", "석유", "정유", "oil", "crude", "brent", "gasoline", "natural gas", "energy"],
        "stocks": [("S-Oil", "010950.KS", "유가·정제마진 변동에 실적이 연동되는 정유주"),
                   ("Exxon Mobil", "XOM", "유가 상승 시 수혜를 받는 미국 대표 에너지주"),
                   ("대한항공", "003490.KS", "유가 상승 시 연료비 부담이 커지는 항공주")],
    },
    {
        "name": "한국 증시",
        "weight": 4,
        "keywords": ["코스피", "코스닥", "증시", "외국인 순매수", "외국인 순매도", "공매도", "밸류업", "kospi", "kosdaq"],
        "stocks": [("KODEX 200", "069500.KS", "코스피200 지수를 추종하는 대표 ETF"),
                   ("삼성전자", "005930.KS", "코스피 시가총액 1위로 지수 방향을 좌우하는 종목")],
    },
    {
        "name": "미국 증시",
        "weight": 4,
        "keywords": ["뉴욕증시", "나스닥", "s&p", "다우", "월가", "wall street", "nasdaq", "dow jones", "stocks", "stock market", "equities"],
        "stocks": [("SPDR S&P 500 ETF", "SPY", "미국 대형주 전체 흐름을 추종하는 대표 ETF"),
                   ("Invesco QQQ", "QQQ", "나스닥100 기술주 흐름을 추종하는 ETF")],
    },
    {
        "name": "물가·경기",
        "weight": 4,
        "keywords": ["물가", "인플레", "cpi", "pce", "gdp", "성장률", "경기침체", "고용", "실업률", "수출", "무역수지", "inflation", "recession", "jobs", "payroll", "unemployment", "economy", "consumer", "retail sales"],
        "stocks": [("SPDR S&P 500 ETF", "SPY", "미국 경기 지표에 따라 움직이는 대표 지수 ETF"),
                   ("KODEX 200", "069500.KS", "국내 경기·수출 흐름을 반영하는 대표 지수 ETF")],
    },
    {
        "name": "관세·무역",
        "weight": 4,
        "keywords": ["관세", "무역협상", "무역분쟁", "수출규제", "tariff", "trade war", "trade deal", "export control", "sanction"],
        "stocks": [("현대차", "005380.KS", "미국 관세 정책에 직접 영향을 받는 수출 자동차주"),
                   ("POSCO홀딩스", "005490.KS", "철강 관세·무역 규제에 민감한 종목"),
                   ("Apple", "AAPL", "중국 생산 비중이 커 관세 이슈에 민감한 종목")],
    },
    {
        "name": "반도체",
        "weight": 3,
        "keywords": ["반도체", "메모리", "hbm", "d램", "디램", "낸드", "파운드리", "semiconductor", "chip", "memory", "foundry"],
        "stocks": [("SK하이닉스", "000660.KS", "HBM·메모리 업황의 대표 수혜주"),
                   ("삼성전자", "005930.KS", "메모리·파운드리 업황에 직접 연동되는 종목"),
                   ("NVIDIA", "NVDA", "AI 반도체 수요를 대표하는 종목")],
    },
    {
        "name": "AI·빅테크",
        "weight": 3,
        "keywords": ["인공지능", "ai", "빅테크", "데이터센터", "artificial intelligence", "data center", "big tech", "cloud"],
        "stocks": [("NVIDIA", "NVDA", "AI 인프라 투자 확대의 핵심 수혜주"),
                   ("Microsoft", "MSFT", "클라우드·AI 서비스 대표 빅테크"),
                   ("SK하이닉스", "000660.KS", "AI 서버용 HBM 공급 수혜주")],
    },
    {
        "name": "2차전지·전기차",
        "weight": 3,
        "keywords": ["2차전지", "이차전지", "배터리", "전기차", "리튬", "battery", "electric vehicle", "ev", "lithium"],
        "stocks": [("LG에너지솔루션", "373220.KS", "국내 대표 배터리 제조사"),
                   ("Tesla", "TSLA", "전기차 수요를 대표하는 종목")],
    },
    {
        "name": "자동차",
        "weight": 3,
        "keywords": ["자동차", "완성차", "automaker", "auto sales", "car sales"],
        "stocks": [("현대차", "005380.KS", "국내 대표 완성차 업체"),
                   ("기아", "000270.KS", "수출 비중이 높은 완성차 업체")],
    },
    {
        "name": "조선·방산",
        "weight": 3,
        "keywords": ["조선", "수주", "방산", "방위산업", "shipbuilding", "defense", "military"],
        "stocks": [("HD한국조선해양", "009540.KS", "국내 대표 조선 지주사"),
                   ("한화에어로스페이스", "012450.KS", "국내 대표 방산 종목"),
                   ("Lockheed Martin", "LMT", "미국 대표 방산 종목")],
    },
    {
        "name": "금·원자재",
        "weight": 3,
        "keywords": ["금값", "금 가격", "국제 금", "구리", "원자재", "gold", "copper", "commodity", "commodities"],
        "stocks": [("SPDR Gold Shares", "GLD", "국제 금 가격을 추종하는 ETF"),
                   ("고려아연", "010130.KS", "비철금속 가격에 연동되는 제련 기업")],
    },
    {
        "name": "부동산",
        "weight": 2,
        "keywords": ["부동산", "아파트", "주택", "집값", "전세", "real estate", "housing", "mortgage", "home sales"],
        "stocks": [("현대건설", "000720.KS", "주택 경기에 민감한 대표 건설주"),
                   ("Vanguard Real Estate ETF", "VNQ", "미국 리츠 전반을 추종하는 ETF")],
    },
    {
        "name": "가상자산",
        "weight": 2,
        "keywords": ["비트코인", "가상자산", "암호화폐", "코인", "bitcoin", "crypto", "cryptocurrency", "ethereum"],
        "stocks": [("Coinbase", "COIN", "가상자산 거래량에 실적이 연동되는 거래소"),
                   ("iShares Bitcoin Trust", "IBIT", "비트코인 현물 ETF")],
    },
    {
        "name": "실적·기업",
        "weight": 2,
        "keywords": ["실적", "영업이익", "매출", "어닝", "배당", "자사주", "ipo", "상장", "인수", "합병", "earnings", "revenue", "profit", "guidance", "dividend", "buyback", "merger", "acquisition"],
        "stocks": [],
    },
]

# 기사에 기업명이 직접 나오면 우선 연결
COMPANIES = [
    (["삼성전자", "samsung electronics", "samsung"], "삼성전자", "005930.KS"),
    (["sk하이닉스", "하이닉스", "sk hynix"], "SK하이닉스", "000660.KS"),
    (["현대차", "현대자동차", "hyundai motor", "hyundai"], "현대차", "005380.KS"),
    (["기아"], "기아", "000270.KS"),
    (["lg에너지솔루션", "lg엔솔"], "LG에너지솔루션", "373220.KS"),
    (["네이버", "naver"], "NAVER", "035420.KS"),
    (["카카오"], "카카오", "035720.KS"),
    (["셀트리온"], "셀트리온", "068270.KS"),
    (["삼성바이오로직스"], "삼성바이오로직스", "207940.KS"),
    (["한화에어로스페이스"], "한화에어로스페이스", "012450.KS"),
    (["포스코", "posco"], "POSCO홀딩스", "005490.KS"),
    (["엔비디아", "nvidia"], "NVIDIA", "NVDA"),
    (["애플", "apple"], "Apple", "AAPL"),
    (["마이크로소프트", "microsoft"], "Microsoft", "MSFT"),
    (["알파벳", "구글", "alphabet", "google"], "Alphabet", "GOOGL"),
    (["아마존", "amazon"], "Amazon", "AMZN"),
    (["메타", "meta platforms", "facebook"], "Meta", "META"),
    (["테슬라", "tesla"], "Tesla", "TSLA"),
    (["팔란티어", "palantir"], "Palantir", "PLTR"),
    (["tsmc"], "TSMC", "TSM"),
    (["브로드컴", "broadcom"], "Broadcom", "AVGO"),
    (["마이크론", "micron"], "Micron", "MU"),
    (["인텔", "intel"], "Intel", "INTC"),
    (["amd"], "AMD", "AMD"),
    (["넷플릭스", "netflix"], "Netflix", "NFLX"),
    (["보잉", "boeing"], "Boeing", "BA"),
    (["버크셔", "berkshire"], "Berkshire Hathaway", "BRK-B"),
    (["jp모건", "jpmorgan"], "JPMorgan Chase", "JPM"),
    (["골드만삭스", "goldman sachs"], "Goldman Sachs", "GS"),
]

# 재테크와 무관한 기사 제외
EXCLUDE_KEYWORDS = ["부고", "인사]", "[인사", "포토", "[사진", "게시판", "운세", "연예", "스포츠", "obituary", "podcast", "quiz", "horoscope"]

# 이메일 상단 시장 지표
MARKET_TICKERS = [
    ("코스피", "^KS11"),
    ("코스닥", "^KQ11"),
    ("S&P 500", "^GSPC"),
    ("나스닥", "^IXIC"),
    ("다우존스", "^DJI"),
    ("원/달러 환율", "KRW=X"),
    ("달러 인덱스", "DX-Y.NYB"),
    ("WTI 유가", "CL=F"),
    ("브렌트 유가", "BZ=F"),
    ("미 10년물 금리(%)", "^TNX"),
    ("금", "GC=F"),
]


# =========================
# 뉴스 수집
# =========================
def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def entry_time(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def collect_news(feeds, since, needs_translation):
    items = []
    seen = set()
    for source, url in feeds:
        try:
            feed = feedparser.parse(url, agent=USER_AGENT)
        except Exception as e:
            print(f"[경고] {source} 피드 수집 실패 ({url}): {e}")
            continue
        if not feed.entries:
            print(f"[경고] {source} 피드에 기사가 없습니다 ({url})")
            continue

        for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
            link = entry.get("link", "").strip()
            title = clean_text(entry.get("title"))
            if not link or not title or link in seen or title in seen:
                continue
            published = entry_time(entry)
            if published and published < since:
                continue
            seen.update([link, title])
            items.append({
                "source": source,
                "title": title,
                "summary": clean_text(entry.get("summary")),
                "url": link,
                "published": published,
                "needs_translation": needs_translation,
            })
    print(f"[정보] {'/'.join(s for s, _ in feeds)} 후보 기사 {len(items)}건 수집")
    return items


# =========================
# 키워드 점수로 기사 선정
# =========================
def contains(text, keyword):
    if re.fullmatch(r"[a-z0-9&/\-\. ]+", keyword):
        # 영문 키워드는 단어 단위로만 일치 (예: "ai"가 "air"에 걸리지 않게)
        return re.search(r"(?<![a-z])" + re.escape(keyword) + r"(?:s|es)?(?![a-z])", text) is not None
    return keyword in text


def score_item(item):
    title = item["title"].lower()
    body = item["summary"].lower()
    if any(k in title for k in EXCLUDE_KEYWORDS):
        return 0, []
    score = 0
    topics = []
    for topic in TOPICS:
        in_title = any(contains(title, k) for k in topic["keywords"])
        in_body = any(contains(body, k) for k in topic["keywords"])
        if in_title or in_body:
            score += topic["weight"] * (2 if in_title else 1)
            topics.append(topic)
    # 제목 매칭이 강한 주제를 대표 주제로
    topics.sort(key=lambda t: -(t["weight"] * (2 if any(contains(title, k) for k in t["keywords"]) else 1)))
    return score, topics


def title_tokens(title):
    title = title.lower()
    words = re.findall(r"[a-z0-9]+|[가-힣]+", title)
    # 한글은 2글자 단위로 쪼개 유사도 비교
    tokens = set()
    for w in words:
        if re.match(r"[가-힣]", w) and len(w) > 2:
            tokens.update(w[i:i + 2] for i in range(len(w) - 1))
        else:
            tokens.add(w)
    return tokens


def is_duplicate(item, picked):
    tokens = title_tokens(item["title"])
    for p in picked:
        other = title_tokens(p["title"])
        if tokens and other and len(tokens & other) / len(tokens | other) > 0.4:
            return True
    return False


def select_top(items, limit=PICKS_PER_REGION):
    scored = []
    for item in items:
        score, topics = score_item(item)
        if score > 0:
            item["score"], item["topics"] = score, topics
            scored.append(item)
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    scored.sort(key=lambda it: (it["score"], it["published"] or oldest), reverse=True)

    picked = []
    # 1차: 언론사·주제 편중 제한, 2차: 제한 없이 빈자리 채우기
    for strict in (True, False):
        for item in scored:
            if len(picked) == limit:
                return picked
            if item in picked or is_duplicate(item, picked):
                continue
            if strict:
                same_source = sum(p["source"] == item["source"] for p in picked)
                same_topic = sum(p["topics"][0]["name"] == item["topics"][0]["name"] for p in picked)
                if same_source >= MAX_PER_SOURCE or same_topic >= MAX_PER_TOPIC:
                    continue
            picked.append(item)
    return picked


# =========================
# 요약 / 번역 / 관련 주식
# =========================
META_PATTERNS = [
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description',
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description',
]


def fetch_page_description(url):
    """원문 페이지의 og:description (언론사가 직접 제공하는 요약문)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            page = resp.read(400_000).decode(charset, errors="ignore")
    except Exception as e:
        print(f"[경고] 원문 페이지 조회 실패 ({url}): {e}")
        return ""
    for pattern in META_PATTERNS:
        m = re.search(pattern, page, re.IGNORECASE)
        if m:
            return clean_text(m.group(1))
    return ""


def strip_byline(text):
    text = re.sub(r"^\s*[\[\(][^\]\)]{0,40}(=|뉴스|기자)[^\]\)]{0,40}[\]\)]\s*", "", text)  # [서울=연합뉴스] / (서울=연합뉴스)
    text = re.sub(r"^\s*[가-힣]{2,4}\s*(기자|특파원)\s*=\s*", "", text)  # 홍길동 기자 =
    text = re.sub(r"\S+@\S+", "", text)
    return text.strip()


def make_summary(item):
    candidates = [item["summary"], fetch_page_description(item["url"])]
    text = max((strip_byline(c) for c in candidates), key=len)
    if len(text) < 20 or text == item["title"]:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = ""
    for i, s in enumerate(sentences):
        if i >= 3 or (i >= 2 and len(summary) + len(s) > MAX_SUMMARY_CHARS):
            break
        summary = f"{summary} {s}".strip()
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
    return summary


TRANSLATE_MIN_INTERVAL = 1.2  # 초 (요청 폭주 방지용 최소 간격)
TRANSLATE_RETRIES = 2
_last_translate_at = 0.0
_google_blocked = False  # 이번 실행에서 구글 번역이 계속 막히면 이후 호출은 바로 대체 서비스로


def _throttle():
    global _last_translate_at
    wait = TRANSLATE_MIN_INTERVAL - (time.monotonic() - _last_translate_at)
    if wait > 0:
        time.sleep(wait)
    _last_translate_at = time.monotonic()


def translate_ko(text):
    """구글 번역(무료)을 우선 시도하고, 요청이 계속 막히면 MyMemory(무료, 가입 불필요)로 넘어간다."""
    global _google_blocked
    if not text:
        return text

    if not _google_blocked:
        for attempt in range(1, TRANSLATE_RETRIES + 1):
            _throttle()
            try:
                return GoogleTranslator(source="auto", target="ko").translate(text) or text
            except Exception as e:
                is_rate_limited = "too many requests" in str(e).lower()
                if not is_rate_limited:
                    print(f"[경고] 구글 번역 실패: {e}")
                    break
                if attempt == TRANSLATE_RETRIES:
                    print(f"[경고] 구글 번역이 차단된 것으로 보여 이후 기사는 대체 번역 서비스를 사용합니다: {e}")
                    _google_blocked = True
                else:
                    time.sleep(3 * attempt)

    try:
        _throttle()
        # GLOBAL_FEEDS는 전부 영어 매체이므로 출발 언어를 명시한다.
        # MyMemory는 "auto"를 지원하지 않고, 지원하지 않는 언어 코드를 줘도 예외 대신
        # 안내 문구를 번역 결과인 것처럼 그대로 돌려주므로 결과 텍스트도 검사해야 한다.
        result = MyMemoryTranslator(source="en-US", target="ko-KR").translate(text)
        if not result or "INVALID SOURCE LANGUAGE" in result.upper():
            print(f"[경고] 대체 번역 응답이 올바르지 않아 원문 유지: {result}")
            return text
        return result
    except Exception as e:
        print(f"[경고] 대체 번역도 실패, 원문 유지: {e}")
        return text


def related_stocks(item, limit=3):
    text = f"{item['title']} {item['summary']}".lower()
    stocks = []
    for aliases, name, ticker in COMPANIES:
        if any(contains(text, a) for a in aliases):
            stocks.append((name, ticker, "기사에 직접 언급된 기업"))
    for topic in item["topics"]:
        stocks += [(n, t, f"[{topic['name']}] {r}") for n, t, r in topic["stocks"]]

    result, seen = [], set()
    for name, ticker, reason in stocks:
        if ticker not in seen:
            seen.add(ticker)
            result.append({"name": name, "ticker": ticker, "reason": reason})
        if len(result) == limit:
            break
    return result


def build_entries(picked):
    entries = []
    for item in picked:
        summary = make_summary(item)
        headline = item["title"]
        translate = item["needs_translation"]
        if translate:
            headline, summary = translate_ko(headline), translate_ko(summary)
        entries.append({
            "headline": headline,
            "original_title": item["title"] if translate else "",
            "summary": summary or "(요약 정보가 제공되지 않는 기사입니다. 원문 링크를 확인해 주세요.)",
            "topics": ", ".join(t["name"] for t in item["topics"][:3]),
            "stocks": related_stocks(item),
            "source": item["source"],
            "published": item["published"].astimezone(KST).strftime("%Y-%m-%d %H:%M") if item["published"] else "",
            "url": item["url"],
        })
    return entries


# =========================
# 시장 지표
# =========================
def fetch_market_snapshot():
    rows = []
    for name, ticker in MARKET_TICKERS:
        try:
            df = yf.download(ticker, period="10d", interval="1d", progress=False, auto_adjust=True)
            close = df["Close"].squeeze().dropna()
            if len(close) < 2:
                continue
            last, prev = float(close.iloc[-1]), float(close.iloc[-2])
            rows.append({
                "name": name,
                "value": last,
                "change": (last - prev) / prev * 100,
                "date": close.index[-1].strftime("%m/%d"),
            })
        except Exception as e:
            print(f"[경고] {name}({ticker}) 시세 조회 실패: {e}")
    return rows


# =========================
# 이메일 본문
# =========================
def render_market_html(rows):
    if not rows:
        return ""
    cells = ""
    for r in rows:
        color = "#d32f2f" if r["change"] > 0 else "#1565c0" if r["change"] < 0 else "#555"
        cells += (
            f"<tr><td style='padding:4px 10px;border-bottom:1px solid #eee;'>{r['name']}</td>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #eee;text-align:right;'>{r['value']:,.2f}</td>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #eee;text-align:right;color:{color};'>{r['change']:+.2f}%</td>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #eee;color:#888;'>{r['date']}</td></tr>"
        )
    return (
        "<h3 style='margin-top:24px;'>📊 주요 시장 지표 (전일 대비)</h3>"
        f"<table style='border-collapse:collapse;font-size:14px;'>{cells}</table>"
    )


def render_news_html(title, entries):
    blocks = ""
    for i, e in enumerate(entries, 1):
        stocks = "<br>".join(
            f"· <b>{html.escape(s['name'])}</b> ({html.escape(s['ticker'])}) – {html.escape(s['reason'])}"
            for s in e["stocks"]
        ) or "· 직접 연결되는 종목 없음"
        original = f"원문 제목: {html.escape(e['original_title'])}<br>" if e["original_title"] else ""
        url = html.escape(e["url"])
        blocks += f"""
        <div style="margin:0 0 22px 0;">
            <div style="font-size:16px;font-weight:bold;">{i}. {html.escape(e['headline'])}</div>
            <div style="margin:6px 0 0 0;line-height:1.6;">{html.escape(e['summary'])}</div>
            <div style="margin:8px 0 0 0;padding:8px 10px;background:#f6f8fa;border-radius:6px;font-size:14px;">
                <b>📈 관련 주식</b> <span style="color:#888;font-size:12px;">({html.escape(e['topics'])})</span><br>{stocks}
            </div>
            <div style="margin:6px 0 0 0;font-size:13px;color:#666;">
                {original}출처: {html.escape(e['source'])} ({e['published']})<br>
                <a href="{url}">{url}</a>
            </div>
        </div>"""
    if not blocks:
        blocks = "<p>조건에 맞는 기사가 없습니다.</p>"
    return f"<h3 style='margin-top:24px;'>{title}</h3>{blocks}"


def render_news_text(title, entries):
    lines = [title, ""]
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. {e['headline']}")
        lines.append(e["summary"])
        lines.append(f"관련 주식 ({e['topics']}):")
        lines += [f"  - {s['name']} ({s['ticker']}): {s['reason']}" for s in e["stocks"]] or ["  - 직접 연결되는 종목 없음"]
        if e["original_title"]:
            lines.append(f"원문 제목: {e['original_title']}")
        lines.append(f"출처: {e['source']} ({e['published']})")
        lines.append(e["url"])
        lines.append("")
    return "\n".join(lines)


DISCLAIMER = ("※ 뉴스는 재테크 키워드 기준으로 자동 선정·발췌되었습니다. 해외 뉴스는 국내 언론사의 국제 보도를 우선 사용하고, "
              "부족하면 해외 매체 기사를 자동 번역해 채웁니다. 관련 주식은 주제별로 미리 정한 참고 종목이며 투자 권유가 아닙니다. "
              "투자 판단과 책임은 본인에게 있습니다.")


def build_email(korea, world, market_rows, today):
    html_body = f"""
    <html><body style="font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;max-width:720px;color:#222;">
        <h2>🗞️ {today} 재테크 모닝 브리핑</h2>
        {render_market_html(market_rows)}
        {render_news_html("🇰🇷 한국 주요 뉴스", korea)}
        {render_news_html("🌎 해외 주요 뉴스", world)}
        <p style="font-size:12px;color:#888;border-top:1px solid #ddd;padding-top:10px;">{DISCLAIMER}</p>
    </body></html>"""
    text_body = "\n".join([
        f"{today} 재테크 모닝 브리핑",
        "",
        render_news_text("[한국 주요 뉴스]", korea),
        render_news_text("[해외 주요 뉴스]", world),
        DISCLAIMER,
    ])
    return html_body, text_body


def send_email(html_content, text_content, subject):
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    mail_to_raw = os.environ.get("NEWS_MAIL_TO")

    if not gmail_address or not gmail_app_password or not mail_to_raw:
        print("[에러] 이메일 관련 환경 변수(GMAIL_ADDRESS, GMAIL_APP_PASSWORD, NEWS_MAIL_TO)가 설정되지 않았습니다.")
        sys.exit(1)

    mail_to_list = [addr.strip() for addr in mail_to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(mail_to_list)
    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, mail_to_list, msg.as_string())

    print("[완료] 이메일 발송 성공")


# =========================
# 메인 실행
# =========================
def main():
    now = datetime.now(KST)
    # 전날 00:00(KST)부터 발송 시점까지 (밤사이 미국 시장 뉴스 포함)
    since = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    korea_items = collect_news(KOREAN_FEEDS, since, needs_translation=False)
    world_items = (
        collect_news(KOREAN_WORLD_FEEDS, since, needs_translation=False)
        + collect_news(GLOBAL_FEEDS, since, needs_translation=True)
    )
    if not korea_items and not world_items:
        print("[에러] 수집된 기사가 없습니다.")
        sys.exit(1)

    korea = build_entries(select_top(korea_items))
    world = build_entries(select_top(world_items))

    market_rows = fetch_market_snapshot()
    today = now.strftime("%Y-%m-%d")
    html_body, text_body = build_email(korea, world, market_rows, today)

    if os.environ.get("DRY_RUN"):
        print(text_body)
        return

    send_email(html_body, text_body, f"[모닝 브리핑] {today} 국내·해외 주요 뉴스 & 관련 주식")


if __name__ == "__main__":
    main()
