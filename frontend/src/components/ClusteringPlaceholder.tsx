import { Box, Button, Checkbox, FormControlLabel, Paper, Stack, TextField, Typography } from '@mui/material'
import { useState } from 'react'

type Props = { jobId: string }

export function ClusteringPlaceholder({ jobId }: Props) {
  const [minSeqId, setMinSeqId] = useState('0.90')
  const [coverage, setCoverage] = useState('0.90')
  const [reassign, setReassign] = useState(true)

  return (
    <Box sx={{ minHeight: '100vh', p: { xs: 2, sm: 4 } }}>
      <Paper variant="outlined" sx={{ maxWidth: 720, mx: 'auto', p: { xs: 2, sm: 4 } }}>
        <Stack spacing={2}>
          <Typography component="h1" variant="h4">Кластеризация</Typography>
          <Typography color="text.secondary">Параметры кластеризации MMseqs2 для job {jobId}.</Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField fullWidth size="small" label="Минимальная идентичность" value={minSeqId} onChange={(event) => setMinSeqId(event.target.value)} inputProps={{ inputMode: 'decimal' }} />
            <TextField fullWidth size="small" label="Покрытие" value={coverage} onChange={(event) => setCoverage(event.target.value)} inputProps={{ inputMode: 'decimal' }} />
          </Stack>
          <FormControlLabel control={<Checkbox checked={reassign} disabled onChange={(event) => setReassign(event.target.checked)} />} label="Переназначение участников включено" />
          <Typography variant="body2" color="text.secondary">Служебные параметры: cov-mode 0, cluster-mode 0 (greedy set cover), один поток.</Typography>
          <Typography variant="body2" color="text.secondary">Поток MMseqs2 и сохранение результатов будут подключены после закрепления версии инструмента и проверки Docker-образа.</Typography>
          <Button component="a" href={`?view=alignment&job=${encodeURIComponent(jobId)}`} variant="contained">Вернуться к выравниванию</Button>
        </Stack>
      </Paper>
    </Box>
  )
}