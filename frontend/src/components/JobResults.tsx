import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { ApiError, api, type AlignmentResponse, type CdrScheme } from '../api/client'
import { AlignmentExclusions } from './AlignmentExclusions'
import { AlignmentViewer } from './AlignmentViewer'

type Props = { jobId: string; status: string }
const schemes: CdrScheme[] = ['imgt', 'kabat', 'chothia']
const alignmentFiles: Array<{ filename: 'vheavy.aln' | 'vkappa.aln' | 'vlambda.aln'; label: string }> = [
  { filename: 'vheavy.aln', label: 'Скачать VHeavy и VHH' },
  { filename: 'vkappa.aln', label: 'Скачать VKappa' },
  { filename: 'vlambda.aln', label: 'Скачать VLambda' },
]

export function JobResults({ jobId, status }: Props) {
  const [alignment, setAlignment] = useState<AlignmentResponse>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    if (status !== 'done' && status !== 'partial') return
    let active = true
    void api.alignments(jobId).then(
      (response) => { if (active) setAlignment(response) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось определить доступные CSV-файлы.') },
    )
    return () => { active = false }
  }, [jobId, status])

  const csvFiles = schemes.map((scheme) => `${scheme}.csv`)
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
        {csvFiles.length > 0 && <Box><Typography variant="subtitle1" gutterBottom>CSV нумерации ANARCI</Typography><Box display="flex" gap={1} flexWrap="wrap">{csvFiles.map((filename) => <Button key={filename} component="a" href={api.anarciDownloadUrl(jobId, filename)} size="small" variant="text">{filename}</Button>)}</Box></Box>}
        <AlignmentViewer jobId={jobId} />
        <AlignmentExclusions jobId={jobId} />
      </Stack>
    </Paper>
  )
}
