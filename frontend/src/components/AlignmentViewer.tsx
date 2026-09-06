import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, ButtonGroup, Checkbox, CircularProgress, FormControl, IconButton, InputLabel, MenuItem, Paper, Select, Stack, SvgIcon, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import { useEffect, useMemo, useReducer, useState } from 'react'
import { ApiError, api, type AlignmentGroup, type AlignmentResponse, type AlignmentSequence, type CdrScheme } from '../api/client'
import { formatResidueFrequency } from './alignment/columnStatistics'
import { createViewerState, orderedViewerGroups, viewerReducer, type ViewerGroup, type ViewerSequence } from './alignment/viewerState'

type Props = {
  jobId: string
  fullScreen?: boolean
  groupName?: string
}

type ConsensusColumn = {
  residue: string | null
  matches: boolean[]
}

const schemes: Array<{ value: CdrScheme; label: string; color: string }> = [
  { value: 'imgt', label: 'IMGT', color: '#a5d6a7' },
  { value: 'kabat', label: 'Kabat', color: '#ef9a9a' },
  { value: 'chothia', label: 'Chothia', color: '#90caf9' },
]
const consensusThresholds = [50, 60, 70, 75, 80, 90, 95]
const groupOrder = ['VHeavy', 'VHH', 'VKappa', 'VLambda', 'Other']
const zappoColors: Record<string, string> = {
  I: '#ffafaf', L: '#ffafaf', V: '#ffafaf', A: '#ffafaf', M: '#ffafaf',
  F: '#ffc800', W: '#ffc800', Y: '#ffc800',
  K: '#6464ff', R: '#6464ff', H: '#6464ff',
  D: '#ff0000', E: '#ff0000',
  S: '#00ff00', T: '#00ff00', N: '#00ff00', Q: '#00ff00',
  P: '#ff00ff', G: '#ff00ff', C: '#ffff00',
}
const aminoAcidNames: Record<string, string> = {
  A: 'Аланин', R: 'Аргинин', N: 'Аспарагин', D: 'Аспарагиновая кислота',
  C: 'Цистеин', Q: 'Глутамин', E: 'Глутаминовая кислота', G: 'Глицин',
  H: 'Гистидин', I: 'Изолейцин', L: 'Лейцин', K: 'Лизин', M: 'Метионин',
  F: 'Фенилаланин', P: 'Пролин', S: 'Серин', T: 'Треонин', W: 'Триптофан',
  Y: 'Тирозин', V: 'Валин',
}

function cdrIndexes(sequence: AlignmentSequence, scheme: CdrScheme): Set<number> {
  const cdr = sequence.cdr?.[scheme]
  return new Set([...(cdr?.cdr1 ?? []), ...(cdr?.cdr2 ?? []), ...(cdr?.cdr3 ?? [])])
}

export function calculateConsensus(group: AlignmentGroup, threshold: number): ConsensusColumn[] {
  const length = Math.max(0, ...group.sequences.map((sequence) => sequence.seq.length))
  return Array.from({ length }, (_, index) => {
    const counts = new Map<string, number>()
    let nonGapCount = 0
    for (const sequence of group.sequences) {
      const residue = sequence.seq[index]?.toUpperCase()
      if (!residue || residue === '-' || residue === '.') continue
      nonGapCount += 1
      counts.set(residue, (counts.get(residue) ?? 0) + 1)
    }
    let residue: string | null = null
    let count = 0
    counts.forEach((candidateCount, candidate) => {
      if (candidateCount > count || (candidateCount === count && candidate < (residue ?? candidate))) {
        residue = candidate
        count = candidateCount
      }
    })
    const hasConsensus = nonGapCount > 0 && count / nonGapCount >= threshold / 100
    return {
      residue: hasConsensus ? residue : null,
      matches: group.sequences.map((sequence) => hasConsensus && sequence.seq[index]?.toUpperCase() === residue),
    }
  })
}

