# trading-alert
## 재테크 모닝 브리핑 (`news_digest.py`)

매일 07:45 (KST)에 전날 국내 주요 뉴스 5건, 해외 주요 뉴스 5건을 이메일로 보냅니다.

- 출처: 연합뉴스·한국경제·매일경제 / CNBC·MarketWatch·WSJ·Bloomberg·BBC·NYT 공식 RSS
- 뉴스별: 번호 + 헤드라인 → 2~3줄 요약 → 관련 주식 → 출처 및 원문 URL
- 상단에 코스피·코스닥·S&P500·나스닥·다우·원/달러·달러인덱스·WTI·브렌트·미 10년물·금 시세
- 요약·종목 추천은 Claude API가 수행하며, URL은 RSS 원문 링크를 그대로 사용합니다.

GitHub 저장소 Settings → Secrets and variables → Actions에 필요한 값:

| Secret | 설명 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API 키 (신규) |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | 기존 발송용 Gmail 계정 |
| `MAIL_TO` | 수신 주소 (기존 값 사용) |
| `NEWS_MAIL_TO` | (선택) 뉴스만 다른 주소로 받고 싶을 때 |

Actions 탭 → `daily-news-digest` → **Run workflow**로 바로 테스트할 수 있습니다.
로컬에서 `DRY_RUN=1 python news_digest.py`로 실행하면 메일 대신 본문을 출력합니다.
