import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material'
import { api } from '../api/client'
import { AlignmentExclusions } from './AlignmentExclusions'
import { AlignmentViewer } from './AlignmentViewer'

type Props = { jobId: string; status: string }
const alignmentFiles: Array<{ filename: 'vheavy.aln' | 'vkappa.aln' | 'vlambda.aln'; label: string }> = [
  { filename: 'vheavy.aln', label: 'Скачать VHeavy и VHH' },
  { filename: 'vkappa.aln', label: 'Скачать VKappa' },
  { filename: 'vlambda.aln', label: 'Скачать VLambda' },
]

export function JobResults({ jobId, status }: Props) {

  if (status !== 'done' && status !== 'partial') return null

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Typography component="h2" variant="h5">Результаты выравнивания</Typography>
        {status === 'partial' && <Alert severity="warning">Job завершена с ошибками отдельных файлов; смотрите отчёт ниже.</Alert>}
        <Box display="flex" gap={1} flexWrap="wrap">
          {alignmentFiles.map(({ filename, label }) => <Button key={filename} component="a" href={api.alignmentDownloadUrl(jobId, filename)} variant="outlined">{label}</Button>)}
        </Box>
        <AlignmentViewer jobId={jobId} />
        <AlignmentExclusions jobId={jobId} />
      </Stack>
    </Paper>
  )
}