function aminoAcidTooltip(sequence: AlignmentSequence, sequences: AlignmentSequence[], index: number): string {
  const residue = sequence.seq[index]?.toUpperCase() ?? ''
  if (!residue || residue === '-' || residue === '.') return 'Пропуск выравнивания'
  const position = Array.from(sequence.seq.slice(0, index + 1)).filter((item) => item !== '-' && item !== '.').length
  return [
    `${aminoAcidNames[residue] ?? residue} (${position})`,
    formatResidueFrequency(sequences, index, residue),
    `IMGT: ${sequence.numbering?.imgt?.[index] ?? '—'}`,
    `Kabat: ${sequence.numbering?.kabat?.[index] ?? '—'}`,
    `Chothia: ${sequence.numbering?.chothia?.[index] ?? '—'}`,
  ].join('\n')
}

function sortedNonEmptyGroups(data: { groups: ViewerGroup[] }): ViewerGroup[] {
  const found = new Map((data?.groups ?? []).map((group) => [group.name, group]))
  const known = groupOrder.flatMap((name) => {
    const group = found.get(name)
    return group && group.sequences.length > 0 ? [group] : []
  })
  const knownNames = new Set(groupOrder)
  const other = (data?.groups ?? []).filter((group) => !knownNames.has(group.name) && group.sequences.length > 0)
  return [...known, ...other]
}

function sourceKey(sequence: ViewerSequence): string | null {
  const source = sequence.source
  if (!source) return null
  return JSON.stringify([source.animal, source.project, source.group])
}

function sourceLabel(sequence: ViewerSequence): string {
  const source = sequence.source
  return source ? `${source.animal} / ${source.project} / ${source.group}` : 'Происхождение неизвестно'
}

function AlignmentGroupPanel({
  group,
  scheme,
  showCdr,
  showConsensus,
  showZappo,
  consensusThreshold,
  selectedSequence,
  onSelect,
  onMove,
  excludedIds,
  onToggleExclusion,
  fullScreen,
  onOpenInNewTab,
}: {
  group: ViewerGroup
  scheme: CdrScheme
  showCdr: boolean
  showConsensus: boolean
  showZappo: boolean
  consensusThreshold: number
  selectedSequence: string | null
  onSelect: (sequenceId: string) => void
  onMove: (sequenceId: string, offset: -1 | 1) => void
  excludedIds: string[]
  onToggleExclusion: (sequenceId: string) => void
  fullScreen: boolean
  onOpenInNewTab?: () => void
}) {
  const columns = useMemo(() => calculateConsensus(group, consensusThreshold), [group, consensusThreshold])
  const schemeColor = schemes.find((item) => item.value === scheme)?.color ?? 'transparent'

  return (
    <Paper variant="outlined" sx={{ p: { xs: 1, sm: 2 }, minWidth: 0 }}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap">
        <Typography variant="h6">{group.name}</Typography>
        {onOpenInNewTab && <Button size="small" variant="outlined" onClick={onOpenInNewTab}>Открыть в новой вкладке</Button>}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Последовательностей: {group.sequences.length}
      </Typography>
      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, maxHeight: fullScreen ? 'calc(100vh - 250px)' : 360, overflow: 'auto', scrollbarGutter: 'stable both-edges' }}>
        <Box component="table" sx={{ borderCollapse: 'separate', borderSpacing: 0, minWidth: 'max-content', fontFamily: '"JetBrains Mono", Consolas, monospace', fontSize: fullScreen ? 13.5 : 13 }}>
          <Box component="tbody">
            {group.sequences.map((sequence, rowIndex) => {
              const cdr = cdrIndexes(sequence, scheme)
              const isSelected = selectedSequence === sequence.id
              return (
                <Box component="tr" key={sequence.id} tabIndex={0} onClick={() => onSelect(sequence.id)} onKeyDown={(event) => {
                  if (event.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return
                  if (!event.ctrlKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return
                  event.preventDefault()
                  onSelect(sequence.id)
                  onMove(sequence.id, event.key === 'ArrowUp' ? -1 : 1)
                }} sx={{ cursor: 'pointer' }}>
                  <Box component="th" scope="row" sx={{ position: 'sticky', left: 0, zIndex: 1, px: 1, py: 0.25, textAlign: 'left', bgcolor: isSelected ? 'primary.main' : 'background.paper', color: isSelected ? 'primary.contrastText' : 'text.primary', borderRight: 1, borderColor: 'divider', whiteSpace: 'nowrap' }}>
                    <Checkbox checked={excludedIds.includes(sequence.id)} size="small" inputProps={{ 'aria-label': `Исключить ${sequence.name}` }} onClick={(event) => event.stopPropagation()} onChange={() => onToggleExclusion(sequence.id)} sx={{ p: 0, mr: 0.5, color: isSelected ? 'primary.contrastText' : undefined }} />
                    {sequence.name}
                  </Box>
                  <Box component="td" sx={{ p: 0.25, whiteSpace: 'pre', bgcolor: isSelected ? 'primary.main' : 'transparent' }}>
                    {Array.from(sequence.seq).map((residue, index) => {
                      const upperResidue = residue.toUpperCase()
                      const background = showCdr && cdr.has(index)
                        ? schemeColor
                        : showConsensus && columns[index]?.matches[rowIndex]
                          ? '#fff59d'
                          : showZappo ? zappoColors[upperResidue] ?? 'transparent' : 'transparent'
                      return (
                        <Box component="span" key={`${sequence.id}-${index}`} title={aminoAcidTooltip(sequence, group.sequences, index)} sx={{ display: 'inline-block', minWidth: '0.74em', textAlign: 'center', bgcolor: background, color: isSelected && background === 'transparent' ? 'primary.contrastText' : 'inherit' }}>
                          {residue}
                        </Box>
                      )
                    })}
                  </Box>
                </Box>
              )
            })}
          </Box>
        </Box>
      </Box>
    </Paper>
  )
}

