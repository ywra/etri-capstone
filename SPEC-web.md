# 리포트 열람 웹 명세

## Context

MCP Server는 리포트를 `research.db`에 저장하지만 열람은 Host LLM을 통해서만 가능하다. 이 명세는
저장된 리포트를 브라우저에서 읽는 React 앱과 그에 필요한 읽기 전용 HTTP API를 정의한다.

핵심 제약은 브라우저가 `stdio` 기반 MCP Server와 직접 통신할 수 없다는 점이다. MCP Host는
`python server.py`를 자식 프로세스로 띄우고 표준 입출력으로 대화하는데 브라우저는 프로세스를 띄울 수
없다. 따라서 웹은 MCP를 거치지 않고 별도의 HTTP 경로로 같은 데이터베이스를 읽는다.

## Goal

`localhost:3000`에서 저장된 리포트 목록을 보고, 항목을 눌러 상세 페이지로 이동해 본문과 근거 논문을
읽을 수 있게 한다.

## Non-goals

- 인증과 접근 제어. 대신 API를 `127.0.0.1`에만 바인딩한다.
- 프로덕션 빌드 배포와 외부 공개.
- 검색, 필터, 페이지 나누기.
- 참고 논문만 따로 보는 화면. 논문은 리포트 상세 안에서만 표시한다.
- 웹에서의 리포트 수정과 삭제. 쓰기는 전부 MCP Tool을 통한다.
- `research.db`의 `journal_mode` 변경.

## Architecture

```text
브라우저 (Vite dev server :3000)
      │  /api/*  ->  Vite proxy
      ▼
web_api.py (:8000, 127.0.0.1)  ─┐
                                ├─→ database.py ─→ research.db
Claude Code ─stdio→ server.py ──┘
```

`database.py`를 두 진입점이 공유한다. 스키마와 조회 규칙이 한 곳에만 존재해 MCP 쪽과 웹 쪽이
갈라지지 않는다.

## User flow

```text
터미널 1: python web_api.py
터미널 2: cd web && npm run dev
→ localhost:3000 목록 화면
→ 리포트 클릭 → /reports/:id 상세 페이지
→ 본문과 참고 논문 열람 → 뒤로가기로 목록 복귀
```

## Functional requirements

1. 목록은 저장된 모든 리포트를 `archived` 포함해 최신 수정순으로 보여준다. 상태는 배지로 구분한다.
2. 목록 항목에는 제목, 상태, 판(`version`), 참고 논문 수, 태그, 수정 시각을 표시한다.
3. 항목을 누르면 `/reports/:id`로 이동한다. 주소가 실제로 바뀌어 새로고침과 뒤로가기가 동작한다.
4. 상세 페이지는 연구 질문, 메타데이터, 마크다운으로 렌더링한 본문, 참고 논문 목록을 표시한다.
5. 참고 논문에는 제목, 저자, 발행 연도, 인용 수, 연구 분야, 원문 링크, `evidence`를 함께 표시한다.
6. API가 응답하지 않으면 빈 화면 대신 원인과 대처를 안내한다.

## API contracts

`web_api.py`는 표준 라이브러리 `http.server`로 구현한다. `requirements.txt`는 변경하지 않는다.

| 메서드와 경로 | 반환 |
| --- | --- |
| `GET /api/reports` | `{ count, total, reports: [...] }`. 본문 대신 `preview`와 `paper_count`를 포함한다 |
| `GET /api/reports/{id}` | 리포트 전체 컬럼과 `papers[]`. `evidence`를 포함하며 `position` 순이다 |

응답은 `application/json; charset=utf-8`이다. 오류는 상태 코드와 함께 `{ "error": "메시지" }`를
반환한다.

| 상황 | 코드 |
| --- | --- |
| 정상 | 200 |
| 없는 `report_id` | 404 |
| 그 외 경로 | 404 |
| 서버 내부 오류 | 500 |

## database.py 변경

`list_reports()`는 `status` 미지정 시 `archived`를 제외한다. 웹이 전체를 조회할 수 있도록 매개변수
하나를 추가한다.

```python
def list_reports(status=None, tag=None, limit=20, offset=0, include_archived=False)
```

기본값이 `False`이므로 MCP Tool의 기존 동작은 바뀌지 않는다. 웹 API만 `True`로 호출한다. 조회
조건은 다음과 같이 확장한다.

```sql
WHERE ((:status IS NULL AND (:include_archived OR r.status <> 'archived'))
       OR r.status = :status)
```

## Frontend

```text
web/
  package.json
  vite.config.js
  index.html
  src/
    main.jsx          라우터 구성
    api.js            fetch 래퍼와 오류 처리
    pages/ReportList.jsx
    pages/ReportDetail.jsx
    styles.css
```

| 항목 | 선택 |
| --- | --- |
| 빌드 도구 | Vite. `create-react-app`은 폐기되어 사용하지 않는다 |
| 포트 | `server.port: 3000`, `strictPort: true` |
| API 연결 | Vite proxy로 `/api`를 `http://127.0.0.1:8000`에 넘긴다. 동일 출처가 되어 CORS 설정이 필요 없다 |
| 라우팅 | `react-router-dom`. `/` 목록, `/reports/:id` 상세 |
| 마크다운 | `react-markdown`과 `remark-gfm`. 본문에 표가 있어 GFM이 필요하다 |
| 스타일 | 단일 CSS 파일. UI 프레임워크는 쓰지 않는다 |

