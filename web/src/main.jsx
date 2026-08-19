import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import ReportList from './pages/ReportList.jsx'
import ReportDetail from './pages/ReportDetail.jsx'
import './styles.css'

function NotFound() {
  return (
    <div className="notice">
      <p>없는 주소입니다.</p>
      <Link to="/" className="back-link">
        목록으로 돌아가기
      </Link>
    </div>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <div className="app">
        <Routes>
          <Route path="/" element={<ReportList />} />
          <Route path="/reports/:id" element={<ReportDetail />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </BrowserRouter>
  </StrictMode>,
)
