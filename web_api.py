"""저장된 리포트를 브라우저에서 읽기 위한 읽기 전용 HTTP API.

MCP Server는 stdio로 통신하므로 브라우저가 직접 붙을 수 없다. 이 서버는 같은 database.py를
재사용해 조회만 제공한다. 쓰기는 전부 MCP Tool을 통한다.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import database


HOST = "127.0.0.1"
PORT = 8000
LIST_LIMIT = database.MAX_REPORT_PAGE_SIZE

REPORTS_PATH = "/api/reports"
REPORT_PATH_PREFIX = REPORTS_PATH + "/"


class ReportHandler(BaseHTTPRequestHandler):
    server_version = "etri-capstone-web/1.0"

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server가 요구하는 이름
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        try:
            if path == REPORTS_PATH:
                return self._respond(200, database.list_reports(
                    limit=LIST_LIMIT, include_archived=True
                ))

            if path.startswith(REPORT_PATH_PREFIX):
                raw_id = path[len(REPORT_PATH_PREFIX):]
                # isdigit()은 위첨자 같은 문자에도 참이라 int()에서 터진다.
                if not raw_id.isdecimal():
                    return self._respond(
                        404, {"error": f"report_id {raw_id!r}는 숫자가 아닙니다."}
                    )
                return self._respond(200, database.get_report(int(raw_id)))

            return self._respond(404, {"error": f"{path} 경로를 찾을 수 없습니다."})

        except database.DatabaseError as error:
            self._respond(404, {"error": str(error)})
        except Exception as error:  # noqa: BLE001 - 어떤 실패든 JSON으로 돌려준다
            self._respond(500, {"error": f"서버 오류가 발생했습니다: {error}"})


def main() -> None:
    database.initialize()
    print(f"리포트 API: http://{HOST}:{PORT}{REPORTS_PATH}")
    print(f"데이터베이스: {database.DB_PATH}")
    print("종료하려면 Ctrl+C를 누릅니다.")

    server = ThreadingHTTPServer((HOST, PORT), ReportHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
