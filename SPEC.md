# 리포트 저장소 명세

## Context

`etri-capstone`은 OpenAlex 기반 연구 지원 MCP Server 실습 저장소다. 기존 `server.py`에는 참고 구현인
`search_papers_by_title` Tool 하나만 존재했고 영속성 계층은 없었다. 이 명세는 AI가 생성한 논문 기반
문서 산출물을 SQLite에 보존하고 다시 활용하는 기능을 정의한다.

## Goal

연구자가 Host LLM과 대화하며 논문을 검색·비교하고 작성한 리포트를 저장한 뒤, 이후 세션에서 목록
조회·불러오기·수정·삭제할 수 있게 한다. 리포트는 근거와 출처가 되는 참고 논문과 함께 보존된다.

## Non-goals

- 리포트 본문 이력 보존 및 복원. `version`은 개정 횟수 카운터일 뿐 과거 본문을 저장하지 않는다.
- FTS5 전문 검색 인덱스.
- BibTeX·APA 등 인용 형식 변환 및 내보내기.
- 스키마 마이그레이션 체계. 스키마 변경 시 DB 파일을 삭제하고 재생성한다.
- 서버가 분석·비교·본문 작성을 수행하는 것. 전부 Host LLM 책임이다.
- 초록 수집, 인증, 다중 사용자, 웹 UI.

## User flow

```text
연구 질문
→ search_papers_by_title 로 논문 검색
→ (Host LLM이 검색 결과를 비교·분석하고 리포트 본문 작성)
→ save_report 로 본문과 참고 논문을 한 번에 저장
→ list_reports 로 목록 조회
→ get_report 로 불러오기
→ update_report 로 수정 또는 보관(status='archived')
→ delete_report / delete_paper 로 삭제
```

## Functional requirements

1. 서버는 데이터 계층에 한정한다. 분석·비교·문장 작성은 수행하지 않는다.
2. 검색은 비교 가능한 축을 제공한다. 기존 6개 필드에 `cited_by_count`와 `primary_topic`에서 얻는
   `topic`·`field`를 추가한다.
3. 리포트 저장은 단일 호출로 완결된다. `save_report`가 참고 논문 배열을 받아 `papers` upsert와 인용
   링크 생성까지 한 트랜잭션에서 처리한다.
4. 이미 저장된 논문을 다시 인용하면 인용 수·토픽·`saved_at`을 최신값으로 갱신한다.
5. 수정은 `update_report`로 전달된 필드만 변경한다. 본문이 실제로 바뀐 경우에만 `version`이 증가한다.
6. `delete_report`는 실제 행 삭제다. 보관은 `update_report(status='archived')`로 수행한다.
7. 저장된 논문은 `list_papers`로 조회하고 `delete_paper`로 삭제한다. 리포트가 인용 중인 논문의 삭제는
   거부한다.

## Tool contracts

전 Tool은 `@server.tool(structured_output=True)`로 등록한다. 실패 시 예외를 던지지 않고 `error` 키를
포함한 dict를 반환한다. 기존 `search_papers_by_title`의 패턴을 따른다.

| Tool | 입력 | 반환 |
| --- | --- | --- |
| `search_papers_by_title` | `title`, `limit=5` (최대 10) | `query`, `count`, `papers[]` |
| `save_report` | `title`, `content`, `research_question=None`, `report_format='markdown'`, `status='draft'`, `tags=None`, `papers=None` | `report_id`, `version`, `created_at`, `saved_paper_count` |
| `list_reports` | `status=None`, `tag=None`, `limit=20`, `offset=0` | `count`, `reports[]` |
| `get_report` | `report_id` | 리포트 전체 컬럼과 `papers[]` |
| `update_report` | `report_id`와 나머지 선택 필드 | `report_id`, `version`, `updated_at`, `changed_fields[]` |
| `delete_report` | `report_id` | `deleted_title`, `unlinked_paper_count` |
| `list_papers` | `limit=50`, `offset=0` | `count`, `papers[]` |
| `delete_paper` | `paper_id` | `deleted_title` |

`list_reports`의 각 항목은 본문 전체 대신 200자 `preview`와 `paper_count`를 포함한다.
`get_report`의 `papers[]`는 `evidence`를 포함하며 `position` 순으로 정렬한다.
`list_papers`의 각 항목은 인용 중인 리포트 수 `cited_in`을 포함한다.

`papers[]` 항목은 검색 결과를 그대로 넘길 수 있도록 검색 출력과 동일한 키를 사용한다.

```text
openalex_id (필수) · title (필수) · publication_year · authors[] · doi
landing_page_url · cited_by_count · topic · field · evidence
```

## Persistence requirements

DB 파일은 `Path(__file__).parent / "research.db"`로 고정한다. Host가 어떤 작업 디렉터리로 서버를
띄우든 같은 파일을 열기 위함이다. 모든 커넥션에서 `PRAGMA foreign_keys = ON`을 실행한다.

