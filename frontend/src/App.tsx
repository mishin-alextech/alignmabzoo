import { Alert, Box, Container, Stack, Typography } from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, type Job } from './api/client'
import { JobList } from './components/JobList'
import { JobResults } from './components/JobResults'
import { JobStatus } from './components/JobStatus'
import { JobWizard } from './components/JobWizard'

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedJob, setSelectedJob] = useState<Job>()
  const [error, setError] = useState<string>()

  const mergeJob = useCallback((nextJob: Job) => {
    setJobs((current) => [nextJob, ...current.filter((job) => job.id !== nextJob.id)])
    setSelectedJob((current) => current?.id === nextJob.id ? nextJob : current)
  }, [])

  useEffect(() => {
    let active = true
    void api.jobs().then(
      (items) => { if (active) setJobs(items) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить список job.') },
    )
    return () => { active = false }
  }, [])

  return (
    <Box component="main" sx={{ minHeight: '100vh', py: { xs: 3, sm: 6 } }}>
      <Container maxWidth="lg">
        <Stack spacing={3}>
          <Box>
            <Typography component="h1" variant="h3" gutterBottom>AlignMabZoo</Typography>
            <Typography color="text.secondary" variant="h6">Выравнивание и аннотация последовательностей моноклональных антител</Typography>
          </Box>
          {error && <Alert severity="warning" onClose={() => setError(undefined)}>{error}</Alert>}
          <JobWizard onCreated={mergeJob} />
          <JobList jobs={jobs} selectedJobId={selectedJob?.id} onSelect={setSelectedJob} />
          {selectedJob && <JobStatus job={selectedJob} onUpdate={mergeJob} />}
          {selectedJob && <JobResults jobId={selectedJob.id} status={selectedJob.status} />}
        </Stack>
      </Container>
    </Box>
  )
}

export default App
