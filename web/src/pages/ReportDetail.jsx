import { Link, useParams } from 'react-router-dom'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchReport, useApi } from '../api.js'

const STATUS_LABEL = { draft: '초안', final: '확정', archived: '보관' }

function authorLine(authors, year) {
  const names =
    authors.length === 0
      ? '저자 정보 없음'
      : authors.length > 3
        ? `${authors.slice(0, 3).join(', ')} 외 ${authors.length - 3}인`
        : authors.join(', ')
  return year ? `${names} · ${year}` : names
}

function Reference({ paper, order }) {
  const link = paper.landing_page_url || paper.doi

  return (
    <li className="reference">
      <span className="reference-order">[{order}]</span>
      <div>
        <p className="reference-title">{paper.title}</p>
        <p className="reference-authors">
          {authorLine(paper.authors, paper.publication_year)}
        </p>

        <div className="reference-meta">
          {paper.cited_by_count !== null && (
            <span className="cites">인용 {paper.cited_by_count.toLocaleString('ko-KR')}회</span>
          )}
          {paper.field && (
            <span className="meta-item">
              {paper.field}
              {paper.topic ? ` / ${paper.topic}` : ''}
            </span>
          )}
          {link && (
            <a href={link} target="_blank" rel="noreferrer" className="reference-link">
              원문 보기
            </a>
          )}
        </div>

        {paper.evidence && (
          <p className="evidence">
            <span className="evidence-label">근거</span>
            {paper.evidence}
          </p>
        )}
      </div>
    </li>
  )
}

export default function ReportDetail() {
  const { id } = useParams()
  const { loading, data, error } = useApi(() => fetchReport(id), [id])

  if (loading) return <p className="notice">불러오는 중입니다.</p>

  if (error) {
    return (
      <div className="notice notice-error">
        <p>{error.message}</p>
        {error.offline && <pre className="hint">python web_api.py</pre>}
        <Link to="/" className="back-link">
          목록으로 돌아가기
        </Link>
      </div>
    )
  }

  return (
    <article>
      <Link to="/" className="back-link">
        목록으로 돌아가기
      </Link>

      <header className="page-head detail-head">
        <h1>{data.title}</h1>
        {data.research_question && (
          <p className="detail-question">{data.research_question}</p>
        )}
        <div className="report-meta">
          <span className={`badge badge-${data.status}`}>
            {STATUS_LABEL[data.status] ?? data.status}
          </span>
          <span className="meta-item">v{data.version}</span>
          <span className="meta-item">{data.format}</span>
          <span className="meta-item">작성 {data.created_at}</span>
          <span className="meta-item">수정 {data.updated_at}</span>
        </div>
        {data.tags.length > 0 && (
          <div className="tags">
            {data.tags.map((tag) => (
              <span key={tag} className="tag">
                {tag}
              </span>
            ))}
          </div>
        )}
      </header>

      <div className="document">
        <Markdown remarkPlugins={[remarkGfm]}>{data.content}</Markdown>
      </div>

      <section className="bibliography">
        <h2>참고 논문 {data.papers.length}편</h2>
        {data.papers.length === 0 ? (
          <p className="hint-text">연결된 참고 논문이 없습니다.</p>
        ) : (
          <ol className="reference-list">
            {data.papers.map((paper, index) => (
              <Reference key={paper.paper_id} paper={paper} order={index + 1} />
            ))}
          </ol>
        )}
      </section>
    </article>
  )
}
