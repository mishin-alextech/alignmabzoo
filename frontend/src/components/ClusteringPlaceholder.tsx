import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, FormControl, InputLabel, MenuItem, Paper, Select, Stack, TextField, Typography } from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, type AlignmentSequence, type CdrScheme, type ClusterResult, type ClusterScope } from '../api/client'

type Props = {
  jobId: string
  sequenceIds?: string[]
  onBack?: () => void
  onApplyOrder?: (order: string[]) => void
}

const pollingDelayMs = 1000

export function ClusteringPlaceholder({ jobId, sequenceIds, onBack, onApplyOrder }: Props) {
  const [scope, setScope] = useState<ClusterScope>('variable_domain')
  const [scheme, setScheme] = useState<CdrScheme>('imgt')
  const [minSeqId, setMinSeqId] = useState('0.90')
  const [coverage, setCoverage] = useState('0.90')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string>()
  const [result, setResult] = useState<ClusterResult>()
  const [availableIds, setAvailableIds] = useState<string[]>(sequenceIds ?? [])
  const [sequencesById, setSequencesById] = useState<Map<string, AlignmentSequence>>(new Map())
  const [loadingIds, setLoadingIds] = useState(sequenceIds === undefined)

  useEffect(() => {
    let active = true
    setLoadingIds(true)
    void api.alignments(jobId).then(
      (alignment) => {
        if (!active) return
        const sequences = (alignment.groups ?? []).flatMap((group) => group.sequences)
        setSequencesById(new Map(sequences.flatMap((sequence) => sequence.id ? [[sequence.id, sequence] as const] : [])))
        const ids = sequences.map((sequence) => sequence.id ?? '').filter((id) => id.startsWith('seq_'))
        setAvailableIds(sequenceIds === undefined ? ids : sequenceIds.filter((id) => ids.includes(id)))
      },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить выравнивание для кластеризации.') },
    ).finally(() => { if (active) setLoadingIds(false) })
    return () => { active = false }
  }, [jobId, sequenceIds])

  const clusterSections = useMemo(() => {
    if (!result) return []
    const sections = new Map<string, { clusters: ClusterResult['clusters']; singletonCount: number }>()
    result.clusters.forEach((cluster) => {
      const section = sections.get(cluster.chain_group) ?? { clusters: [], singletonCount: 0 }
      if (cluster.size > 1) section.clusters.push(cluster)
      else section.singletonCount += cluster.size
      sections.set(cluster.chain_group, section)
    })
    return [...sections.entries()].map(([chainGroup, section]) => ({ chainGroup, ...section }))
  }, [result])
  const visibleClusterNumbers = useMemo(() => new Map(
    clusterSections.flatMap((section) => section.clusters).map((cluster, index) => [cluster.id, index + 1]),
  ), [clusterSections])
  const clusterMemberLabel = (sequenceId: string) => {
    const sequence = sequencesById.get(sequenceId)
    if (!sequence) return `Неизвестная группа / ${sequenceId}`
    return `${sequence.source?.group ?? 'Неизвестная группа'} / ${sequence.name}`
  }

  const run = async () => {
    const identity = Number(minSeqId)
    const nextCoverage = Number(coverage)
    if (![0.8, 0.9, 0.95].includes(identity) || ![0.8, 0.9].includes(nextCoverage)) {
      setError('Допустимые пороги: идентичность 0.80, 0.90 или 0.95; покрытие 0.80 или 0.90.')
      return
    }
    if (availableIds.length === 0) {
      setError('В текущем варианте выравнивания нет последовательностей для кластеризации.')
      return
    }
    setRunning(true)
    setError(undefined)
    setResult(undefined)
    try {
      const created = await api.cluster(jobId, {
        sequenceIds: availableIds,
        scope,
        numberingScheme: scope === 'cdr3' ? scheme : undefined,
        minSeqId: identity,
        coverage: nextCoverage,
      })
      let status = created
      while (status.status === 'queued' || status.status === 'running') {
        await new Promise((resolve) => window.setTimeout(resolve, pollingDelayMs))
        status = await api.job(created.id)
      }
      if (status.status !== 'done' && status.status !== 'partial') {
        throw new ApiError(status.failure_reason || 'Кластеризация завершилась ошибкой.')
      }
      setResult(await api.clusters(created.id))
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Не удалось выполнить кластеризацию.')
    } finally {
      setRunning(false)
    }
  }

  const createClusterAlignment = async (cluster: ClusterResult['clusters'][number]) => {
    try {
      const job = await api.realign(jobId, cluster.sequence_ids)
      window.open(`?view=alignment&job=${encodeURIComponent(job.id)}`, '_blank', 'noopener,noreferrer')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Не удалось создать выравнивание кластера.')
    }
  }

  return (
    <Box sx={{ minHeight: '100vh', p: { xs: 2, sm: 4 } }}>
      <Paper variant="outlined" sx={{ maxWidth: 860, mx: 'auto', p: { xs: 2, sm: 4 } }}>
        <Stack spacing={2}>
          <Typography component="h1" variant="h4">Кластеризация</Typography>
          <Typography color="text.secondary">MMseqs2 группирует сохранённые последовательности. Инженерные пороги не являются биологическим выводом.</Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl fullWidth size="small">
              <InputLabel id="cluster-scope-label">Область сравнения</InputLabel>
              <Select labelId="cluster-scope-label" value={scope} label="Область сравнения" disabled={running} onChange={(event) => setScope(event.target.value as ClusterScope)}>
                <MenuItem value="variable_domain">Вариабельный домен</MenuItem>
                <MenuItem value="cdr3">CDR3</MenuItem>
              </Select>
            </FormControl>
            {scope === 'cdr3' && <FormControl fullWidth size="small">
              <InputLabel id="cluster-scheme-label">Схема CDR3</InputLabel>
              <Select labelId="cluster-scheme-label" value={scheme} label="Схема CDR3" disabled={running} onChange={(event) => setScheme(event.target.value as CdrScheme)}>
                <MenuItem value="imgt">IMGT</MenuItem>
                <MenuItem value="kabat">Kabat</MenuItem>
                <MenuItem value="chothia">Chothia</MenuItem>
              </Select>
            </FormControl>}
          </Stack>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField fullWidth size="small" label="Минимальная идентичность" value={minSeqId} disabled={running} onChange={(event) => setMinSeqId(event.target.value)} inputProps={{ inputMode: 'decimal' }} />
            <TextField fullWidth size="small" label="Покрытие" value={coverage} disabled={running} onChange={(event) => setCoverage(event.target.value)} inputProps={{ inputMode: 'decimal' }} />
          </Stack>
          <Typography variant="body2" color="text.secondary">Режим: easy-cluster, set cover с reassignment, покрытие обеих последовательностей, один поток.</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Button variant="contained" disabled={running || loadingIds} onClick={() => void run()}>{running ? 'Выполняется…' : loadingIds ? 'Загрузка…' : 'Кластеризовать'}</Button>
            {onBack
              ? <Button onClick={onBack} disabled={running}>Вернуться к выравниванию</Button>
              : <Button component="a" href={`?view=alignment&job=${encodeURIComponent(jobId)}`} disabled={running}>Вернуться к выравниванию</Button>}
          </Stack>
          {error && <Alert severity="warning">{error}</Alert>}
          {result && <Stack spacing={1}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
              <Typography>Кластеров из нескольких последовательностей: {visibleClusterNumbers.size}; вне расчёта: {result.unclustered.length}.</Typography>
              {onApplyOrder && <Button size="small" variant="outlined" onClick={() => onApplyOrder(result.order)}>Расположить строки блоками кластеров</Button>}
            </Stack>
            {result.unclustered.length > 0 && <Alert severity="info">Не вошли в расчёт: {result.unclustered.length} последовательностей.</Alert>}
            {clusterSections.map((section) => <Stack key={section.chainGroup} spacing={1}>
              {section.clusters.map((cluster) => <Accordion key={cluster.id} variant="outlined" disableGutters>
                <AccordionSummary>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} gap={1} width="100%" mr={1}>
                    <Typography>Кластер №{visibleClusterNumbers.get(cluster.id)} · {cluster.chain_group}: {cluster.size} последовательностей</Typography>
                    <Button size="small" variant="outlined" onClick={(event) => { event.stopPropagation(); void createClusterAlignment(cluster) }}>Выровнять кластер</Button>
                  </Stack>
                </AccordionSummary>
                <AccordionDetails>
                  <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
                    {cluster.sequence_ids.map((sequenceId) => <Typography component="li" key={sequenceId}>{clusterMemberLabel(sequenceId)}</Typography>)}
                  </Stack>
                </AccordionDetails>
              </Accordion>)}
              {section.singletonCount > 0 && <Typography variant="body2" color="text.secondary">{section.chainGroup}: не попали в кластеры: {section.singletonCount} последовательностей.</Typography>}
            </Stack>)}
          </Stack>}
        </Stack>
      </Paper>
    </Box>
  )
}
