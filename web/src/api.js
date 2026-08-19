import { useEffect, useState } from 'react'

const OFFLINE_MESSAGE =
  'API 서버에 연결할 수 없습니다. 터미널에서 python web_api.py 를 실행해 주세요.'

export class ApiError extends Error {
  constructor(message, { offline = false } = {}) {
    super(message)
    this.name = 'ApiError'
    this.offline = offline
  }
}

async function getJSON(path) {
  let response
  try {
    response = await fetch(path)
  } catch {
    throw new ApiError(OFFLINE_MESSAGE, { offline: true })
  }

  let body
  try {
    body = await response.json()
  } catch {
    // API 서버가 꺼져 있으면 Vite proxy가 JSON이 아닌 502 본문을 돌려준다.
    throw new ApiError(OFFLINE_MESSAGE, { offline: true })
  }

  if (!response.ok) {
    throw new ApiError(body.error || `요청이 실패했습니다. HTTP ${response.status}`)
  }
  return body
}

export const fetchReports = () => getJSON('/api/reports')
export const fetchReport = (id) => getJSON(`/api/reports/${id}`)

/** 요청 상태를 로딩, 성공, 실패 세 가지로 정리해 돌려준다. */
export function useApi(request, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null })

  useEffect(() => {
    let active = true
    setState({ loading: true, data: null, error: null })

    request().then(
      (data) => active && setState({ loading: false, data, error: null }),
      (error) => active && setState({ loading: false, data: null, error }),
    )

    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
