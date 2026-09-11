import { Alert, Paper, Stack, Typography } from '@mui/material'
import { AlignmentViewer } from './AlignmentViewer'

type Props = { jobId: string; status: string }

export function JobResults({ jobId, status }: Props) {

  if (status !== 'done' && status !== 'partial') return null

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Typography component="h2" variant="h5">Результаты выравнивания</Typography>
        {status === 'partial' && <Alert severity="warning">Job завершена с ошибками отдельных файлов; смотрите отчёт ниже.</Alert>}
        <AlignmentViewer key={jobId} jobId={jobId} />
      </Stack>
    </Paper>
  )
}
