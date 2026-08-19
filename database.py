from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DB_PATH = Path(__file__).parent / "research.db"
SCHEMA_VERSION = 1

REPORT_STATUSES = ("draft", "final", "archived")
REPORT_FORMATS = ("markdown", "html", "text")
DEFAULT_STATUS = "draft"
DEFAULT_FORMAT = "markdown"

PREVIEW_LENGTH = 200
MAX_REPORT_PAGE_SIZE = 100
MAX_PAPER_PAGE_SIZE = 200

PAPER_COLUMNS = (
    "openalex_id",
    "title",
    "publication_year",
    "authors",
    "doi",
    "landing_page_url",
    "cited_by_count",
    "topic",
    "field",
)


class DatabaseError(Exception):
    """Tool 응답으로 그대로 전달할 수 있는 오류."""


def _sql_choices(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


SCHEMA = f"""
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
    format            TEXT    NOT NULL DEFAULT '{DEFAULT_FORMAT}'
                      CHECK (format IN ({_sql_choices(REPORT_FORMATS)})),
    status            TEXT    NOT NULL DEFAULT '{DEFAULT_STATUS}'
                      CHECK (status IN ({_sql_choices(REPORT_STATUSES)})),
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
"""

UPSERT_PAPER = f"""
INSERT INTO papers ({", ".join(PAPER_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in PAPER_COLUMNS)})
ON CONFLICT(openalex_id) DO UPDATE SET
    {", ".join(f"{column} = excluded.{column}" for column in PAPER_COLUMNS[1:])},
    saved_at = datetime('now')
RETURNING id
"""

SELECT_REPORT_LIST = f"""
SELECT r.id, r.title, r.research_question, r.status, r.tags, r.version,
       r.created_at, r.updated_at,
       CASE WHEN length(r.content) > {PREVIEW_LENGTH}
            THEN substr(r.content, 1, {PREVIEW_LENGTH}) || '...'
            ELSE r.content END AS preview,
       (SELECT COUNT(*) FROM report_papers rp WHERE rp.report_id = r.id) AS paper_count
  FROM reports r
 WHERE ((:status IS NULL AND r.status <> 'archived') OR r.status = :status)
   AND (:tag IS NULL OR EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = :tag))
 ORDER BY r.updated_at DESC, r.id DESC
 LIMIT :limit OFFSET :offset
"""

SELECT_REPORT_PAPERS = """
SELECT p.*, rp.evidence, rp.position
  FROM papers p
  JOIN report_papers rp ON rp.paper_id = p.id
 WHERE rp.report_id = ?
 ORDER BY rp.position, p.id
"""

SELECT_PAPER_LIST = """
SELECT p.*,
       (SELECT COUNT(*) FROM report_papers rp WHERE rp.paper_id = p.id) AS cited_in
  FROM papers p
 ORDER BY p.saved_at DESC, p.id DESC
 LIMIT ? OFFSET ?
"""

SELECT_CITING_REPORTS = """
SELECT r.title
  FROM reports r
  JOIN report_papers rp ON rp.report_id = r.id
 WHERE rp.paper_id = ?
 ORDER BY r.id
"""


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    """외래 키를 켠 커넥션을 열고, 블록이 끝나면 커밋한 뒤 닫는다."""

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    except sqlite3.IntegrityError as error:
        raise DatabaseError(f"데이터 제약을 위반했습니다: {error}") from error
    finally:
        connection.close()


def initialize() -> None:
    """스키마를 생성한다. 이미 있으면 아무것도 바꾸지 않는다."""

    with _transaction() as connection:
        connection.executescript(SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _require_text(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatabaseError(f"{field} 값이 비어 있습니다. 내용을 입력해 주세요.")
    return value.strip()


def _require_choice(field: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise DatabaseError(
            f"{field}는 {', '.join(allowed)} 중 하나여야 합니다. 받은 값: {value!r}"
        )
    return str(value)


def _require_page(limit: Any, offset: Any, maximum: int) -> tuple[int, int]:
    if not isinstance(limit, int) or not isinstance(offset, int):
        raise DatabaseError("limit과 offset은 정수여야 합니다.")
    return max(1, min(limit, maximum)), max(0, offset)


def _normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise DatabaseError('tags는 문자열 배열이어야 합니다. 예: ["RAG", "LLM"]')

    normalized: list[str] = []
    for tag in tags:
        cleaned = tag.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _normalize_papers(papers: Any) -> list[dict[str, Any]]:
    if papers is None:
        return []
    if not isinstance(papers, list):
        raise DatabaseError("papers는 논문 객체 배열이어야 합니다.")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, paper in enumerate(papers):
        if not isinstance(paper, dict):
            raise DatabaseError(f"papers[{index}]가 객체가 아닙니다.")

        openalex_id = paper.get("openalex_id")
        title = paper.get("title")
        if not openalex_id or not title:
            raise DatabaseError(
                f"papers[{index}]에 openalex_id와 title이 모두 필요합니다. "
                "search_papers_by_title 결과를 그대로 전달해 주세요."
            )
        if openalex_id in seen:
            continue
        seen.add(str(openalex_id))

        authors = paper.get("authors") or []
        if not isinstance(authors, list):
            raise DatabaseError(f"papers[{index}].authors는 문자열 배열이어야 합니다.")

        normalized.append(
            {
                "openalex_id": str(openalex_id),
                "title": str(title),
                "publication_year": paper.get("publication_year"),
                "authors": json.dumps(
                    [str(author) for author in authors], ensure_ascii=False
                ),
                "doi": paper.get("doi"),
                "landing_page_url": paper.get("landing_page_url"),
                "cited_by_count": paper.get("cited_by_count"),
                "topic": paper.get("topic"),
                "field": paper.get("field"),
                "evidence": paper.get("evidence"),
            }
        )
    return normalized


def _paper_row(row: sqlite3.Row) -> dict[str, Any]:
    columns = row.keys()
    paper = {
        "paper_id": row["id"],
        "openalex_id": row["openalex_id"],
        "title": row["title"],
        "publication_year": row["publication_year"],
        "authors": json.loads(row["authors"]),
        "doi": row["doi"],
        "landing_page_url": row["landing_page_url"],
        "cited_by_count": row["cited_by_count"],
        "topic": row["topic"],
        "field": row["field"],
        "saved_at": row["saved_at"],
    }
    if "evidence" in columns:
        paper["evidence"] = row["evidence"]
    if "cited_in" in columns:
        paper["cited_in"] = row["cited_in"]
    return paper


def _require_report(connection: sqlite3.Connection, report_id: Any) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    if row is None:
        raise DatabaseError(
            f"report_id {report_id!r} 리포트를 찾을 수 없습니다. list_reports로 확인해 주세요."
        )
    return row


def _replace_links(
    connection: sqlite3.Connection,
    report_id: int,
    papers: list[dict[str, Any]],
) -> None:
    connection.execute("DELETE FROM report_papers WHERE report_id = ?", (report_id,))
    for position, paper in enumerate(papers):
        paper_id = connection.execute(
            UPSERT_PAPER, {column: paper[column] for column in PAPER_COLUMNS}
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO report_papers (report_id, paper_id, evidence, position)
            VALUES (?, ?, ?, ?)
            """,
            (report_id, paper_id, paper["evidence"], position),
        )


def save_report(
    title: str,
    content: str,
    research_question: str | None = None,
    report_format: str = DEFAULT_FORMAT,
    status: str = DEFAULT_STATUS,
    tags: list[str] | None = None,
    papers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    values = {
        "title": _require_text("title", title),
        "research_question": research_question,
        "content": _require_text("content", content),
        "format": _require_choice("format", report_format, REPORT_FORMATS),
        "status": _require_choice("status", status, REPORT_STATUSES),
        "tags": json.dumps(_normalize_tags(tags), ensure_ascii=False),
    }
    paper_list = _normalize_papers(papers)

    with _transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO reports (title, research_question, content, format, status, tags)
            VALUES (:title, :research_question, :content, :format, :status, :tags)
            """,
            values,
        )
        report_id = int(cursor.lastrowid)
        _replace_links(connection, report_id, paper_list)
        row = connection.execute(
            "SELECT version, created_at FROM reports WHERE id = ?", (report_id,)
        ).fetchone()

    return {
        "report_id": report_id,
        "title": values["title"],
        "version": row["version"],
        "created_at": row["created_at"],
        "saved_paper_count": len(paper_list),
    }


def list_reports(
    status: str | None = None,
    tag: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    if status is not None:
        status = _require_choice("status", status, REPORT_STATUSES)
    limit, offset = _require_page(limit, offset, MAX_REPORT_PAGE_SIZE)

    with _transaction() as connection:
        rows = connection.execute(
            SELECT_REPORT_LIST,
            {"status": status, "tag": tag, "limit": limit, "offset": offset},
        ).fetchall()

    reports = [
        {
            "report_id": row["id"],
            "title": row["title"],
            "research_question": row["research_question"],
            "status": row["status"],
            "tags": json.loads(row["tags"]),
            "version": row["version"],
            "preview": row["preview"],
            "paper_count": row["paper_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return {"count": len(reports), "reports": reports}


def get_report(report_id: int) -> dict[str, Any]:
    with _transaction() as connection:
        row = _require_report(connection, report_id)
        papers = connection.execute(SELECT_REPORT_PAPERS, (report_id,)).fetchall()

    return {
        "report_id": row["id"],
        "title": row["title"],
        "research_question": row["research_question"],
        "content": row["content"],
        "format": row["format"],
        "status": row["status"],
        "tags": json.loads(row["tags"]),
        "version": row["version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "papers": [_paper_row(paper) for paper in papers],
    }


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
    assignments: dict[str, Any] = {}
    if title is not None:
        assignments["title"] = _require_text("title", title)
    if content is not None:
        assignments["content"] = _require_text("content", content)
    if research_question is not None:
        assignments["research_question"] = research_question
    if report_format is not None:
        assignments["format"] = _require_choice("format", report_format, REPORT_FORMATS)
    if status is not None:
        assignments["status"] = _require_choice("status", status, REPORT_STATUSES)
    if tags is not None:
        assignments["tags"] = json.dumps(_normalize_tags(tags), ensure_ascii=False)

    paper_list = None if papers is None else _normalize_papers(papers)
    if not assignments and paper_list is None:
        raise DatabaseError(
            "변경할 필드를 최소 하나 지정해 주세요. "
            "title, content, research_question, report_format, status, tags, papers "
            "중에서 선택합니다."
        )

    with _transaction() as connection:
        _require_report(connection, report_id)

        if assignments:
            clause = ", ".join(f"{column} = :{column}" for column in assignments)
            connection.execute(
                f"UPDATE reports SET {clause} WHERE id = :report_id",
                {**assignments, "report_id": report_id},
            )

        if paper_list is not None:
            _replace_links(connection, report_id, paper_list)
            if not assignments:
                # 인용 목록만 바뀐 경우에도 reports_touch 트리거가 updated_at을 갱신하게 한다.
                connection.execute(
                    "UPDATE reports SET title = title WHERE id = ?", (report_id,)
                )

        row = connection.execute(
            "SELECT version, updated_at FROM reports WHERE id = ?", (report_id,)
        ).fetchone()

    changed_fields = sorted(assignments)
    if paper_list is not None:
        changed_fields.append("papers")

    return {
        "report_id": report_id,
        "version": row["version"],
        "updated_at": row["updated_at"],
        "changed_fields": changed_fields,
    }


def delete_report(report_id: int) -> dict[str, Any]:
    with _transaction() as connection:
        row = _require_report(connection, report_id)
        unlinked = connection.execute(
            "SELECT COUNT(*) AS total FROM report_papers WHERE report_id = ?",
            (report_id,),
        ).fetchone()["total"]
        connection.execute("DELETE FROM reports WHERE id = ?", (report_id,))

    return {
        "report_id": report_id,
        "deleted_title": row["title"],
        "unlinked_paper_count": unlinked,
    }


def list_papers(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit, offset = _require_page(limit, offset, MAX_PAPER_PAGE_SIZE)

    with _transaction() as connection:
        rows = connection.execute(SELECT_PAPER_LIST, (limit, offset)).fetchall()

    papers = [_paper_row(row) for row in rows]
    return {"count": len(papers), "papers": papers}


def delete_paper(paper_id: int) -> dict[str, Any]:
    with _transaction() as connection:
        row = connection.execute(
            "SELECT title FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            raise DatabaseError(
                f"paper_id {paper_id!r} 논문을 찾을 수 없습니다. list_papers로 확인해 주세요."
            )

        citing = connection.execute(SELECT_CITING_REPORTS, (paper_id,)).fetchall()
        if citing:
            titles = ", ".join(f"'{report['title']}'" for report in citing)
            raise DatabaseError(
                f"리포트 {len(citing)}건이 인용 중이라 삭제할 수 없습니다: {titles}. "
                "해당 리포트를 먼저 삭제하거나 update_report로 인용에서 제외해 주세요."
            )

        connection.execute("DELETE FROM papers WHERE id = ?", (paper_id,))

    return {"paper_id": paper_id, "deleted_title": row["title"]}
