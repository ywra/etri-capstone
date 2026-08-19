import { Link } from 'react-router-dom'
import { fetchReports, useApi } from '../api.js'

const STATUS_LABEL = { draft: '초안', final: '확정', archived: '보관' }

/** 미리보기는 본문 앞부분을 그대로 잘라온 값이라 마크다운 기호가 섞여 있다. */
function plainPreview(text) {
  return text
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*([^*]*)\*\*/g, '$1')
    .replace(/^[>#\-*\s]+/gm, '')
    .split('\n')
    .filter((line) => line.trim())
    .join(' ')
}

export default function ReportList() {
  const { loading, data, error } = useApi(fetchReports, [])

  if (loading) return <p className="notice">불러오는 중입니다.</p>

  if (error) {
    return (
      <div className="notice notice-error">
        <p>{error.message}</p>
        {error.offline && (
          <pre className="hint">python web_api.py</pre>
        )}
      </div>
    )
  }

  if (data.count === 0) {
    return (
      <div className="notice">
        <p>저장된 리포트가 없습니다.</p>
        <p className="hint-text">
          MCP Tool <code>save_report</code>로 리포트를 저장하면 여기에 나타납니다.
        </p>
      </div>
    )
  }

  return (
    <>
      <header className="page-head">
        <h1>저장된 리포트</h1>
        <p className="count">{data.count}건</p>
      </header>

      <ul className="report-list">
        {data.reports.map((report) => (
          <li key={report.report_id}>
            <Link to={`/reports/${report.report_id}`} className="report-card">
              <div className="report-card-head">
                <span className="report-id">#{report.report_id}</span>
                <h2>{report.title}</h2>
              </div>

              {report.research_question && (
                <p className="report-question">{report.research_question}</p>
              )}

              <p className="report-preview">{plainPreview(report.preview)}</p>

              <div className="report-meta">
                <span className={`badge badge-${report.status}`}>
                  {STATUS_LABEL[report.status] ?? report.status}
                </span>
                <span className="meta-item">v{report.version}</span>
                <span className="meta-item">참고 논문 {report.paper_count}편</span>
                <span className="meta-item">{report.updated_at}</span>
              </div>

              {report.tags.length > 0 && (
                <div className="tags">
                  {report.tags.map((tag) => (
                    <span key={tag} className="tag">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}
