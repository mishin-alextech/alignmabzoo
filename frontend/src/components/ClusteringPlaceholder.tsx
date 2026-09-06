import { Box, Button, Paper, Stack, Typography } from '@mui/material'

type Props = { jobId: string }

export function ClusteringPlaceholder({ jobId }: Props) {
  return (
    <Box sx={{ minHeight: '100vh', p: { xs: 2, sm: 4 } }}>
      <Paper variant="outlined" sx={{ maxWidth: 720, mx: 'auto', p: { xs: 2, sm: 4 } }}>
        <Stack spacing={2}>
          <Typography component="h1" variant="h4">Кластеризация</Typography>
          <Typography color="text.secondary">Кластеризация последовательностей будет доступна позже.</Typography>
          <Button component="a" href={`?view=alignment&job=${encodeURIComponent(jobId)}`} variant="contained">Вернуться к выравниванию</Button>
        </Stack>
      </Paper>
    </Box>
  )
}