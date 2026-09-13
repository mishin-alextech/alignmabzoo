import { Alert, Box, Button, Chip, CircularProgress, Collapse, Divider, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { ApiError, api, type Job } from '../api/client'

type Props = { job: Job; onUpdate: (job: Job) => void }
const terminalStatuses = new Set(['done', 'partial', 'failed'])
const POLL_INTERVAL_MS = 1500

export function JobStatus({ job: initialJob, onUpdate }: Props) {
  const [job, setJob] = useState(initialJob)
  const [log, setLog] = useState('')
  const [error, setError] = useState<string>()
  const [logError, setLogError] = useState<string>()
  const [isLogExpanded, setIsLogExpanded] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)

  useEffect(() => setJob(initialJob), [initialJob])
  useEffect(() => { setLog(''); setLogError(undefined); setError(undefined) }, [initialJob.id])

  useEffect(() => {
    let active = true
    let loadingStatus = false
    let loadingLog = false
    const refresh = async () => {
      if (loadingStatus) return
      loadingStatus = true
      try {
        const nextJob = await api.job(initialJob.id)
        if (!active) return
        setJob(nextJob)
        setError(undefined)
        onUpdate(nextJob)
      } catch (reason) {
        if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось обновить статус job.')
      } finally {
        loadingStatus = false
      }
    }
    const refreshLog = async () => {
      if (loadingLog) return
      loadingLog = true
      try {
        const nextLog = await api.log(initialJob.id)
        if (active) { setLog(nextLog); setLogError(undefined) }
      } catch (reason) {
        if (active) setLogError(reason instanceof ApiError && reason.status === 404
          ? 'Журнал этой job пока недоступен.'
          : reason instanceof ApiError ? reason.message : 'Не удалось обновить журнал job.')
      } finally {
        loadingLog = false
      }
    }
    void refresh()
    void refreshLog()
    if (terminalStatuses.has(initialJob.status)) return () => { active = false }
    const timer = window.setInterval(() => { void refresh(); void refreshLog() }, POLL_INTERVAL_MS)
    return () => { active = false; window.clearInterval(timer) }
  }, [initialJob.id, initialJob.status, onUpdate])

  useEffect(() => {
    const element = logRef.current
    if (isLogExpanded && element && stickToBottomRef.current) {
      element.scrollTop = element.scrollHeight
    }
  }, [isLogExpanded, log])

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
        {logError && <Alert severity="info">{logError}</Alert>}
        <Typography color="text.secondary">
          Найдено файлов: {job.counts?.files_found ?? 0}; последовательностей: {job.counts?.sequences ?? 0}.
        </Typography>
        <Divider />
        <Button
          aria-expanded={isLogExpanded}
          onClick={() => setIsLogExpanded((current) => !current)}
          sx={{ justifyContent: 'space-between', px: 0, color: 'text.primary', textTransform: 'none' }}
        >
          <Typography component="h3" variant="subtitle1">Журнал выполнения</Typography>
          <Box component="span" aria-hidden="true">{isLogExpanded ? '▴' : '▾'}</Box>
        </Button>
        <Collapse in={isLogExpanded}>
          <Box
            ref={logRef}
            onScroll={handleLogScroll}
            component="pre"
            sx={{ m: 0, maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13, bgcolor: 'grey.50', border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5 }}
          >
            {log || 'Журнал пока пуст.'}
          </Box>
        </Collapse>
      </Stack>
    </Paper>
  )
}
