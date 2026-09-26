import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import yfinance as yf

# =========================
# 설정
# =========================
TICKERS = {
    "005935.KS": "삼성전자우",
    "005387.KS": "현대차2우B",
    "009150.KS": "삼성전기",
    "498400.KS": "KODEX 200타겟위클리커버드콜",
    "007660.KS": "이수페타시스",
    "441800.KS": "TIME Korea플러스배탕액티브",
    "028050.KS": "삼성E&A",
    "000660.KS": "SK하이닉스",
    "TSLA": "테슬라",
    "QQQM": "Invesco NASDAQ 100 ETF",
    "SPY": "SPDR S&P 500 ETF Trust",
    "PLTR": "팔란티어",
    "NIKE": "나이키B",
    "GOOGL": "알파벳 A",
    "IONQ": "아이온큐",
    "AMD": "AMD",
    "VOO": "VANGUARD S&P 500",
    "SCHD": "SCHWAB US DIVIDEND EQUITY",
}

LOOKBACK_DAYS = "400d" # 200일 지표 계산 위해 여유 있게 수집


# =========================
# 지표 계산 함수
# =========================
def calc_sma(series, window):
    return series.rolling(window=window).mean()


def calc_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def calc_macd(close):
    ema12 = calc_ema(close, 12)
    ema26 = calc_ema(close, 26)
    macd_line = ema12 - ema26
    signal_line = calc_ema(macd_line, 9)
    return macd_line, signal_line


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_bollinger(close, window=20, num_std=2):
    mid = calc_sma(close, window)
    std = close.rolling(window=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, lower


# =========================
# 전략 함수
# =========================
def strategy_1_golden_dead_cross(df):
    """골든/데드크로스 + 거래량"""
    sma5 = calc_sma(df["Close"], 5)
    sma20 = calc_sma(df["Close"], 20)
    vol_sma20 = calc_sma(df["Volume"], 20)

    prev_diff = sma5.iloc[-2] - sma20.iloc[-2]
    curr_diff = sma5.iloc[-1] - sma20.iloc[-1]

    golden_cross = (prev_diff <= 0) and (curr_diff > 0)
    dead_cross = (prev_diff >= 0) and (curr_diff < 0)

    vol_today = df["Volume"].iloc[-1]
    vol_avg20 = vol_sma20.iloc[-1]

    if golden_cross and vol_today > vol_avg20:
        return 1
    elif dead_cross:
        return -1
    return 0


def strategy_2_macd_alignment(df):
    """MACD + 정배열 + 거래량"""
    sma5 = calc_sma(df["Close"], 5)
    sma20 = calc_sma(df["Close"], 20)
    sma60 = calc_sma(df["Close"], 60)
    macd_line, signal_line = calc_macd(df["Close"])
    vol_sma20 = calc_sma(df["Volume"], 20)

    prev_macd_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_macd_diff = macd_line.iloc[-1] - signal_line.iloc[-1]

    macd_golden = (prev_macd_diff <= 0) and (curr_macd_diff > 0)
    macd_dead = (prev_macd_diff >= 0) and (curr_macd_diff < 0)

    aligned = (sma5.iloc[-1] > sma20.iloc[-1]) and (sma20.iloc[-1] > sma60.iloc[-1])

    vol_today = df["Volume"].iloc[-1]
    vol_avg20 = vol_sma20.iloc[-1]

    if aligned and macd_golden and vol_today >= vol_avg20 * 1.5:
        return 1
    elif macd_dead or not aligned:
        prev_aligned = (sma5.iloc[-2] > sma20.iloc[-2]) and (sma20.iloc[-2] > sma60.iloc[-2])
        if macd_dead or (prev_aligned and not aligned):
            return -1
    return 0


def strategy_3_rsi_bollinger(df):
    """RSI + 볼린저밴드 반전"""
    rsi = calc_rsi(df["Close"], 14)
    upper, lower = calc_bollinger(df["Close"], 20, 2)

    close_today = df["Close"].iloc[-1]
    rsi_today = rsi.iloc[-1]
    upper_today = upper.iloc[-1]
    lower_today = lower.iloc[-1]

    if rsi_today <= 30 and close_today <= lower_today:
        return 1
    elif rsi_today >= 70 and close_today >= upper_today:
        return -1
    return 0


STRATEGIES = {
    "골든/데드크로스+거래량": strategy_1_golden_dead_cross,
    "MACD+정배열+거래량": strategy_2_macd_alignment,
    "RSI+볼린저밴드": strategy_3_rsi_bollinger,
}


# =========================
# 데이터 수집 및 신호 계산
# =========================
def fetch_data(ticker):
    df = yf.download(ticker, period=LOOKBACK_DAYS, interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return df


def scan_all():
    results = []
    for ticker, name in TICKERS.items():
        try:
            df = fetch_data(ticker)
            if len(df) < 200:
                print(f"[경고] {name}({ticker}) 데이터 부족: {len(df)}행")
                continue

            close_today = df["Close"].iloc[-1]
            last_date = df.index[-1].strftime("%Y-%m-%d")

            for strategy_name, strategy_func in STRATEGIES.items():
                signal = strategy_func(df)
                if signal != 0:
                    results.append({
                        "name": name,
                        "ticker": ticker,
                        "strategy": strategy_name,
                        "signal": signal,
                        "close": close_today,
                        "date": last_date,
                    })
        except Exception as e:
            print(f"[에러] {name}({ticker}) 처리 실패: {e}")
    return results


def build_html_table(results):
    rows_html = ""
    for r in results:
        if r["signal"] == 1:
            signal_text = "매수"
            color = "green"
        else:
            signal_text = "매도"
            color = "red"

        close_str = f"{r['close']:,.2f}"

        rows_html += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd;">{r['name']} ({r['ticker']})</td>
            <td style="padding:8px;border:1px solid #ddd;">{r['strategy']}</td>
            <td style="padding:8px;border:1px solid #ddd;color:{color};font-weight:bold;">{signal_text}</td>
            <td style="padding:8px;border:1px solid #ddd;">{close_str}</td>
            <td style="padding:8px;border:1px solid #ddd;">{r['date']}</td>
        </tr>
        """

    html = f"""
    <html>
    <body style="font-family:Arial, sans-serif;">
        <h2>퀀트 트레이딩 신호 알림</h2>
        <table style="border-collapse:collapse;width:100%;">
            <thead>
                <tr style="background-color:#f2f2f2;">
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">자산명</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">적용 전략</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">신호</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">기준 종가</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">기준일</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """
    return html


def send_email(html_content, subject):
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    mail_to_raw = os.environ.get("MAIL_TO")

    if not gmail_address or not gmail_app_password or not mail_to_raw:
        print("[에러] 이메일 관련 환경 변수가 설정되지 않았습니다.")
        sys.exit(1)

    mail_to_list = [addr.strip() for addr in mail_to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(mail_to_list)

    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, mail_to_list, msg.as_string())

    print("[완료] 이메일 발송 성공")


# =========================
# 메인 실행
# =========================
def main():
    results = scan_all()

    if not results:
        print("No signals today")
        return

    html_content = build_html_table(results)
    subject = f"[주식 분석] {results[0]['date']} 매수/매도 신호 발생 ({len(results)}건)"
    send_email(html_content, subject)


if __name__ == "__main__":
    main()
