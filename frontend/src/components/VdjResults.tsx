import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, CircularProgress, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, type AlignmentSequence, type Job, type VdjCall, type VdjRecord, type VdjResult } from '../api/client'

type Props = { jobId: string }
type SequenceContext = { sequence: AlignmentSequence; chainGroup: string }

const activeStatuses = new Set(['queued', 'running'])

function recordStatus(status: string): string {
  return ({ ready: 'Готово', unavailable: 'Недоступно', failed: 'Ошибка', ambiguous: 'Несколько назначений' }[status] ?? status)
}

function sourceLabel(sequence?: AlignmentSequence): string {
  if (!sequence?.source) return 'Неизвестная группа / неизвестный клон'
  return `${sequence.source.group} / ${sequence.name}`
}

function callLabel(call: VdjCall | string): string {
  if (typeof call === 'string') return call
  return call.allele ?? call.gene ?? 'Не определено'
}

function metric(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return '—'
  return Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function Calls({ label, calls }: { label: string; calls?: Array<VdjCall | string> }) {
  if (!calls?.length) return null
  return <Typography variant="body2"><strong>{label}:</strong> {calls.map(callLabel).join(', ')}</Typography>
}

function RecordDetails({ record }: { record: VdjRecord }) {
  if (record.status === 'unavailable' || record.status === 'failed') {
    return <Typography color="text.secondary">{record.reason || 'Причина не указана.'}</Typography>
  }
  const metrics = record.metrics
  return (
    <Stack spacing={0.5}>
      {record.reason && <Alert severity="info">{record.reason}</Alert>}
      <Calls label="V" calls={record.v_calls} />
      <Calls label="D" calls={record.d_calls} />
      <Calls label="J" calls={record.j_calls} />
      <Typography variant="body2"><strong>Локус:</strong> {record.locus || '—'}</Typography>
      <Typography variant="body2"><strong>Junction, нуклеотиды:</strong> {record.junction?.nt || '—'}</Typography>
      <Typography variant="body2"><strong>Junction, аминокислоты:</strong> {record.junction?.aa || '—'}</Typography>
      <Typography variant="body2"><strong>Идентичность:</strong> {metric(metrics?.identity)} · <strong>Покрытие:</strong> {metric(metrics?.coverage)} · <strong>Длина:</strong> {metrics?.alignment_length ?? '—'}</Typography>
      <Typography variant="body2"><strong>Score:</strong> {metric(metrics?.score)} · <strong>E-value:</strong> {metric(metrics?.evalue)}</Typography>
      {record.profile_id && <Typography variant="body2"><strong>Профиль:</strong> {record.profile_id}</Typography>}
      {record.tool_version && <Typography variant="body2"><strong>IgBLAST:</strong> {record.tool_version}</Typography>}
    </Stack>
  )
}

/** Самостоятельная вкладка результата Germline; белковые последовательности здесь намеренно не выводятся. */
export function VdjResults({ jobId }: Props) {
  const [job, setJob] = useState<Job>()
  const [result, setResult] = useState<VdjResult>()
  const [sequences, setSequences] = useState<Map<string, SequenceContext>>(new Map())
  const [error, setError] = useState<string>()

  useEffect(() => {
    let active = true
    let timer: number | undefined
    const load = async () => {
      try {
        const current = await api.job(jobId)
        if (!active) return
        setJob(current)
        if (activeStatuses.has(current.status)) {
          timer = window.setTimeout(() => void load(), 1000)
          return
        }
        const [nextResult, parentAlignment] = await Promise.all([
          api.vdjResults(jobId),
          current.parent_job_id ? api.alignments(current.parent_job_id) : Promise.resolve(undefined),
        ])
        if (!active) return
        setResult(nextResult)
        const byId = new Map<string, SequenceContext>()
        parentAlignment?.groups?.forEach((group) => group.sequences.forEach((sequence) => {
          if (sequence.id) byId.set(sequence.id, { sequence, chainGroup: group.name })
        }))
        setSequences(byId)
      } catch (reason) {
        if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось получить результат V(D)J-анализа.')
      }
    }
    void load()
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer) }
  }, [jobId])

  const title = useMemo(() => job?.name ? `Germline: ${job.name}` : 'Germline-анализ', [job?.name])
  if (error) return <Box component="main" sx={{ p: 3 }}><Alert severity="warning">{error}</Alert></Box>
  if (!job || activeStatuses.has(job.status)) {
    return <Box component="main" sx={{ p: 3, textAlign: 'center' }}><CircularProgress size={28} /><Typography sx={{ mt: 1 }}>V(D)J-анализ выполняется…</Typography></Box>
  }
  if (job.status !== 'done' && job.status !== 'partial') {
    return <Box component="main" sx={{ p: 3 }}><Alert severity="warning">{job.failure_reason || 'V(D)J-анализ завершился с ошибкой.'}</Alert></Box>
  }
  if (!result) return <Box component="main" sx={{ p: 3, textAlign: 'center' }}><CircularProgress size={28} /></Box>

  return (
    <Box component="main" sx={{ minHeight: '100vh', p: { xs: 2, sm: 4 } }}>
      <Stack spacing={2} maxWidth="lg" mx="auto">
        <Box>
          <Typography component="h1" variant="h4">{title}</Typography>
          <Typography color="text.secondary">IMGT / IgBLAST. Выбранные клоны анализируются независимо; исходное выравнивание не изменено.</Typography>
        </Box>
        {job.status === 'partial' && <Alert severity="info">Часть записей не обработана. Причины указаны в строках.</Alert>}
        <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead><TableRow><TableCell>Группа / клон</TableCell><TableCell>Цепь</TableCell><TableCell>Животное / профиль</TableCell><TableCell>Статус</TableCell></TableRow></TableHead>
            <TableBody>
              {result.records.map((record) => {
                const context = sequences.get(record.sequence_id)
                const sequence = context?.sequence
                return <TableRow key={record.sequence_id} hover>
                  <TableCell colSpan={4} sx={{ p: 0 }}>
                    <Accordion disableGutters elevation={0} square>
                      <AccordionSummary expandIcon={<span aria-hidden="true">⌄</span>}>
                        <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '2fr 1fr 1fr 1fr' }} gap={1} width="100%" alignItems="center">
                          <Typography>{sourceLabel(sequence)}</Typography>
                          <Typography>{context?.chainGroup ?? '—'}</Typography>
                          <Typography>{sequence?.source?.animal ?? '—'}{record.profile_id ? ` / ${record.profile_id}` : ''}</Typography>
                          <Typography>{recordStatus(record.status)}</Typography>
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails><RecordDetails record={record} /></AccordionDetails>
                    </Accordion>
                  </TableCell>
                </TableRow>
              })}
            </TableBody>
          </Table>
        </Paper>
        {result.records.length === 0 && <Alert severity="info">В этой задаче нет записей для V(D)J-анализа.</Alert>}
        <Box display="flex" gap={1} flexWrap="wrap">
          {result.records.some((record) => record.status === 'ready' || record.status === 'ambiguous') && <Button component="a" href={api.vdjTsvDownloadUrl(jobId)} variant="outlined">Скачать TSV</Button>}
          <Button component="a" href={api.vdjManifestDownloadUrl(jobId)} variant="outlined">Скачать manifest</Button>
        </Box>
      </Stack>
    </Box>
  )
}
