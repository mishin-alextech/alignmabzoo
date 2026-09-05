import { Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { ApiError, api, type Job } from '../api/client'

type Props = { job: Job; onUpdate: (job: Job) => void }
const terminalStatuses = new Set(['done', 'partial', 'failed'])

export function JobStatus({ job: initialJob, onUpdate }: Props) {
  const [job, setJob] = useState(initialJob)
  const [log, setLog] = useState('')
  const [error, setError] = useState<string>()

  useEffect(() => setJob(initialJob), [initialJob])

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const [nextJob, nextLog] = await Promise.all([api.job(initialJob.id), api.log(initialJob.id)])
        if (!active) return
        setJob(nextJob)
        setLog(nextLog)
        setError(undefined)
        onUpdate(nextJob)
      } catch (reason) {
        if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось обновить статус job.')
      }
    }
    void refresh()
    if (terminalStatuses.has(initialJob.status)) return () => { active = false }
    const timer = window.setInterval(() => { void refresh() }, 3000)
    return () => { active = false; window.clearInterval(timer) }
  }, [initialJob.id, initialJob.status, onUpdate])

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Box display="flex" alignItems="center" gap={1}>
          {job.status === 'running' && <CircularProgress size={20} />}
          <Typography component="h2" variant="h6">{job.name}</Typography>
          <Chip label={job.status} size="small" />
        </Box>
        {job.failure_reason && <Alert severity="error">{job.failure_reason}</Alert>}
        {error && <Alert severity="warning">{error}</Alert>}
        <Typography color="text.secondary">
          Найдено файлов: {job.counts?.files_found ?? 0}; последовательностей: {job.counts?.sequences ?? 0}.
        </Typography>
        <Divider />
        <Typography component="h3" variant="subtitle1">Журнал выполнения</Typography>
        <Box component="pre" sx={{ m: 0, maxHeight: 260, overflow: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13 }}>
          {log || 'Журнал пока пуст.'}
        </Box>
      </Stack>
    </Paper>
  )
}
