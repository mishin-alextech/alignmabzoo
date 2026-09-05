import { Alert, Box, CircularProgress, Divider, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { ApiError, api, type JobReport, type ReportEntry } from '../api/client'

type Props = { jobId: string }

function Entries({ title, entries, severity }: { title: string; entries: ReportEntry[]; severity?: 'error' | 'warning' }) {
  if (entries.length === 0) return null
  return (
    <Box>
      <Typography variant="subtitle2">{title}: {entries.length}</Typography>
      <Stack spacing={0.5} sx={{ mt: 0.5, maxHeight: 150, overflow: 'auto' }}>
        {entries.map((entry, index) => severity
          ? <Alert key={`${entry.path ?? 'file'}-${index}`} severity={severity} sx={{ py: 0 }}>{entry.path ?? 'Файл без пути'}{entry.reason ? `: ${entry.reason}` : ''}</Alert>
          : <Typography key={`${entry.path ?? 'file'}-${index}`} variant="body2">{entry.path ?? 'Файл без пути'}{entry.reason ? `: ${entry.reason}` : ''}</Typography>)}
      </Stack>
    </Box>
  )
}

export function AlignmentExclusions({ jobId }: Props) {
  const [report, setReport] = useState<JobReport>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    let active = true
    setReport(undefined)
    setError(undefined)
    void api.exclusions(jobId).then(
      (response) => { if (active) setReport(response) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить отчёт.') },
    )
    return () => { active = false }
  }, [jobId])

  if (error) return <Alert severity="warning">{error}</Alert>
  if (!report) return <Paper variant="outlined" sx={{ p: 2 }}><CircularProgress size={22} /></Paper>
  const processed = report.processed ?? []
  const skipped = report.skipped ?? []
  const clustaloExclusions = report.clustalo_exclusions ?? []
  const errors = report.errors ?? []
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography component="h3" variant="h6" gutterBottom>Отчёт по входным файлам</Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mb: 1 }}>Обработано: {processed.length}; пропущено: {skipped.length + clustaloExclusions.length}; ошибок: {errors.length}.</Typography>
      <Stack spacing={1.5}>
        <Entries title="Обработанные файлы" entries={processed} />
        <Divider />
        <Entries title="Пропущенные файлы" entries={skipped} severity="warning" />
        <Entries title="Не прошедшие Clustal Omega" entries={clustaloExclusions} severity="warning" />
        <Entries title="Файлы с ошибками" entries={errors} severity="error" />
      </Stack>
    </Paper>
  )
}
