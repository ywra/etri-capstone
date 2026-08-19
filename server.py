from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server import MCPServer

import database


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_RESULT_LIMIT = 5
MAX_RESULT_LIMIT = 10

ENV_FILE = Path(__file__).parent / ".env"


def load_env_file() -> None:
    """server.py 옆의 .env를 읽어 아직 비어 있는 환경 변수만 채운다.

    MCP Host가 환경 변수를 직접 넘기면 그 값을 그대로 둔다.
    """

    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        setting = line.strip()
        if not setting or setting.startswith("#") or "=" not in setting:
            continue
        name, _, value = setting.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))

server = MCPServer(
    name="openalex-paper-search",
    title="OpenAlex 논문 검색과 리포트 저장소",
    description=(
        "논문명을 검색해 OpenAlex의 논문 정보를 반환하고, "
        "작성한 리포트를 참고 논문과 함께 SQLite에 저장하고 다시 활용합니다."
    ),
)


def _author_names(authorships: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for authorship in authorships:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(str(name))
    return names


def _search_openalex(title: str, limit: int) -> dict[str, Any]:
    params = {
        "search": title,
        "per_page": limit,
        "select": (
            "id,display_name,publication_year,doi,authorships,primary_location,"
            "cited_by_count,primary_topic"
        ),
    }
    api_key = os.getenv("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key

    request = Request(
        f"{OPENALEX_WORKS_URL}?{urlencode(params)}",
        headers={"User-Agent": "etri-capstone/1.0"},
    )

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as error:
        return {
            "query": title,
            "error": f"OpenAlex가 HTTP {error.code} 응답을 반환했습니다.",
            "papers": [],
        }
    except URLError as error:
        return {
            "query": title,
            "error": f"OpenAlex에 연결하지 못했습니다: {error.reason}",
            "papers": [],
        }

    papers: list[dict[str, Any]] = []
    for work in payload.get("results", []):
        primary_location = work.get("primary_location") or {}
        primary_topic = work.get("primary_topic") or {}
        topic_field = primary_topic.get("field") or {}
        papers.append(
            {
                "openalex_id": work.get("id"),
                "title": work.get("display_name"),
                "publication_year": work.get("publication_year"),
                "authors": _author_names(work.get("authorships") or []),
                "doi": work.get("doi"),
                "landing_page_url": primary_location.get("landing_page_url"),
                "cited_by_count": work.get("cited_by_count"),
                "topic": primary_topic.get("display_name"),
                "field": topic_field.get("display_name"),
            }
        )

    return {
        "query": title,
        "count": len(papers),
        "papers": papers,
    }


@server.tool(structured_output=True)
def search_papers_by_title(
    title: str,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> dict[str, Any]:
    """논문명을 검색어로 사용해 OpenAlex에서 관련 논문을 찾는다.

    반환된 논문 항목은 save_report의 papers 인자에 그대로 넣을 수 있다.

    Args:
        title: 찾고 싶은 논문의 이름 또는 제목에 포함된 검색어.
        limit: 반환할 논문 수. 기본값은 5이며 최대 10이다.
    """

    normalized_title = title.strip()
    if not normalized_title:
        return {
            "query": title,
            "error": "검색할 논문명을 입력해 주세요.",
            "papers": [],
        }

    safe_limit = max(1, min(limit, MAX_RESULT_LIMIT))
    return _search_openalex(normalized_title, safe_limit)


@server.tool(structured_output=True)
def save_report(
    title: str,
    content: str,
    research_question: str | None = None,
    report_format: str = database.DEFAULT_FORMAT,
    status: str = database.DEFAULT_STATUS,
    tags: list[str] | None = None,
    papers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """작성한 리포트를 근거가 된 참고 논문과 함께 저장한다.

    Args:
        title: 리포트 제목.
        content: 리포트 본문.
        research_question: 이 리포트가 답하는 연구 질문.
        report_format: 본문 형식. markdown, html, text 중 하나이며 기본값은 markdown.
        status: 상태. draft, final, archived 중 하나이며 기본값은 draft.
        tags: 분류 태그 배열. 예: ["RAG", "LLM"].
        papers: 근거로 사용한 논문 배열. search_papers_by_title 결과 항목을 그대로 넣고
            항목마다 evidence를 덧붙인다. 항목의 키는 openalex_id와 title이 필수이고
            publication_year, authors, doi, landing_page_url, cited_by_count, topic,
            field, evidence는 선택이다. evidence에는 그 논문이 리포트에서 뒷받침하는
            주장을 적는다.
    """

    try:
        return database.save_report(
            title=title,
            content=content,
            research_question=research_question,
            report_format=report_format,
            status=status,
            tags=tags,
            papers=papers,
        )
    except database.DatabaseError as error:
        return {"error": str(error)}


@server.tool(structured_output=True)
def list_reports(
    status: str | None = None,
    tag: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """저장된 리포트 목록을 최근 수정 순으로 조회한다.

    본문 전체 대신 앞부분 미리보기만 반환한다. 본문이 필요하면 get_report를 사용한다.

    Args:
        status: draft, final, archived 중 하나로 거른다. 지정하지 않으면 archived를 제외한다.
        tag: 이 태그를 가진 리포트만 거른다. 태그 이름은 완전히 일치해야 한다.
        limit: 반환할 리포트 수. 기본값은 20이며 최대 100이다.
        offset: 건너뛸 리포트 수. 기본값은 0이다.
    """

    try:
        return database.list_reports(status=status, tag=tag, limit=limit, offset=offset)
    except database.DatabaseError as error:
        return {"error": str(error)}


@server.tool(structured_output=True)
def get_report(report_id: int) -> dict[str, Any]:
    """저장된 리포트를 본문과 참고 논문까지 모두 불러온다.

    Args:
        report_id: 불러올 리포트의 식별자. list_reports로 확인할 수 있다.
    """

    try:
        return database.get_report(report_id)
    except database.DatabaseError as error:
        return {"error": str(error)}


@server.tool(structured_output=True)
def update_report(
    report_id: int,
    title: str | None = None,
    content: str | None = None,
    research_question: str | None = None,
    report_format: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    papers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """저장된 리포트를 수정한다. 전달한 필드만 바뀐다.

    본문이 실제로 달라진 경우에만 version이 올라간다. 리포트를 지우지 않고 보관하려면
    status를 archived로 바꾼다.

    Args:
        report_id: 수정할 리포트의 식별자.
        title: 새 제목.
        content: 새 본문.
        research_question: 새 연구 질문.
        report_format: 새 본문 형식. markdown, html, text 중 하나.
        status: 새 상태. draft, final, archived 중 하나.
        tags: 새 태그 배열. 기존 태그를 대체한다.
        papers: 새 참고 논문 배열. 기존 인용 목록을 전부 대체한다. 항목 형식은
            save_report와 같다.
    """

    try:
        return database.update_report(
            report_id=report_id,
            title=title,
            content=content,
            research_question=research_question,
            report_format=report_format,
            status=status,
            tags=tags,
            papers=papers,
        )
    except database.DatabaseError as error:
        return {"error": str(error)}


@server.tool(structured_output=True)
def delete_report(report_id: int) -> dict[str, Any]:
    """저장된 리포트를 삭제한다.

    인용 관계만 함께 정리되고 참고 논문 자체는 남는다. 되돌릴 수 없으므로 나중에 다시 볼
    가능성이 있다면 update_report로 status를 archived로 바꾸는 편이 낫다.

    Args:
        report_id: 삭제할 리포트의 식별자.
    """

    try:
        return database.delete_report(report_id)
    except database.DatabaseError as error:
        return {"error": str(error)}


@server.tool(structured_output=True)
def list_papers(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """저장된 참고 논문 목록을 최근 저장 순으로 조회한다.

    각 항목의 cited_in은 그 논문을 인용하는 리포트 수다.

    Args:
        limit: 반환할 논문 수. 기본값은 50이며 최대 200이다.
        offset: 건너뛸 논문 수. 기본값은 0이다.
    """

    try:
        return database.list_papers(limit=limit, offset=offset)
    except database.DatabaseError as error:
        return {"error": str(error)}


@server.tool(structured_output=True)
def delete_paper(paper_id: int) -> dict[str, Any]:
    """저장된 참고 논문을 삭제한다.

    리포트가 인용 중인 논문은 삭제할 수 없고, 어떤 리포트가 인용 중인지 알려준다.

    Args:
        paper_id: 삭제할 논문의 식별자. list_papers로 확인할 수 있다.
    """

    try:
        return database.delete_paper(paper_id)
    except database.DatabaseError as error:
        return {"error": str(error)}


if __name__ == "__main__":
    load_env_file()
    database.initialize()
    server.run(transport="stdio")
