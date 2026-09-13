import type { AlignmentSequence } from '../../api/client'

export type ColumnStatistics = Array<{ total: number; counts: Map<string, number> }>

// Один проход по всем остаткам; пробелы выравнивания не входят в знаменатель.
export function calculateColumnStatistics(sequences: AlignmentSequence[]): ColumnStatistics {
  const columns: ColumnStatistics = []
  sequences.forEach((sequence) => {
    Array.from(sequence.seq).forEach((residue, index) => {
      const candidate = residue.toUpperCase()
      if (!candidate || candidate === '-' || candidate === '.') return
      const column = columns[index] ?? { total: 0, counts: new Map<string, number>() }
      column.total += 1
      column.counts.set(candidate, (column.counts.get(candidate) ?? 0) + 1)
      columns[index] = column
    })
  })
  return columns
}

export function formatResidueFrequency(
  columns: ColumnStatistics,
  index: number,
  residue: string,
): string {
  const normalizedResidue = residue.toUpperCase()
  if (!normalizedResidue || normalizedResidue === '-' || normalizedResidue === '.') return ''
  const column = columns[index]
  if (!column?.total) return ''
  const percentage = ((column.counts.get(normalizedResidue) ?? 0) / column.total) * 100
  return `Частота: ${percentage.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}% (${column.counts.get(normalizedResidue) ?? 0} из ${column.total})`
}