export function AlignmentViewer({ jobId, fullScreen = false, groupName }: Props) {
  const [viewer, dispatch] = useReducer(viewerReducer, jobId, createViewerState)
  const [error, setError] = useState<string>()
  const [scheme, setScheme] = useState<CdrScheme>('imgt')
  const [consensusThreshold, setConsensusThreshold] = useState(80)
  const [showConsensus, setShowConsensus] = useState(true)
  const [showCdr, setShowCdr] = useState(true)
  const [showZappo, setShowZappo] = useState(false)
  const [selectedSourceKey, setSelectedSourceKey] = useState('')
  const [realigning, setRealigning] = useState(false)
  const [realignError, setRealignError] = useState<string>()

  useEffect(() => {
    let active = true
    dispatch({ type: 'reset', jobId })
    setError(undefined)
    void api.alignments(jobId).then(
      (response) => { if (active) dispatch({ type: 'loaded', jobId, alignment: response }) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить выравнивание.') },
    )
    return () => { active = false }
  }, [jobId])

  const groups = useMemo(() => {
    const nonEmptyGroups = sortedNonEmptyGroups({ groups: orderedViewerGroups(viewer.present) })
    return groupName ? nonEmptyGroups.filter((group) => group.name === groupName) : nonEmptyGroups
  }, [viewer.present, groupName])
  const openGroupInNewTab = (name: string) => {
    const query = new URLSearchParams({ view: 'alignment', job: jobId, group: name })
    window.open(`?${query.toString()}`, '_blank', 'noopener,noreferrer')
  }
  const moveSelected = (offset: -1 | 1) => {
    if (!viewer.selected) return
    dispatch({ type: 'move', groupName: viewer.selected.groupName, sequenceId: viewer.selected.sequenceId, offset })
  }
  const openClustering = () => {
    window.location.href = `?view=clustering&job=${encodeURIComponent(jobId)}`
  }
  const originalSequences = viewer.original?.groups.flatMap((group) => group.sequences) ?? []
  const presentIds = new Set(viewer.present?.includedIds ?? [])
  const sourceOptions = useMemo(() => {
    const options = new Map<string, ViewerSequence>()
    originalSequences.forEach((sequence) => {
      const key = sourceKey(sequence)
      if (key && !options.has(key)) options.set(key, sequence)
    })
    return [...options.entries()]
  }, [viewer.original])
  const baselineExcludedIds = useMemo(() => {
    const originalIds = new Set(originalSequences.map((sequence) => sequence.id))
    return [...originalIds].filter((id) => !presentIds.has(id)).sort()
  }, [viewer.original, viewer.present])
  const draftExcludedIds = [...viewer.draftExcludedIds].sort()
  const exclusionsChanged = draftExcludedIds.length !== baselineExcludedIds.length
    || draftExcludedIds.some((id, index) => id !== baselineExcludedIds[index])
  const retainedIds = [...presentIds].filter((id) => !viewer.draftExcludedIds.includes(id))
  const toggleSourceExclusion = (key: string) => {
    const ids = originalSequences.filter((sequence) => sourceKey(sequence) === key).map((sequence) => sequence.id)
    const shouldExclude = ids.some((id) => !viewer.draftExcludedIds.includes(id))
    const next = new Set(viewer.draftExcludedIds)
    ids.forEach((id) => shouldExclude ? next.add(id) : next.delete(id))
    dispatch({ type: 'setDraftExclusions', sequenceIds: [...next] })
  }
  const applyExclusions = async () => {
    if (!viewer.present || !exclusionsChanged || retainedIds.length === 0 || realigning) return
    setRealigning(true)
    setRealignError(undefined)
    try {
      const parentId = viewer.present.jobId || jobId
      const derivedJob = await api.realign(parentId, retainedIds)
      let status = derivedJob
      while (status.status === 'queued' || status.status === 'running') {
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
        status = await api.job(derivedJob.id)
      }
      if (status.status !== 'done' && status.status !== 'partial') {
        throw new ApiError(status.failure_reason || 'Повторное выравнивание завершилось ошибкой.')
      }
      const alignment = await api.alignments(derivedJob.id)
      dispatch({ type: 'applyAlignment', jobId: derivedJob.id, alignment })
    } catch (reason) {
      setRealignError(reason instanceof ApiError ? reason.message : 'Не удалось применить исключения и выровнять последовательности.')
    } finally {
      setRealigning(false)
    }
  }

  if (error) return <Alert severity="warning">{error}</Alert>
  if (viewer.jobId !== jobId || !viewer.present) return <Box textAlign="center" py={3}><CircularProgress size={24} /></Box>
  if (groups.length === 0) return <Typography color="text.secondary">Выравнивания не найдены.</Typography>

  return (
    <Stack spacing={2} sx={fullScreen ? { minHeight: '100vh', p: { xs: 1, sm: 2 } } : undefined}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap">
        <Typography component="h3" variant={fullScreen ? 'h4' : 'h6'}>Выравнивание последовательностей</Typography>
      </Box>
      {fullScreen ? (
        <Stack spacing={1}>
          <Paper variant="outlined" sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1, flexWrap: 'wrap' }}>
            <Typography variant="caption" fontWeight={700}>Консенсус</Typography>
            <Checkbox checked={showConsensus} size="small" inputProps={{ 'aria-label': 'Показывать консенсус' }} onChange={(event) => setShowConsensus(event.target.checked)} />
            <ToggleButtonGroup exclusive size="small" value={consensusThreshold} disabled={!showConsensus} aria-label="Порог консенсуса" onChange={(_, value: number | null) => { if (value !== null) setConsensusThreshold(value) }}>
              {consensusThresholds.map((value) => <ToggleButton key={value} value={value}>{value}%</ToggleButton>)}
            </ToggleButtonGroup>
            <Typography variant="caption" fontWeight={700}>CDR</Typography>
            <Checkbox checked={showCdr} size="small" inputProps={{ 'aria-label': 'Показывать CDR' }} onChange={(event) => setShowCdr(event.target.checked)} />
            <ToggleButtonGroup exclusive size="small" value={scheme} disabled={!showCdr} aria-label="Схема нумерации CDR" onChange={(_, value: CdrScheme | null) => { if (value !== null) setScheme(value) }}>
              {schemes.map((item) => <ToggleButton key={item.value} value={item.value} sx={{ '&.Mui-selected': { bgcolor: item.color, '&:hover': { bgcolor: item.color } } }}>{item.label}</ToggleButton>)}
            </ToggleButtonGroup>
            <Typography variant="caption" fontWeight={700}>Zappo</Typography>
            <Checkbox checked={showZappo} size="small" inputProps={{ 'aria-label': 'Показывать цвета Zappo' }} onChange={(event) => setShowZappo(event.target.checked)} />
          </Paper>
          <Typography variant="body2" color="text.secondary">CDR имеют приоритет над консенсусом и цветами Zappo. Нажмите на строку, чтобы выделить последовательность.</Typography>
          <Accordion variant="outlined" disableGutters>
            <AccordionSummary expandIcon={<span aria-hidden="true">⌄</span>} aria-controls="additional-options-content" id="additional-options-header">
              <Typography>Дополнительные параметры</Typography>
            </AccordionSummary>
            <AccordionDetails id="additional-options-content">
              <Typography color="text.secondary">Параметры будут добавлены позже.</Typography>
            </AccordionDetails>
          </Accordion>
        </Stack>
      ) : (
        <ButtonGroup size="small" aria-label="Схема нумерации CDR">
          {schemes.map((item) => <Button key={item.value} variant={scheme === item.value ? 'contained' : 'outlined'} onClick={() => setScheme(item.value)}>{item.label}</Button>)}
        </ButtonGroup>
      )}
      <Paper variant="outlined" sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1, flexWrap: 'wrap' }}>
        <FormControl size="small" sx={{ minWidth: 240 }}>
          <InputLabel id="source-group-label">Исходная группа</InputLabel>
          <Select labelId="source-group-label" value={selectedSourceKey} label="Исходная группа" onChange={(event) => setSelectedSourceKey(event.target.value)}>
            <MenuItem value="">Все группы</MenuItem>
            {sourceOptions.map(([key, sequence]) => <MenuItem key={key} value={key}>{sourceLabel(sequence)}</MenuItem>)}
          </Select>
        </FormControl>
        {selectedSourceKey && <Button size="small" variant="outlined" onClick={() => toggleSourceExclusion(selectedSourceKey)}>Исключить группу</Button>}
        <Button size="small" variant="outlined" disabled={!viewer.selected} onClick={() => viewer.selected && dispatch({ type: 'sortCdr3', groupName: viewer.selected.groupName, scheme, direction: 'ascending' })}>Сортировать CDR3</Button>
        <Button size="small" variant="outlined" onClick={openClustering}>Кластеризовать</Button>
        <Tooltip title="Повторное выравнивание появится позже">
          <span><Button size="small" variant="outlined" disabled>Кластеризовать и выровнять заново</Button></span>
        </Tooltip>
        <Button size="small" variant="outlined" disabled>Исключить клон</Button>
        <Tooltip title="Отменить">
          <span><IconButton aria-label="Отменить" size="small" disabled={viewer.past.length === 0} onClick={() => dispatch({ type: 'undo' })}><SvgIcon><path d="M20 11H7.83l5.59-5.59L12 4l8 8-8 8-1.41-1.41L16.17 13H4v-2z" /></SvgIcon></IconButton></span>
        </Tooltip>
        <Tooltip title="Повторить">
          <span><IconButton aria-label="Повторить" size="small" disabled={viewer.future.length === 0} onClick={() => dispatch({ type: 'redo' })}><SvgIcon><path d="M4 11h12.17l-5.59-5.59L12 4l8 8-8 8-1.41-1.41L16.17 13H4v-2z" /></SvgIcon></IconButton></span>
        </Tooltip>
        <ButtonGroup size="small" aria-label="Перемещение выбранной строки">
          <Button disabled={!viewer.selected} onClick={() => moveSelected(-1)}>Вверх</Button>
          <Button disabled={!viewer.selected} onClick={() => moveSelected(1)}>Вниз</Button>
        </ButtonGroup>
        <Typography variant="body2" color="text.secondary">К исключению: {viewer.draftExcludedIds.length}</Typography>
        <Button size="small" variant="contained" disabled={!exclusionsChanged || retainedIds.length === 0 || realigning} onClick={() => void applyExclusions()}>{realigning ? 'Выполняется...' : 'Применить исключения и выровнять'}</Button>
      </Paper>
      {realignError && <Alert severity="warning">{realignError}</Alert>}
      {groups.map((group) => <AlignmentGroupPanel key={group.name} group={group} scheme={scheme} showCdr={showCdr} showConsensus={showConsensus} showZappo={showZappo} consensusThreshold={consensusThreshold} selectedSequence={viewer.selected?.groupName === group.name ? viewer.selected.sequenceId : null} onSelect={(sequenceId) => dispatch({ type: 'select', selection: { groupName: group.name, sequenceId } })} onMove={(sequenceId, offset) => dispatch({ type: 'move', groupName: group.name, sequenceId, offset })} excludedIds={viewer.draftExcludedIds} onToggleExclusion={(sequenceId) => dispatch({ type: 'toggleDraftExclusion', sequenceId })} fullScreen={fullScreen} onOpenInNewTab={fullScreen ? undefined : () => openGroupInNewTab(group.name)} />)}
    </Stack>
  )
}
