# trading-alert
## 재테크 모닝 브리핑 (`news_digest.py`)

매일 07:45 (KST)에 전날 국내 주요 뉴스 5건, 해외 주요 뉴스 5건을 이메일로 보냅니다.

- 출처: 연합뉴스·한국경제·매일경제 / CNBC·MarketWatch·WSJ·Bloomberg·BBC·NYT 공식 RSS
- 뉴스별: 번호 + 헤드라인 → 2~3줄 요약 → 관련 주식 → 출처 및 원문 URL
- 상단에 코스피·코스닥·S&P500·나스닥·다우·원/달러·달러인덱스·WTI·브렌트·미 10년물·금 시세
- **유료 API를 쓰지 않는 무료 방식입니다.** 뉴스 선정은 재테크 키워드(환율·금리·유가·반도체·증시 등) 점수로,
  요약은 RSS 설명문·기사 페이지의 요약 메타태그에서 2~3문장을 발췌해 만듭니다.
  해외 기사는 무료 번역기(Google 번역, `deep-translator`)로 한국어로 옮기고, 실패 시 원문을 그대로 씁니다.
  관련 주식은 기사에 언급된 기업명 또는 주제별로 미리 정한 종목 사전에서 연결합니다(AI가 그때그때 만들지 않음).
  URL은 항상 RSS 원문 링크 그대로입니다.

GitHub 저장소 Settings → Secrets and variables → Actions에 필요한 값:

| Secret | 설명 |
| --- | --- |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | 기존 발송용 Gmail 계정 |
| `NEWS_MAIL_TO` | 뉴스 브리핑 수신 주소 (필수, 매매 신호용 `MAIL_TO`와 별개. 여러 개는 쉼표로 구분) |

Actions 탭 → `daily-news-digest` → **Run workflow**로 바로 테스트할 수 있습니다.
로컬에서 `DRY_RUN=1 python news_digest.py`로 실행하면 메일 대신 본문을 출력합니다.
