import { Alert, Button, Stack, Typography } from '@mui/material'
import { useState } from 'react'
import { ApiError, api, type Job } from '../api/client'
import { JobList } from './JobList'
import { JobResults } from './JobResults'

type Props = {
  jobs: Job[]
  selectedJob?: Job
  onSelect: (job: Job) => void
  onDeleted: (jobIds: string[]) => void
}

const terminalStatuses = new Set(['done', 'partial', 'failed'])

export function JobArchive({ jobs, selectedJob, onSelect, onDeleted }: Props) {
  const archivedJobs = jobs.filter((job) => terminalStatuses.has(job.status))
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string>()
  const [isDeleting, setIsDeleting] = useState(false)

  const toggleSelection = (job: Job) => {
    setSelectedJobIds((current) => {
      const next = new Set(current)
      if (next.has(job.id)) next.delete(job.id)
      else next.add(job.id)
      return next
    })
  }

  const deleteSelected = async () => {
    const jobIds = [...selectedJobIds]
    if (!jobIds.length) return
    setError(undefined)
    setIsDeleting(true)
    try {
      const deletedIds = await api.deleteJobs(jobIds)
      setSelectedJobIds((current) => new Set([...current].filter((jobId) => !deletedIds.includes(jobId))))
      onDeleted(deletedIds)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Не удалось удалить выбранные задачи.')
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <Stack spacing={3}>
      <Typography component="h1" variant="h4">Архив задач</Typography>
      {error && <Alert severity="warning" onClose={() => setError(undefined)}>{error}</Alert>}
      <Stack direction="row" justifyContent="flex-end">
        <Button
          color="error"
          disabled={selectedJobIds.size === 0 || isDeleting}
          onClick={() => void deleteSelected()}
          variant="outlined"
        >
          Удалить задачи
        </Button>
      </Stack>
      <JobList
        jobs={archivedJobs}
        selectedJobId={selectedJob?.id}
        onSelect={onSelect}
        onToggleSelection={toggleSelection}
        selectedJobIds={selectedJobIds}
        title="Завершённые задачи"
      />
      {selectedJob && <JobResults jobId={selectedJob.id} status={selectedJob.status} />}
    </Stack>
  )
}
