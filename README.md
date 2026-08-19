# OpenAlex 기반 연구 지원 MCP Server

## 실습 목표

MCP Server를 직접 구현하여 LLM이 논문을 찾고 분석·비교하며, 작성한 리포트를 저장하고 다시 활용할 수 있게 한다.

## 요구사항

- OpenAlex를 활용한 논문 검색
- LLM이 식별하고 호출할 수 있는 MCP Tool 제공
- 연구 분야에 맞는 논문 분석 및 비교
- 근거와 출처가 포함된 리포트 작성
- 참고 논문과 리포트 저장, 목록 조회, 불러오기 및 삭제
- SQLite를 사용한 데이터 보존

완성된 결과물은 다음 흐름을 지원해야 한다.

```text
연구 질문
→ OpenAlex를 활용한 논문 검색
→ 연구 목적에 따른 데이터 비교
→ 근거와 출처가 포함된 리포트 작성
→ 리포트 저장
→ 저장된 리포트 목록 조회·불러오기·삭제
```

## 참고 구현

이 저장소에는 Python으로 실행하는 가장 기본적인 MCP Server가 포함되어 있다.

참고 Tool은 입력받은 논문명을 OpenAlex에서 검색하고, 검색된 논문의 제목·발행 연도·저자·DOI·OpenAlex 주소를 반환한다. 이 코드는 MCP Server의 선언, Tool 등록, OpenAlex 요청과 `stdio` 구동 구조를 확인하기 위한 참고 구현이다.

## 준비

Python 3.10 이상이 필요하다.

먼저 Python 버전을 확인한다. 3.10보다 낮다면 설치된 Python 3.10 이상의 실행 명령을 사용한다.

```bash
python3 --version
```

Windows PowerShell:

```powershell
python --version
```

macOS와 Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## MCP Server 실행

```bash
python server.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe server.py
```

MCP Host는 위 명령으로 Server를 실행하고 표준 입력과 표준 출력을 통해 통신한다.

## MCP Host 등록

Claude Code에 등록한다. 경로는 절대경로로 적는다. Host가 어느 작업 디렉터리에서 Server를 실행하든 같은 데이터베이스를 사용한다.

Windows:

```powershell
claude mcp add -s user etri-capstone -- "C:\경로\etri-capstone\.venv\Scripts\python.exe" "C:\경로\etri-capstone\server.py"
```

macOS와 Linux:

```bash
claude mcp add -s user etri-capstone -- /경로/etri-capstone/.venv/bin/python /경로/etri-capstone/server.py
```

등록 결과를 확인한다.

```bash
claude mcp list
```

`etri-capstone`이 `Connected`로 표시되면 등록된 것이다. 이미 열려 있는 세션에는 반영되지 않으므로 새 세션을 시작한다.

`-s user`는 모든 프로젝트에서 사용한다는 뜻이다. `-s project`를 쓰면 저장소에 `.mcp.json`이 만들어지지만 절대경로가 함께 커밋되어 다른 컴퓨터와 충돌한다.

## 제공 Tool

```text
search_papers_by_title   list_reports   update_report   list_papers
save_report              get_report     delete_report   delete_paper
```

| Tool | 설명 |
| --- | --- |
| `search_papers_by_title` | 논문명을 OpenAlex에서 검색해 제목·연도·저자·DOI·주소·인용 수·연구 분야를 반환한다 |
| `save_report` | 작성한 리포트를 근거가 된 참고 논문과 함께 저장한다 |
| `list_reports` | 저장된 리포트를 최근 수정 순으로 조회한다. 상태와 태그로 거를 수 있다 |
| `get_report` | 리포트를 본문과 참고 논문까지 모두 불러온다 |
| `update_report` | 전달한 필드만 수정한다. 보관은 `status`를 `archived`로 바꾼다 |
| `delete_report` | 리포트를 삭제한다. 인용 관계만 정리되고 참고 논문은 남는다 |
| `list_papers` | 저장된 참고 논문을 인용 리포트 수와 함께 조회한다 |
| `delete_paper` | 참고 논문을 삭제한다. 리포트가 인용 중이면 거부한다 |

검색 결과 항목은 `save_report`의 `papers` 인자에 그대로 넣을 수 있고, 항목마다 `evidence`에 그 논문이 뒷받침하는 주장을 적는다.

## OpenAlex API 키

검색은 API 키 없이도 동작하지만, 공용 대역은 요청이 몰리면 `HTTP 429`로 거절된다. 키가 있으면 `server.py` 옆에 `.env` 파일을 만들어 적는다.

```text
OPENALEX_API_KEY=발급받은_키
```

Server는 시작할 때 이 파일을 읽어 아직 비어 있는 환경 변수만 채운다. MCP Host 설정에서 `OPENALEX_API_KEY`를 직접 넘기면 그 값이 우선한다.

`.env`는 `.gitignore`에 포함되어 커밋되지 않는다. 키는 저장소에 올리지 않는다.

## 데이터 저장

리포트와 참고 논문은 `server.py` 옆의 `research.db`에 저장된다. 파일은 Server를 처음 실행할 때 만들어지며 `.gitignore`로 커밋에서 제외된다. 스키마와 Tool 계약은 `SPEC.md`에 정리되어 있다.

데이터를 초기화하려면 `research.db` 파일을 삭제하고 Server를 다시 실행한다.

## 웹으로 리포트 읽기

저장된 리포트를 브라우저에서 읽는 React 앱이 `web/`에 있다. 브라우저는 `stdio`로 통신하는 MCP Server에 직접 붙을 수 없으므로, 같은 `database.py`를 재사용하는 읽기 전용 HTTP API를 거친다. 설계와 계약은 `SPEC-web.md`에 정리되어 있다.

Node.js 20 이상이 필요하다. 처음 한 번만 의존성을 설치한다.

```bash
cd web
npm install
```

터미널 두 개에서 각각 실행한다.

```bash
python web_api.py
```

```bash
cd web
npm run dev
```

브라우저에서 `http://localhost:3000`을 연다. 목록에서 리포트를 누르면 상세 페이지로 이동해 본문과 참고 논문을 읽을 수 있다.

API 서버는 `127.0.0.1:8000`에만 바인딩되므로 같은 네트워크의 다른 기기에서는 접근할 수 없다. 화면은 조회만 제공하며 저장과 수정, 삭제는 MCP Tool을 통한다.

## 다른 컴퓨터에서 사용

저장소를 내려받는 것만으로는 동작하지 않는다. `.env`와 `research.db`는 `.gitignore` 대상이라 함께 오지 않고, MCP 등록의 경로는 컴퓨터마다 다르다.

1. 저장소를 내려받는다.
2. 위 `준비` 절에 따라 가상환경을 만들고 의존성을 설치한다.
3. `.env`를 새로 만들고 OpenAlex 키를 적는다. 키는 저장소나 대화 기록을 거쳐 옮기지 않는다.
4. 위 `MCP Host 등록` 절에 따라 그 컴퓨터의 경로로 등록한다.
5. 웹 화면을 쓴다면 `web` 디렉터리에서 `npm install`을 실행한다. `node_modules/`도 커밋되지 않는다.

리포트와 참고 논문은 컴퓨터마다 별도의 `research.db`에 쌓이며 서로 동기화되지 않는다.

## 프로젝트 스킬

저장소를 내려받아 프로젝트 루트에서 LLM 애플리케이션을 실행하면 `.claude/skills`의 스킬을 사용할 수 있다.

```text
/interview 구현할 기능의 요구사항을 명세로 정리
/code-review 현재 변경에서 수정이 필요한 문제만 검토
```
