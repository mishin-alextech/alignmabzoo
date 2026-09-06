import { Alert, Box, Button, Container, Stack, Typography } from '@mui/material'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api, type Job } from './api/client'
import { FullscreenAlignmentViewer } from './components/FullscreenAlignmentViewer'
import { JobArchive } from './components/JobArchive'
import { JobResults } from './components/JobResults'
import { JobStatus } from './components/JobStatus'
import { JobWizard } from './components/JobWizard'

const activeStatuses = new Set(['queued', 'running'])

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [activeJobId, setActiveJobId] = useState<string>()
  const [locationSearch, setLocationSearch] = useState(() => window.location.search)
  const [error, setError] = useState<string>()

  const route = useMemo(() => new URLSearchParams(locationSearch), [locationSearch])
  const view = route.get('view')
  const selectedArchiveJobId = route.get('job') ?? undefined
  const selectedAlignmentGroupName = route.get('group') ?? undefined

  const navigate = useCallback((nextView?: 'archive' | 'alignment', jobId?: string) => {
    const nextRoute = new URLSearchParams()
    if (nextView) nextRoute.set('view', nextView)
    if (jobId) nextRoute.set('job', jobId)
    const nextSearch = nextRoute.toString()
    window.history.pushState({}, '', `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ''}`)
    setLocationSearch(window.location.search)
  }, [])

  const mergeJob = useCallback((nextJob: Job) => {
    setJobs((current) => [nextJob, ...current.filter((job) => job.id !== nextJob.id)])
    if (activeStatuses.has(nextJob.status)) setActiveJobId(nextJob.id)
  }, [])

  useEffect(() => {
    const handlePopState = () => setLocationSearch(window.location.search)
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    let active = true
    void api.jobs().then(
      (items) => {
        if (!active) return
        setJobs(items)
        setActiveJobId((current) => current ?? items.find((job) => activeStatuses.has(job.status))?.id)
      },
      (reason) => {
        if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить список job.')
      },
    )
    return () => { active = false }
  }, [])

  const currentJob = jobs.find((job) => job.id === activeJobId)
    ?? jobs.find((job) => activeStatuses.has(job.status))
  const selectedArchiveJob = jobs.find((job) => job.id === selectedArchiveJobId)

  const removeDeletedJobs = useCallback((deletedIds: string[]) => {
    const deletedSet = new Set(deletedIds)
    setJobs((current) => current.filter((job) => !deletedSet.has(job.id)))
    setActiveJobId((current) => (current && deletedSet.has(current) ? undefined : current))
    if (selectedArchiveJobId && deletedSet.has(selectedArchiveJobId)) navigate('archive')
  }, [navigate, selectedArchiveJobId])

  if (view === 'alignment' && selectedArchiveJobId) {
    return <FullscreenAlignmentViewer jobId={selectedArchiveJobId} groupName={selectedAlignmentGroupName} />
  }

  return (
    <Box component="main" sx={{ minHeight: '100vh', py: { xs: 3, sm: 6 } }}>
      <Container maxWidth="lg">
        <Stack spacing={3}>
          <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={2} flexWrap="wrap">
            <Box>
              <Typography component="h1" variant="h3" gutterBottom>AlignMabZoo</Typography>
              <Typography color="text.secondary" variant="h6">Выравнивание и аннотация последовательностей моноклональных антител</Typography>
            </Box>
            <Button
              onClick={() => navigate(view === 'archive' ? undefined : 'archive')}
              variant="outlined"
            >
              {view === 'archive' ? 'Новая задача' : 'Архив задач'}
            </Button>
          </Box>
          {error && <Alert severity="warning" onClose={() => setError(undefined)}>{error}</Alert>}
          {view === 'archive' ? (
            <JobArchive
              jobs={jobs}
              selectedJob={selectedArchiveJob}
              onSelect={(job) => navigate('archive', job.id)}
              onDeleted={removeDeletedJobs}
            />
          ) : (
            <>
              <JobWizard onCreated={mergeJob} />
              {currentJob && <JobStatus job={currentJob} onUpdate={mergeJob} />}
              {currentJob && <JobResults jobId={currentJob.id} status={currentJob.status} />}
            </>
          )}
        </Stack>
      </Container>
    </Box>
  )
}

export default App
