import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { ApiError, api, type AlignmentResponse } from '../api/client'
import { AlignmentExclusions } from './AlignmentExclusions'
import { AlignmentViewer } from './AlignmentViewer'

type Props = { jobId: string; status: string }
const anarciBatches = [
  { name: 'vheavy', label: 'VHeavy и VHH' },
  { name: 'vkappa', label: 'VKappa' },
  { name: 'vlambda', label: 'VLambda' },
  { name: 'other', label: 'Other' },
] as const
const anarciBatchLabels: Record<string, string> = Object.fromEntries(
  anarciBatches.map(({ name, label }) => [name, label]),
)

function anarciCsvLabel(filename: string): string {
  const [scheme, batch] = filename.replace(/\.csv$/, '').split('_', 2)
  return `${scheme}.csv — ${anarciBatchLabels[batch] ?? batch}`
}
const alignmentFiles: Array<{ filename: 'vheavy.aln' | 'vkappa.aln' | 'vlambda.aln'; label: string }> = [
  { filename: 'vheavy.aln', label: 'Скачать VHeavy и VHH' },
  { filename: 'vkappa.aln', label: 'Скачать VKappa' },
  { filename: 'vlambda.aln', label: 'Скачать VLambda' },
]

export function JobResults({ jobId, status }: Props) {
  const [alignment, setAlignment] = useState<AlignmentResponse>()
  const [error, setError] = useState<string>()
  const [csvFiles, setCsvFiles] = useState<string[]>([])

  useEffect(() => {
    if (status !== 'done' && status !== 'partial') return
    let active = true
    void api.alignments(jobId).then(
      (response) => { if (active) setAlignment(response) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось определить доступные CSV-файлы.') },
    )
    return () => { active = false }
  }, [jobId, status])

  useEffect(() => {
    if (status !== 'done' && status !== 'partial') return
    const controller = new AbortController()
    void fetch(`/api/jobs/${encodeURIComponent(jobId)}/anarci`, { signal: controller.signal })
      .then(async (response) => response.ok ? response.json() as Promise<{ files?: unknown }> : { files: [] })
      .then((response) => {
        if (!controller.signal.aborted) {
          setCsvFiles(Array.isArray(response.files) ? response.files.filter((file): file is string => typeof file === 'string') : [])
        }
      })
      .catch(() => { if (!controller.signal.aborted) setCsvFiles([]) })
    return () => controller.abort()
  }, [jobId, status])

  if (status !== 'done' && status !== 'partial') return null

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Typography component="h2" variant="h5">Результаты выравнивания</Typography>
        {status === 'partial' && <Alert severity="warning">Job завершена с ошибками отдельных файлов; смотрите отчёт ниже.</Alert>}
        {error && <Alert severity="warning">{error}</Alert>}
        <Box display="flex" gap={1} flexWrap="wrap">
          {alignmentFiles.map(({ filename, label }) => <Button key={filename} component="a" href={api.alignmentDownloadUrl(jobId, filename)} variant="outlined">{label}</Button>)}
          <Button component="a" href={api.reportDownloadUrl(jobId)} variant="outlined">Скачать report.json</Button>
        </Box>
        {csvFiles.length > 0 && <Box><Typography variant="subtitle1" gutterBottom>CSV нумерации ANARCI</Typography><Box display="flex" gap={1} flexWrap="wrap">{csvFiles.map((filename) => <Button key={filename} component="a" href={api.anarciDownloadUrl(jobId, filename)} size="small" variant="text">{anarciCsvLabel(filename)}</Button>)}</Box></Box>}
        <AlignmentViewer jobId={jobId} />
        <AlignmentExclusions jobId={jobId} />
      </Stack>
    </Paper>
  )
}
