# 회의실 예약 시스템 개발 계획

## 1. 목표
사내 회의실을 시간대별로 조회·예약·취소할 수 있는 웹 앱. 충돌(중복) 예약을 방지하고, 한눈에 일정 파악이 가능해야 한다.

## 2. 범위 (MVP)
| 구분 | 기능 |
|---|---|
| 회의실 | 목록, 수용 인원/장비(프로젝터, 화상회의 등) 표시, 층/인원 필터 |
| 캘린더 | 일간 타임라인(회의실 × 시간) 뷰, 주간 뷰, 날짜 이동 |
| 예약 | 생성(제목, 예약자, 회의실, 날짜, 시작/종료, 참석자 수, 메모), 수정, 취소 |
| 검증 | 시간 겹침 차단, 과거 시간 차단, 종료>시작, 운영시간(09:00–18:00, 30분 단위) |
| 내 예약 | 내 예약 목록, 취소 |
| 반복 예약 | (2차) 매일/매주 반복 |

### 제외 (후속 단계)
실제 인증/SSO, 이메일·슬랙 알림, 관리자 권한, 캘린더(Google/Outlook) 연동.

## 3. 기술 스택
- **React 18 + TypeScript + Vite**
- **Tailwind CSS v3**
- 라우팅: React Router
- 상태: React Context + `useReducer` (규모 작아 외부 라이브러리 불필요)
- 폼/검증: React Hook Form + Zod
- 날짜: date-fns
- 저장소: **MVP는 localStorage 기반 Repository 계층** → 추후 REST API로 교체 가능하도록 인터페이스 분리
- 테스트: Vitest + React Testing Library
- 품질: ESLint, Prettier, `tsc --noEmit`

## 4. 폴더 구조
```
room-booking/
├─ src/
│  ├─ components/      # 공통 UI (Button, Modal, Badge, Select ...)
│  ├─ features/
│  │  ├─ rooms/        # RoomList, RoomCard, RoomFilter
│  │  ├─ bookings/     # BookingForm, BookingModal, MyBookings
│  │  └─ calendar/     # DayTimeline, WeekView, DateNavigator
│  ├─ lib/             # 시간 유틸, 충돌 검사 로직
│  ├─ repositories/    # BookingRepository (localStorage 구현)
│  ├─ context/         # BookingContext, UserContext
│  ├─ types/           # Room, Booking 타입
│  ├─ data/            # 초기 회의실 시드 데이터
│  ├─ pages/           # CalendarPage, MyBookingsPage
│  └─ App.tsx, main.tsx
└─ tailwind.config.js, vite.config.ts, tsconfig.json
```

## 5. 데이터 모델
```ts
interface Room { id: string; name: string; floor: number; capacity: number; amenities: string[]; }
interface Booking {
  id: string; roomId: string; title: string; organizer: string;
  date: string;        // YYYY-MM-DD
  start: string;       // HH:mm
  end: string;         // HH:mm
  attendees: number; note?: string; createdAt: string;
}
```
- 충돌 조건: 같은 `roomId`·`date`에서 `newStart < existing.end && newEnd > existing.start`
- 수용 인원 초과 시 경고(차단).

## 6. 화면 구성
1. **캘린더 페이지(메인)**: 상단 날짜 이동/필터, 본문 회의실별 타임라인. 빈 슬롯 클릭 → 예약 모달, 기존 예약 클릭 → 상세/수정/취소.
2. **내 예약 페이지**: 예정/지난 예약 탭, 취소 버튼.
3. 반응형: 모바일에서는 회의실 선택 후 단일 컬럼 타임라인.
4. 접근성: 키보드 포커스, 모달 `aria` 속성, 색상 대비.

## 7. 개발 단계
| 단계 | 내용 | 산출물 |
|---|---|---|
| 1 | Vite+React+TS+Tailwind 세팅, ESLint/Prettier | 실행 가능한 골격 |
| 2 | 타입, 시드 데이터, 시간·충돌 유틸 + 단위 테스트 | `lib/`, `types/` |
| 3 | Repository + Context | 예약 CRUD 로직 |
| 4 | 공통 UI + 회의실 목록/필터 | 회의실 화면 |
| 5 | 일간 타임라인 + 예약 모달(생성/수정/취소) | 핵심 기능 |
| 6 | 내 예약 페이지, 주간 뷰 | 보조 기능 |
| 7 | 반응형·접근성·빈/에러 상태 다듬기 | UI 완성도 |
| 8 | 컴포넌트 테스트, 빌드 확인, README | 마감 |

## 8. 테스트·검증 기준
- 충돌 검사: 경계(끝=시작 허용), 포함, 부분 겹침 케이스 단위 테스트
- 예약 생성/취소 흐름 컴포넌트 테스트
- `tsc`, `eslint`, `vitest`, `vite build` 모두 통과
- 브라우저(Playwright)로 실제 예약 흐름 수동 확인

## 9. 결정 필요 사항 (검토 요청)
1. **백엔드**: MVP는 localStorage(서버 없음)로 진행해도 되는가? 아니면 Node/Supabase 등 백엔드 포함?
2. **사용자 구분**: 로그인 없이 "이름 입력/선택"으로 예약자 식별해도 되는가?
3. **회의실 목록**: 임의 시드(예: 6개 방) 사용 vs 실제 목록 제공?
4. **운영시간/슬롯 단위**: 09:00–18:00, 30분 단위 괜찮은가?
5. **반복 예약**을 MVP에 포함할지?
6. **언어**: UI 한국어 고정으로 진행?
7. **위치**: 기존 저장소의 `room-booking/` 하위 폴더 vs 별도 저장소?

## 10. 위험 요소
- localStorage는 사용자 간 공유 불가 → 실서비스 시 백엔드 필수 (Repository 추상화로 완화)
- 타임존/날짜 처리 오류 → 날짜는 문자열(YYYY-MM-DD, HH:mm)로 다뤄 로컬 기준 단순화
