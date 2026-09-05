import { Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { ApiError, api, type Job } from '../api/client'

type Props = { job: Job; onUpdate: (job: Job) => void }
const terminalStatuses = new Set(['done', 'partial', 'failed'])
const POLL_INTERVAL_MS = 1500

export function JobStatus({ job: initialJob, onUpdate }: Props) {
  const [job, setJob] = useState(initialJob)
  const [log, setLog] = useState('')
  const [error, setError] = useState<string>()
  const logRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)

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
    const timer = window.setInterval(() => { void refresh() }, POLL_INTERVAL_MS)
    return () => { active = false; window.clearInterval(timer) }
  }, [initialJob.id, initialJob.status, onUpdate])

  // Автопрокрутка лога вниз при обновлении, если пользователь не прокрутил вверх.
  useEffect(() => {
    const element = logRef.current
    if (element && stickToBottomRef.current) {
      element.scrollTop = element.scrollHeight
    }
  }, [log])

  const handleLogScroll = () => {
    const element = logRef.current
    if (!element) return
    stickToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24
  }

  const isLive = job.status === 'running' || job.status === 'queued'

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
          {job.status === 'running' && <CircularProgress size={20} />}
          <Typography component="h2" variant="h6">{job.name}</Typography>
          <Chip label={job.status} size="small" />
          {isLive && (
            <Chip
              size="small"
              color="primary"
              variant="outlined"
              label="обновляется"
              sx={{ ml: 'auto' }}
            />
          )}
        </Box>
        {job.failure_reason && <Alert severity="error">{job.failure_reason}</Alert>}
        {error && <Alert severity="warning">{error}</Alert>}
        <Typography color="text.secondary">
          Найдено файлов: {job.counts?.files_found ?? 0}; последовательностей: {job.counts?.sequences ?? 0}.
        </Typography>
        <Divider />
        <Typography component="h3" variant="subtitle1">Журнал выполнения</Typography>
        <Box
          ref={logRef}
          onScroll={handleLogScroll}
          component="pre"
          sx={{ m: 0, maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13, bgcolor: 'grey.50', border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5 }}
        >
          {log || 'Журнал пока пуст.'}
        </Box>
      </Stack>
    </Paper>
  )
}