```sql
CREATE TABLE IF NOT EXISTS papers (
    id               INTEGER PRIMARY KEY,
    openalex_id      TEXT    NOT NULL UNIQUE,
    title            TEXT    NOT NULL,
    publication_year INTEGER,
    authors          TEXT    NOT NULL DEFAULT '[]'
                     CHECK (json_valid(authors) AND json_type(authors) = 'array'),
    doi              TEXT,
    landing_page_url TEXT,
    cited_by_count   INTEGER,
    topic            TEXT,
    field            TEXT,
    saved_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id                INTEGER PRIMARY KEY,
    title             TEXT    NOT NULL,
    research_question TEXT,
    content           TEXT    NOT NULL,
    format            TEXT    NOT NULL DEFAULT 'markdown'
                      CHECK (format IN ('markdown', 'html', 'text')),
    status            TEXT    NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'final', 'archived')),
    tags              TEXT    NOT NULL DEFAULT '[]'
                      CHECK (json_valid(tags) AND json_type(tags) = 'array'),
    version           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_papers (
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    paper_id  INTEGER NOT NULL REFERENCES papers(id)  ON DELETE RESTRICT,
    evidence  TEXT,
    position  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (report_id, paper_id)
);

CREATE INDEX IF NOT EXISTS idx_report_papers_paper ON report_papers(paper_id);
CREATE INDEX IF NOT EXISTS idx_reports_status      ON reports(status);

CREATE TRIGGER IF NOT EXISTS reports_touch
AFTER UPDATE ON reports
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE reports
       SET updated_at = datetime('now'),
           version    = CASE WHEN NEW.content IS NOT OLD.content
                             THEN OLD.version + 1 ELSE OLD.version END
     WHERE id = NEW.id;
END;
```

논문 upsert는 `ON CONFLICT(openalex_id) DO UPDATE SET ... , saved_at = datetime('now')`로 수행한다.
시각은 전부 `datetime('now')`가 만드는 UTC ISO-8601 문자열로 통일한다. 최초 생성 시
`PRAGMA user_version = 1`을 기록한다.

## Error behavior

| 상황 | 응답 |
| --- | --- |
| `status`·`format` 허용값 위반 | 허용값을 나열한 메시지. LLM이 스스로 교정해 재시도할 수 있어야 한다 |
| 인용 중인 논문 삭제 | 거부하고 인용 중인 리포트 제목 목록을 함께 반환 |
| 존재하지 않는 `report_id`·`paper_id` | 대상이 없음을 명시 |
| `tags`가 문자열 배열이 아님 | 배열 형식을 요구하는 메시지 |
| `papers` 항목에 `openalex_id`나 `title`이 없음 | 누락된 키를 지목 |
| OpenAlex HTTP·네트워크 오류 | 기존 구현대로 `error` 키와 빈 `papers[]` |
| 저장 중 실패 | 트랜잭션 롤백. 부분 저장을 남기지 않는다 |

## Completion criteria

Host LLM으로 다음을 수동 확인한다.

1. 정상 흐름 1회 왕복. 연구 질문에서 검색, 리포트 작성, `save_report`, `list_reports`, `get_report`,
   `update_report`, `delete_report`까지 끊김 없이 동작한다.
2. 재인용 갱신. 같은 논문을 두 리포트에서 인용해도 `papers`에 행이 하나이며 인용 수가 최신값이다.
3. 버전 동작. 본문 수정 시 `version`이 증가하고 `status`만 변경하면 증가하지 않는다.
4. 제약 위반 거부. 잘못된 `status` 값 저장과 인용 중인 논문 삭제가 각각 이해 가능한 메시지로 거부된다.
5. 서버 재시작 후에도 저장된 리포트가 그대로 조회된다.

## Constraints

- Python 3.10 이상. 표준 라이브러리 `sqlite3`만 사용하며 `requirements.txt`는 변경하지 않는다.
- `mcp==2.0.0`의 `MCPServer`와 `stdio` 전송 구조를 유지한다.
- `.claude/CLAUDE.md`를 준수한다. 자동화 테스트 생성 금지, 최소 변경, 불필요한 추상화 금지.
- DB 파일은 `.gitignore`의 `*.db` 규칙으로 이미 커밋에서 제외된다.

## Assumptions

1. `list_reports`는 `status` 미지정 시 `archived`를 제외한다.
2. `update_report`에서 인자 미전달은 변경 없음을 뜻한다. 필드를 `NULL`로 지우는 경로는 제공하지 않는다.
3. `update_report`에 `papers`를 주면 기존 인용 링크를 전부 교체한다.
4. 정렬은 리포트 `updated_at DESC`, 논문 `saved_at DESC`.
5. `primary_topic`은 `topic`(토픽명)과 `field`(상위 분야명) 두 컬럼으로 나눠 저장한다.
6. 산출물 종류는 리포트 한 가지다. `kind` 구분은 두지 않는다.
7. 태그 필터는 `json_each()` 기반 완전 일치다. 부분 일치와 대소문자 무시는 하지 않는다.
8. Tool 인자 이름은 `format` 대신 `report_format`을 쓴다. 내장 함수명과 겹치지 않게 하기 위함이며
   DB 컬럼명은 `format`을 유지한다.
9. 한 번의 `save_report` 호출에 같은 `openalex_id`가 중복으로 오면 첫 항목만 남기고 무시한다.

## Open risks

- OpenAlex 레코드에 `primary_topic`이 없는 경우가 있어 `topic`·`field`는 NULL을 허용한다.
- `version`은 본문 문자열의 완전 일치로 판정하므로 공백 하나만 달라져도 증가한다.
- `papers` 인라인 배열이 커지면 `save_report` 요청 토큰이 늘어난다. 실사용에서 과도하면 참고 논문 수에
  상한을 두는 조정이 필요할 수 있다.
- 중첩 객체 인자는 Tool 스키마에 `additionalProperties: true`로만 노출된다. `papers` 항목의 키는
  docstring으로만 전달되므로 설명이 부정확하면 LLM이 잘못된 형태를 보낼 수 있다.
- SQLite 동시 접근은 `stdio` 단일 프로세스 특성상 위험이 낮다. 커넥션은 호출마다 열고 닫는다.
