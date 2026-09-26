"""매일 아침 재테크 뉴스 브리핑 메일 발송.

1. 국내외 신뢰할 수 있는 언론사 RSS에서 전날(KST) 이후 기사를 수집
2. Claude가 국내 5건 / 해외 5건을 골라 2~3줄 요약 + 관련 주식 추천
3. 주요 지수·환율·유가 스냅샷과 함께 HTML 이메일로 발송

기사 URL은 모델이 만들지 않고, 수집한 RSS 항목의 URL을 그대로 사용한다.
"""
import html
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

import anthropic
import feedparser
import yfinance as yf
from pydantic import BaseModel

KST = timezone(timedelta(hours=9))
MODEL = "claude-opus-5"

# =========================
# 신뢰할 수 있는 언론사 RSS
# =========================
KOREAN_FEEDS = [
    ("연합뉴스", "https://www.yna.co.kr/rss/economy.xml"),
    ("연합뉴스", "https://www.yna.co.kr/rss/market.xml"),
    ("연합뉴스", "https://www.yna.co.kr/rss/international.xml"),
    ("한국경제", "https://www.hankyung.com/feed/economy"),
    ("한국경제", "https://www.hankyung.com/feed/finance"),
    ("한국경제", "https://www.hankyung.com/feed/international"),
    ("매일경제", "https://www.mk.co.kr/rss/30100041/"),  # 경제
    ("매일경제", "https://www.mk.co.kr/rss/50200011/"),  # 증권
    ("매일경제", "https://www.mk.co.kr/rss/30300018/"),  # 국제
]

GLOBAL_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),  # Top News
    ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),  # Economy
    ("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),  # Finance
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Wall Street Journal", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
    ("Bloomberg", "https://feeds.bloomberg.com/economics/news.rss"),
    ("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
]

MAX_ITEMS_PER_FEED = 30
SUMMARY_CHARS = 300

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


def collect_news(feeds, since, prefix):
    items = []
    seen = set()
    for source, url in feeds:
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (news-digest)")
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
                "id": f"{prefix}{len(items) + 1}",
                "source": source,
                "title": title,
                "summary": clean_text(entry.get("summary"))[:SUMMARY_CHARS],
                "url": link,
                "published": published.astimezone(KST).strftime("%Y-%m-%d %H:%M") if published else "",
            })
    print(f"[정보] {prefix} 후보 기사 {len(items)}건 수집")
    return items


# =========================
# Claude 요약 / 종목 추천
# =========================
class Stock(BaseModel):
    name: str
    ticker: str
    reason: str


class PickedNews(BaseModel):
    article_id: str
    headline: str
    summary: str
    stocks: List[Stock]


class Digest(BaseModel):
    korea: List[PickedNews]
    world: List[PickedNews]


SYSTEM_PROMPT = """당신은 개인 투자자를 위한 재테크 뉴스 에디터입니다.
제공된 기사 목록(국내 후보, 해외 후보)에서만 기사를 고릅니다. 목록에 없는 기사나 URL을 만들어내지 마세요.

선정 기준:
- 재테크에 실질적으로 도움이 되는 뉴스 우선: 한국 경제, 미국 경제, 한국·미국 증시와 주요 종목, 원/달러 환율, 국제 유가, 금리·통화정책, 원자재.
- 같은 사건을 다룬 기사는 하나만 고릅니다. 연예·사건사고·단순 인사 기사는 제외합니다.
- 국내 5건은 국내 후보(K로 시작하는 id)에서, 해외 5건은 해외 후보(G로 시작하는 id)에서 중요도 순으로 고릅니다.

작성 규칙 (모두 한국어):
- headline: 핵심을 담은 한 줄 헤드라인.
- summary: 2~3문장으로 핵심 사실과 시장에 미칠 영향을 정리. 기사에 없는 수치를 지어내지 마세요.
- stocks: 해당 뉴스와 직접 관련된 한국 또는 미국 상장 주식/ETF 1~3개. ticker는 한국 종목은 6자리 코드+'.KS' 또는 '.KQ', 미국 종목은 티커 심볼. reason은 수혜/피해 등 관련 이유를 한 문장으로."""


def build_prompt(korea_items, world_items):
    def fmt(items):
        return "\n".join(
            f"[{it['id']}] ({it['source']}, {it['published']}) {it['title']} :: {it['summary']}"
            for it in items
        )
    return f"## 국내 후보\n{fmt(korea_items)}\n\n## 해외 후보\n{fmt(world_items)}"


def summarize(korea_items, world_items):
    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(korea_items, world_items)}],
        output_format=Digest,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"모델이 요청을 거절했습니다: {response.stop_details}")
    return response.parsed_output


def attach_sources(picks, items, limit=5):
    """모델이 고른 id를 실제 기사(출처·URL)와 연결. 목록에 없는 id는 버린다."""
    by_id = {it["id"]: it for it in items}
    result = []
    for pick in picks:
        article = by_id.get(pick.article_id)
        if article is None:
            print(f"[경고] 알 수 없는 기사 id: {pick.article_id}")
            continue
        result.append({"pick": pick, "article": article})
        if len(result) == limit:
            break
    return result


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
        pick, article = e["pick"], e["article"]
        stocks = "<br>".join(
            f"· <b>{html.escape(s.name)}</b> ({html.escape(s.ticker)}) – {html.escape(s.reason)}"
            for s in pick.stocks
        )
        url = html.escape(article["url"])
        blocks += f"""
        <div style="margin:0 0 22px 0;">
            <div style="font-size:16px;font-weight:bold;">{i}. {html.escape(pick.headline)}</div>
            <div style="margin:6px 0 0 0;line-height:1.6;">{html.escape(pick.summary)}</div>
            <div style="margin:8px 0 0 0;padding:8px 10px;background:#f6f8fa;border-radius:6px;font-size:14px;">
                <b>📈 관련 주식</b><br>{stocks}
            </div>
            <div style="margin:6px 0 0 0;font-size:13px;color:#666;">
                출처: {html.escape(article['source'])} ({article['published']})<br>
                <a href="{url}">{url}</a>
            </div>
        </div>"""
    return f"<h3 style='margin-top:24px;'>{title}</h3>{blocks}"


def render_news_text(title, entries):
    lines = [title, ""]
    for i, e in enumerate(entries, 1):
        pick, article = e["pick"], e["article"]
        lines.append(f"{i}. {pick.headline}")
        lines.append(pick.summary)
        lines.append("관련 주식:")
        lines += [f"  - {s.name} ({s.ticker}): {s.reason}" for s in pick.stocks]
        lines.append(f"출처: {article['source']} ({article['published']})")
        lines.append(article["url"])
        lines.append("")
    return "\n".join(lines)


DISCLAIMER = "※ 관련 주식은 뉴스와의 연관성을 AI가 정리한 참고 정보이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다."


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

    korea_items = collect_news(KOREAN_FEEDS, since, "K")
    world_items = collect_news(GLOBAL_FEEDS, since, "G")
    if not korea_items and not world_items:
        print("[에러] 수집된 기사가 없습니다.")
        sys.exit(1)

    digest = summarize(korea_items, world_items)
    korea = attach_sources(digest.korea, korea_items)
    world = attach_sources(digest.world, world_items)

    market_rows = fetch_market_snapshot()
    today = now.strftime("%Y-%m-%d")
    html_body, text_body = build_email(korea, world, market_rows, today)

    if os.environ.get("DRY_RUN"):
        print(text_body)
        return

    send_email(html_body, text_body, f"[모닝 브리핑] {today} 국내·해외 주요 뉴스 & 관련 주식")


if __name__ == "__main__":
    main()
