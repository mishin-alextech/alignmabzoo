import { Alert, Box, Button, ButtonGroup, CircularProgress, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, type AlignmentGroup, type AlignmentResponse, type AlignmentSequence, type CdrScheme } from '../api/client'

type Props = { jobId: string }

const schemes: Array<{ value: CdrScheme; label: string; color: string }> = [
  { value: 'imgt', label: 'IMGT', color: '#c8e6c9' },
  { value: 'kabat', label: 'Kabat', color: '#ffcdd2' },
  { value: 'chothia', label: 'Chothia', color: '#bbdefb' },
]

const groupOrder = ['VHeavy', 'VHH', 'VKappa', 'VLambda', 'Other']

function consensus(group: AlignmentGroup): Array<string | null> {
  const length = Math.max(0, ...group.sequences.map((sequence) => sequence.seq.length))
  return Array.from({ length }, (_, index) => {
    const count = new Map<string, number>()
    for (const sequence of group.sequences) {
      const residue = sequence.seq[index]?.toUpperCase()
      if (residue && residue !== '-' && residue !== '.') count.set(residue, (count.get(residue) ?? 0) + 1)
    }
    let residue: string | null = null
    let maximum = 0
    count.forEach((value, key) => {
      if (value > maximum) { residue = key; maximum = value }
    })
    return maximum / Math.max(1, group.sequences.length) >= 0.8 ? residue : null
  })
}

function cdrIndexes(sequence: AlignmentSequence, scheme: CdrScheme): Set<number> {
  const cdr = sequence.cdr?.[scheme]
  return new Set([...(cdr?.cdr1 ?? []), ...(cdr?.cdr2 ?? []), ...(cdr?.cdr3 ?? [])])
}

function AlignmentGroupPanel({ group, scheme }: { group: AlignmentGroup; scheme: CdrScheme }) {
  const columns = useMemo(() => consensus(group), [group])
  const schemeColor = schemes.find((item) => item.value === scheme)?.color ?? 'transparent'

  return (
    <Paper variant="outlined" sx={{ p: 2, minWidth: 0 }}>
      <Typography variant="h6">{group.name}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Последовательностей: {group.sequences.length}. Жёлтым отмечены консервативные позиции (≥ 80%), цветом схемы — CDR.
      </Typography>
      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, maxHeight: 360, overflow: 'auto' }}>
        <Box component="table" sx={{ borderCollapse: 'collapse', minWidth: 'max-content', fontFamily: 'monospace', fontSize: 13 }}>
          <Box component="tbody">
            {group.sequences.map((sequence) => {
              const cdr = cdrIndexes(sequence, scheme)
              return (
                <Box component="tr" key={sequence.name}>
                  <Box component="th" scope="row" sx={{ position: 'sticky', left: 0, zIndex: 1, p: 0.75, textAlign: 'left', bgcolor: 'background.paper', borderRight: 1, borderColor: 'divider', whiteSpace: 'nowrap' }}>
                    {sequence.name}
                  </Box>
                  <Box component="td" sx={{ p: 0.5, whiteSpace: 'pre' }}>
                    {Array.from(sequence.seq).map((residue, index) => {
                      const number = sequence.numbering?.[scheme]?.[index]
                      const title = number == null || residue === '-' || residue === '.'
                        ? 'Пропуск выравнивания или нумерация недоступна'
                        : `${scheme.toUpperCase()}: ${number}`
                      return <Box component="span" key={`${sequence.name}-${index}`} title={title} sx={{ display: 'inline-block', minWidth: '0.74em', textAlign: 'center', bgcolor: cdr.has(index) ? schemeColor : columns[index] === residue.toUpperCase() ? '#fff59d' : 'transparent' }}>{residue}</Box>
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

export function AlignmentViewer({ jobId }: Props) {
  const [data, setData] = useState<AlignmentResponse>()
  const [error, setError] = useState<string>()
  const [scheme, setScheme] = useState<CdrScheme>('imgt')

  useEffect(() => {
    let active = true
    setData(undefined)
    setError(undefined)
    void api.alignments(jobId).then(
      (response) => { if (active) setData(response) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить выравнивание.') },
    )
    return () => { active = false }
  }, [jobId])

  const groups = useMemo(() => {
    const found = new Map((data?.groups ?? []).map((group) => [group.name, group]))
    return groupOrder.map((name) => found.get(name) ?? { name, sequences: [] })
  }, [data])

  if (error) return <Alert severity="warning">{error}</Alert>
  if (!data) return <Box textAlign="center" py={3}><CircularProgress size={24} /></Box>

  return (
    <Stack spacing={2}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap">
        <Typography component="h3" variant="h6">Выравнивание последовательностей</Typography>
        <ButtonGroup size="small" aria-label="Схема нумерации CDR">
          {schemes.map((item) => <Button key={item.value} variant={scheme === item.value ? 'contained' : 'outlined'} onClick={() => setScheme(item.value)}>{item.label}</Button>)}
        </ButtonGroup>
      </Box>
      {groups.map((group) => group.sequences.length > 0
        ? <AlignmentGroupPanel key={group.name} group={group} scheme={scheme} />
        : <Paper key={group.name} variant="outlined" sx={{ p: 2 }}><Typography variant="subtitle1">{group.name}</Typography><Typography color="text.secondary" variant="body2">В этой группе нет последовательностей.</Typography></Paper>)}
    </Stack>
  )
}
