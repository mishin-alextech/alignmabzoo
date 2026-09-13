import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, CircularProgress, Paper, Stack, Typography } from '@mui/material'
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

function evalue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value === 0) return '0'
  return value.toExponential(2)
}

function Calls({ label, calls }: { label: string; calls?: Array<VdjCall | string> }) {
  if (!calls?.length) return null
  return <Typography variant="body2"><strong>{label}:</strong> {calls.map(callLabel).join(', ')}</Typography>
}

function ReportBlock({ title, text }: { title: string; text?: string | null }) {
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{title}</Typography>
      {text ? (
        <Box
          component="pre"
          sx={{ bgcolor: 'grey.50', border: 1, borderColor: 'divider', borderRadius: 1, fontFamily: 'monospace', fontSize: '0.78rem', lineHeight: 1.45, m: 0, overflowX: 'auto', p: 1.5, whiteSpace: 'pre' }}
        >
          {text}
        </Box>
      ) : <Typography variant="body2" color="text.secondary">Данные не определены.</Typography>}
    </Box>
  )
}

function RecordDetails({ record, cloneName }: { record: VdjRecord; cloneName: string }) {
  if (record.status === 'unavailable' || record.status === 'failed') {
    return <Typography color="text.secondary">{record.reason || 'Причина не указана.'}</Typography>
  }
  const metrics = record.metrics
  const details = record.details
  return (
    <Stack spacing={2}>
      {record.reason && <Alert severity="info">{record.reason}</Alert>}
      <Box>
        <Typography variant="subtitle2">Query= {cloneName} &nbsp; Length={details?.query_length ?? '—'}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          V: {(record.v_calls ?? []).map(callLabel).join(', ') || '—'} · D: {(record.d_calls ?? []).map(callLabel).join(', ') || '—'} · J: {(record.j_calls ?? []).map(callLabel).join(', ') || '—'} · Score: {metric(metrics?.score)} · E-value: {evalue(metrics?.evalue)}
        </Typography>
      </Box>
      <ReportBlock title="Sequences producing significant alignments" text={details?.significant_alignments} />
      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Краткий результат</Typography>
        <Stack spacing={0.25}>
          <Calls label="V" calls={record.v_calls} />
          <Calls label="D" calls={record.d_calls} />
          <Calls label="J" calls={record.j_calls} />
          <Typography variant="body2"><strong>Локус:</strong> {record.locus || '—'}</Typography>
          <Typography variant="body2"><strong>Junction, нуклеотиды:</strong> {record.junction?.nt || '—'}</Typography>
          <Typography variant="body2"><strong>Junction, аминокислоты:</strong> {record.junction?.aa || '—'}</Typography>
          <Typography variant="body2"><strong>Идентичность:</strong> {metric(metrics?.identity)}% · <strong>Покрытие V:</strong> {metric(metrics?.coverage)}% · <strong>Длина V:</strong> {metrics?.alignment_length ?? '—'} нт · <strong>E-value:</strong> {evalue(metrics?.evalue)}</Typography>
          {record.profile_id && <Typography variant="body2"><strong>Профиль:</strong> {record.profile_id}</Typography>}
          {record.tool_version && <Typography variant="body2"><strong>IgBLAST:</strong> {record.tool_version}</Typography>}
        </Stack>
      </Box>
      <ReportBlock title="Alignments" text={details?.alignments} />
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
          <Box sx={{ minWidth: 880 }}>
            <Box display="grid" gridTemplateColumns="minmax(0, 2fr) repeat(3, minmax(0, 1fr)) 24px" gap={2} alignItems="center" px={2} py={1.5} borderBottom={1} borderColor="divider" bgcolor="grey.50">
              <Typography variant="subtitle2">Группа / клон</Typography>
              <Typography variant="subtitle2">Цепь</Typography>
              <Typography variant="subtitle2">Животное / профиль</Typography>
              <Typography variant="subtitle2">Статус</Typography>
              <span />
            </Box>
            {result.records.map((record) => {
              const context = sequences.get(record.sequence_id)
              const sequence = context?.sequence
              return <Accordion key={record.sequence_id} disableGutters elevation={0} square>
                <AccordionSummary
                  expandIcon={<span aria-hidden="true">⌄</span>}
                  sx={{ px: 2, '& .MuiAccordionSummary-content': { display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) repeat(3, minmax(0, 1fr))', gap: 2, my: 1.5 } }}
                >
                  <Typography>{sourceLabel(sequence)}</Typography>
                  <Typography>{context?.chainGroup ?? '—'}</Typography>
                  <Typography>{sequence?.source?.animal ?? '—'}{record.profile_id ? ` / ${record.profile_id}` : ''}</Typography>
                  <Typography>{recordStatus(record.status)}</Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ px: 2, pb: 2 }}><RecordDetails record={record} cloneName={sourceLabel(sequence)} /></AccordionDetails>
              </Accordion>
            })}
          </Box>
        </Paper>
        {result.records.length === 0 && <Alert severity="info">В этой задаче нет записей для V(D)J-анализа.</Alert>}
      </Stack>
    </Box>
  )
}
