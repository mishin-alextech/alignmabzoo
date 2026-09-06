export type Animal = { code: string; name: string }

export type GroupSelection = {
  name: string
  groups: string[]
}

export type AnimalSelection = {
  code: string
  projects: GroupSelection[]
}

export type JobSelection = {
  animals: AnimalSelection[]
  exclude_x_file?: boolean
}

export type JobCounts = {
  files_found?: number
  files_processed?: number
  files_skipped?: number
  files_failed?: number
  sequences?: number
}

export type Job = {
  id: string
  name: string
  status: 'queued' | 'running' | 'done' | 'partial' | 'failed' | string
  created_at: string
  updated_at?: string
  started_at?: string | null
  finished_at?: string | null
  counts?: JobCounts
  failure_reason?: string | null
  selection?: JobSelection
}

export type CdrScheme = 'imgt' | 'kabat' | 'chothia'

export type CdrPositions = {
  cdr1?: number[]
  cdr2?: number[]
  cdr3?: number[]
}

export type AlignmentSequence = {
  name: string
  seq: string
  numbering?: Partial<Record<CdrScheme, Array<string | number | null>>>
  cdr?: Partial<Record<CdrScheme, CdrPositions>>
}

export type AlignmentGroup = {
  name: 'VHeavy' | 'VKappa' | 'VLambda' | 'Other' | string
  sequences: AlignmentSequence[]
}

export type AlignmentResponse = { groups?: AlignmentGroup[] }
export type BrowsePage = { items: string[]; nextOffset: number | null }

export type ReportEntry = { path?: string; reason?: string }

export type JobReport = {
  processed?: ReportEntry[]
  skipped?: ReportEntry[]
  clustalo_exclusions?: ReportEntry[]
  errors?: ReportEntry[]
}

type ApiErrorPayload = { detail?: unknown; message?: unknown }

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message)
    this.name = 'ApiError'
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null) {
    const { detail, message } = payload as ApiErrorPayload
    if (typeof detail === 'string') return detail
    if (typeof message === 'string') return message
  }
  return fallback
}

const REQUEST_TIMEOUT_MS = 30_000

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const externalSignal = init?.signal
  const abortExternal = () => controller.abort()
  externalSignal?.addEventListener('abort', abortExternal, { once: true })
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      signal: controller.signal,
      headers: { Accept: 'application/json', ...init?.headers },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (externalSignal?.aborted) throw error
      throw new ApiError('Превышено время ожидания запроса (30 с).')
    }
    throw new ApiError('Не удалось связаться с сервером.')
  } finally {
    clearTimeout(timeout)
    externalSignal?.removeEventListener('abort', abortExternal)
  }

  if (!response.ok) {
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      // Сервер может вернуть ошибку без JSON.
    }
    throw new ApiError(errorMessage(payload, `Ошибка сервера (${response.status}).`), response.status)
  }

  return response.json() as Promise<T>
}

export const api = {
  async animals(): Promise<Animal[]> {
    const response = await request<{ animals?: Animal[] }>('/animals')
    return response.animals ?? []
  },

  async projects(animalCode: string, offset = 0, signal?: AbortSignal): Promise<BrowsePage> {
    const response = await request<{ projects?: Array<{ name?: string }>; next_offset?: number | null }>(
      `/animals/${encodeURIComponent(animalCode)}/projects?offset=${offset}&limit=50`,
      { signal },
    )
    return {
      items: (response.projects ?? []).flatMap((item) => (item.name ? [item.name] : [])),
      nextOffset: response.next_offset ?? null,
    }
  },

  async groups(animalCode: string, project: string, offset = 0, signal?: AbortSignal): Promise<BrowsePage> {
    const response = await request<{ groups?: Array<{ name?: string }>; next_offset?: number | null }>(
      `/animals/${encodeURIComponent(animalCode)}/projects/${encodeURIComponent(project)}/groups?offset=${offset}&limit=50`,
      { signal },
    )
    return {
      items: (response.groups ?? []).flatMap((item) => (item.name ? [item.name] : [])),
      nextOffset: response.next_offset ?? null,
    }
  },

  async createJob(name: string, selection: JobSelection): Promise<Job> {
    return request<Job>('/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, selection }),
    })
  },

  async jobs(): Promise<Job[]> {
    const response = await request<{ jobs?: Job[] } | Job[]>('/jobs')
    return Array.isArray(response) ? response : response.jobs ?? []
  },

  async deleteJobs(jobIds: string[]): Promise<string[]> {
    const response = await request<{ deleted_ids?: string[] }>('/jobs', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: jobIds }),
    })
    return response.deleted_ids ?? []
  },

  job(jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${encodeURIComponent(jobId)}`)
  },

  async log(jobId: string): Promise<string> {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    let response: Response
    try {
      response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/log`, {
        signal: controller.signal,
        headers: { Accept: 'text/plain, application/json' },
      })
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError('Превышено время ожидания запроса (30 с).')
      }
      throw new ApiError('Не удалось получить журнал job.')
    } finally {
      clearTimeout(timeout)
    }
    if (!response.ok) {
      throw new ApiError(`Не удалось получить журнал job (${response.status}).`, response.status)
    }
    return response.text()
  },

  alignments(jobId: string): Promise<AlignmentResponse> {
    return request<AlignmentResponse>(`/jobs/${encodeURIComponent(jobId)}/alignments`)
  },

  exclusions(jobId: string): Promise<JobReport> {
    return request<JobReport>(`/jobs/${encodeURIComponent(jobId)}/exclusions`)
  },

  report(jobId: string): Promise<JobReport> {
    return request<JobReport>(`/jobs/${encodeURIComponent(jobId)}/report`)
  },

  alignmentDownloadUrl(jobId: string, filename: 'vheavy.aln' | 'vkappa.aln' | 'vlambda.aln'): string {
    return `/api/jobs/${encodeURIComponent(jobId)}/alignments/${encodeURIComponent(filename)}`
  },

  reportDownloadUrl(jobId: string): string {
    return `/api/jobs/${encodeURIComponent(jobId)}/report`
  },

  anarciDownloadUrl(jobId: string, filename: string): string {
    return `/api/jobs/${encodeURIComponent(jobId)}/anarci/${encodeURIComponent(filename)}`
  },
}
