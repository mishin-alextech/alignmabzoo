import { Stack, Typography } from '@mui/material'
import type { Job } from '../api/client'
import { JobList } from './JobList'
import { JobResults } from './JobResults'

type Props = {
  jobs: Job[]
  selectedJob?: Job
  onSelect: (job: Job) => void
}

const terminalStatuses = new Set(['done', 'partial', 'failed'])

export function JobArchive({ jobs, selectedJob, onSelect }: Props) {
  const archivedJobs = jobs.filter((job) => terminalStatuses.has(job.status))

  return (
    <Stack spacing={3}>
      <Typography component="h1" variant="h4">Архив задач</Typography>
      <JobList
        jobs={archivedJobs}
        selectedJobId={selectedJob?.id}
        onSelect={onSelect}
        title="Завершённые задачи"
      />
      {selectedJob && <JobResults jobId={selectedJob.id} status={selectedJob.status} />}
    </Stack>
  )
}
