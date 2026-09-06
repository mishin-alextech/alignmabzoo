import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, ButtonGroup, Checkbox, CircularProgress, IconButton, Paper, Stack, SvgIcon, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import { useEffect, useMemo, useReducer, useState } from 'react'
import { ApiError, api, type AlignmentGroup, type AlignmentResponse, type AlignmentSequence, type CdrScheme } from '../api/client'
import { calculateColumnStatistics, formatColumnStatistic } from './alignment/columnStatistics'
import { createViewerState, orderedViewerGroups, viewerReducer, type ViewerGroup } from './alignment/viewerState'

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

function aminoAcidTooltip(sequence: AlignmentSequence, index: number): string {
  const residue = sequence.seq[index]?.toUpperCase() ?? ''
  if (!residue || residue === '-' || residue === '.') return 'Пропуск выравнивания'
  const position = Array.from(sequence.seq.slice(0, index + 1)).filter((item) => item !== '-' && item !== '.').length
  return [
    `${aminoAcidNames[residue] ?? residue} (${position})`,
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
  windowRows,
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
  onSelect: (sequenceName: string) => void
  onMove: (sequenceId: string, offset: -1 | 1) => void
  windowRows: 30 | 60 | 120
  fullScreen: boolean
  onOpenInNewTab?: () => void
}) {
  const columns = useMemo(() => calculateConsensus(group, consensusThreshold), [group, consensusThreshold])
  const statistics = useMemo(() => calculateColumnStatistics(group.sequences), [group.sequences])
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
      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, maxHeight: fullScreen ? `min(calc(100vh - 250px), ${windowRows * 1.65}em)` : `min(360px, ${windowRows * 1.65}em)`, overflow: 'auto', scrollbarGutter: 'stable both-edges' }}>
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
                  <Box component="th" scope="row" sx={{ position: 'sticky', left: 0, zIndex: 1, px: 1, py: 0.5, textAlign: 'left', bgcolor: isSelected ? 'primary.main' : 'background.paper', color: isSelected ? 'primary.contrastText' : 'text.primary', borderRight: 1, borderColor: 'divider', whiteSpace: 'nowrap' }}>
                    {sequence.name}
                  </Box>
                  <Box component="td" sx={{ p: 0.5, whiteSpace: 'pre', bgcolor: isSelected ? 'primary.main' : 'transparent' }}>
                    {Array.from(sequence.seq).map((residue, index) => {
                      const upperResidue = residue.toUpperCase()
                      const background = showCdr && cdr.has(index)
                        ? schemeColor
                        : showConsensus && columns[index]?.matches[rowIndex]
                          ? '#fff59d'
                          : showZappo ? zappoColors[upperResidue] ?? 'transparent' : 'transparent'
                      return (
                        <Box component="span" key={`${sequence.name}-${index}`} title={aminoAcidTooltip(sequence, index)} sx={{ display: 'inline-block', minWidth: '0.74em', textAlign: 'center', bgcolor: background, color: isSelected && background === 'transparent' ? 'primary.contrastText' : 'inherit' }}>
                          {residue}
                        </Box>
                      )
                    })}
                  </Box>
                </Box>
              )
            })}
            <Box component="tr" aria-label="Частоты аминокислот">
              <Box component="th" scope="row" sx={{ position: 'sticky', left: 0, zIndex: 1, px: 1, py: 0.5, textAlign: 'left', bgcolor: 'background.paper', borderRight: 1, borderColor: 'divider', whiteSpace: 'nowrap', fontFamily: 'inherit' }}>
                Частота
              </Box>
              <Box component="td" sx={{ p: 0.5, whiteSpace: 'pre' }}>
                {statistics.map((statistic, index) => <Box component="span" key={`statistic-${index}`} title={formatColumnStatistic(statistic)} sx={{ display: 'inline-block', minWidth: '0.74em', textAlign: 'center', color: 'text.secondary' }}>{statistic.residue ? `${statistic.percentage?.toFixed(0)}%` : ''}</Box>)}
              </Box>
            </Box>
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
  const [windowRows, setWindowRows] = useState<30 | 60 | 120>(30)

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

  const arrowPath = (direction: 'back' | 'forward') => direction === 'back'
    ? 'M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z'
    : 'M4 11v2h12.17l-5.59 5.59L12 20l8-8-8-8-1.41 1.41L16.17 11H4z'

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
        <Typography variant="caption" fontWeight={700}>Окно строк</Typography>
        <ToggleButtonGroup exclusive size="small" value={windowRows} aria-label="Размер окна строк" onChange={(_, value: 30 | 60 | 120 | null) => { if (value !== null) setWindowRows(value) }}>
          {[30, 60, 120].map((value) => <ToggleButton key={value} value={value}>{value}</ToggleButton>)}
        </ToggleButtonGroup>
        <Button size="small" variant="outlined" onClick={() => viewer.selected && dispatch({ type: 'sortCdr3', groupName: viewer.selected.groupName, scheme, direction: 'ascending' })}>Сортировать CDR3</Button>
        <Button size="small" variant="outlined" onClick={() => { window.location.href = `?view=clustering&job=${encodeURIComponent(jobId)}` }}>Кластеризовать</Button>
        <Tooltip title="Повторное выравнивание появится позже">
          <span><Button size="small" variant="outlined" disabled>Кластеризовать и выровнять заново</Button></span>
        </Tooltip>
        <Button size="small" variant="outlined" disabled>Исключить клон</Button>
        <Tooltip title="Отменить">
          <span><IconButton aria-label="Отменить" size="small" disabled={viewer.past.length === 0} onClick={() => dispatch({ type: 'undo' })}><SvgIcon><path d={arrowPath('back')} /></SvgIcon></IconButton></span>
        </Tooltip>
        <Tooltip title="Повторить">
          <span><IconButton aria-label="Повторить" size="small" disabled={viewer.future.length === 0} onClick={() => dispatch({ type: 'redo' })}><SvgIcon><path d={arrowPath('forward')} /></SvgIcon></IconButton></span>
        </Tooltip>
      </Paper>
      {groups.map((group) => <AlignmentGroupPanel key={group.name} group={group} scheme={scheme} showCdr={showCdr} showConsensus={showConsensus} showZappo={showZappo} consensusThreshold={consensusThreshold} selectedSequence={viewer.selected?.groupName === group.name ? viewer.selected.sequenceId : null} onSelect={(sequenceId) => dispatch({ type: 'select', selection: { groupName: group.name, sequenceId } })} onMove={(sequenceId, offset) => dispatch({ type: 'move', groupName: group.name, sequenceId, offset })} windowRows={windowRows} fullScreen={fullScreen} onOpenInNewTab={fullScreen ? undefined : () => openGroupInNewTab(group.name)} />)}
    </Stack>
  )
}