## Error behavior

| 상황 | 화면 |
| --- | --- |
| API 서버 미기동 | 연결 실패를 알리고 `python web_api.py` 실행을 안내한다 |
| 없는 리포트 주소 | 대상이 없음을 알리고 목록으로 돌아가는 링크를 제공한다 |
| 저장된 리포트가 없음 | 빈 목록임을 알리고 MCP Tool로 저장하라고 안내한다 |
| 로딩 중 | 로딩 상태를 표시한다 |

API 서버가 꺼져 있으면 Vite proxy가 `502`와 함께 JSON이 아닌 본문을 반환한다. 응답 본문을 JSON으로
읽는 데 실패한 경우와 API가 돌려준 `error`를 구분해서, 전자에는 서버 실행 안내를 보여준다. 확인
과정에서 이 둘을 구분하지 않으면 "응답을 해석할 수 없습니다" 같은 무의미한 문구가 나오는 것을
확인했다.

## Completion criteria

1. `localhost:3000`에서 목록이 뜨고 저장된 리포트가 모두 보인다.
2. 항목을 누르면 상세 페이지로 이동해 본문과 참고 논문이 보인다.
3. 상세 주소를 새로고침해도 그 리포트가 뜨고, 뒤로가기로 목록에 돌아온다.
4. MCP Tool로 새 리포트를 저장한 뒤 브라우저를 새로고침하면 목록에 나타난다.
5. API 서버를 끈 상태에서 접속하면 빈 화면이 아니라 오류 안내가 보인다.

## Constraints

- Python 표준 라이브러리만 사용한다. `requirements.txt`는 변경하지 않는다.
- API는 `127.0.0.1`에만 바인딩한다.
- `.claude/CLAUDE.md`를 준수한다. 자동화 테스트 생성 금지, 최소 변경.
- `web/`을 저장소에 커밋하고 `.gitignore`에 `node_modules/`와 `dist/`를 추가한다.

## Assumptions

1. API 포트는 `8000`을 쓴다.
2. 목록 정렬은 `updated_at DESC`이며 `database.list_reports()`의 기존 정렬을 그대로 쓴다.
3. 목록은 `database.MAX_REPORT_PAGE_SIZE`(100)까지 한 번에 가져온다. 그보다 많으면 최근 수정순으로 잘리며, 응답의 `total`과 `count`가 달라지므로 화면이 잘렸다는 사실과 남은 건수를 함께 알린다.
4. `react-markdown`은 기본적으로 원시 HTML을 렌더링하지 않으므로 별도 살균 처리를 하지 않는다.
5. 상태 배지 표기는 `draft`, `final`, `archived` 세 가지다.
6. 두 서버는 터미널 두 개에서 각각 실행하며 절차는 README에 적는다.

## 사전 확인 결과

구현에 앞서 별도 디렉터리에서 툴체인을 실제로 확인했다. 확인용 코드는 저장소에 남기지 않았다.

설치한 도구와 확인한 버전이다.

```text
Node.js 24.19.0 (LTS)   npm 11.17.0
Vite 8.2.1              React 19.2
react-router-dom 7.18   react-markdown 10.1   remark-gfm 4.0
```

확인한 동작이다.

| 항목 | 결과 |
| --- | --- |
| Vite `strictPort` 3000 기동 | 정상 |
| `/api` proxy로 `:8000` 연결 | 정상. CORS 설정 없이 동작 |
| SPA 폴백 (`/reports/1` 직접 요청) | 정상 |
| `database.py` 재사용 API의 상태 코드 | 200과 404 모두 명세대로 |
| 목록 응답에 본문 미포함 | 확인 |
| 목록 렌더링 | 실제 DB의 리포트가 제목, 상태, 논문 수와 함께 표시됨 |
| 클릭 이동 | `/` → `/reports/1` 라우팅과 재렌더링 정상 |
| 직접 주소 진입 | `/reports/3` 새로 열어도 해당 리포트가 렌더링됨 |
| 뒤로가기 | 상세에서 목록으로 복귀 |
| GFM 표 렌더링 | 표와 본문 서식 모두 정상. 미처리 마크다운 0건 |
| 참고 논문과 `evidence` 표시 | 정상 |
| API 중지 시 동작 | proxy가 502를 반환하고 화면에 오류 문구가 표시됨 |

## Open risks

- `research.db`의 `journal_mode`가 `delete`라 MCP Server가 쓰는 동안 API 읽기가 잠깐 대기한다.
  `busy_timeout`이 5초라 대부분 넘어가지만 긴 쓰기가 겹치면 지연될 수 있다. `WAL` 전환은 부속 파일이
  생겨 데이터베이스 파일 하나만 복사하던 이점을 잃으므로 이번 범위에서 제외했다.
- `database.py`는 MCP Server와 공유하는 모듈이다. 기본값을 유지해 기존 동작은 바뀌지 않지만 변경 후
  MCP 쪽 회귀를 확인해야 한다.
- 포트 `3000`과 `8000`이 다른 프로세스에 점유되어 있을 수 있다. `strictPort`를 켜 두었으므로 3000이
  막혀 있으면 조용히 다른 포트로 넘어가지 않고 실패한다.
- 확인은 최소 구성으로 했다. 스타일과 컴포넌트 분리는 구현 단계에서 처음 작성한다.
