import { Chip, List, ListItemButton, ListItemText, Paper, Typography } from '@mui/material'
import type { Job } from '../api/client'

type Props = {
  jobs: Job[]
  selectedJobId?: string
  onSelect: (job: Job) => void
  title?: string
}

const statusLabel: Record<string, string> = {
  queued: 'В очереди',
  running: 'Выполняется',
  done: 'Готово',
  partial: 'Готово с ошибками',
  failed: 'Ошибка',
}

const statusColor = (status: string): 'default' | 'primary' | 'success' | 'warning' | 'error' => {
  if (status === 'running') return 'primary'
  if (status === 'done') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'failed') return 'error'
  return 'default'
}

export function JobList({ jobs, selectedJobId, onSelect, title = 'Задачи' }: Props) {
  return (
    <Paper elevation={0} sx={{ p: 2 }}>
      <Typography component="h2" variant="h6" gutterBottom>{title}</Typography>
      {jobs.length === 0 ? (
        <Typography color="text.secondary">Созданных задач пока нет.</Typography>
      ) : (
        <List disablePadding>
          {jobs.map((job) => (
            <ListItemButton
              key={job.id}
              selected={selectedJobId === job.id}
              onClick={() => onSelect(job)}
              sx={{ borderRadius: 1 }}
            >
              <ListItemText
                primary={job.name}
                secondary={`${new Date(job.created_at).toLocaleString('ru-RU')} · последовательностей: ${job.counts?.sequences ?? 0}`}
              />
              <Chip color={statusColor(job.status)} label={statusLabel[job.status] ?? job.status} size="small" />
            </ListItemButton>
          ))}
        </List>
      )}
    </Paper>
  )
}
