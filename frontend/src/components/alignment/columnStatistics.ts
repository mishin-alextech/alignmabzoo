import type { AlignmentSequence } from '../../api/client'

export type ColumnStatistic = {
  residue: string | null
  count: number
  total: number
  percentage: number | null
}

export function calculateColumnStatistics(sequences: AlignmentSequence[]): ColumnStatistic[] {
  const length = Math.max(0, ...sequences.map((sequence) => sequence.seq.length))
  return Array.from({ length }, (_, index) => {
    const counts = new Map<string, number>()
    let total = 0
    sequences.forEach((sequence) => {
      const residue = sequence.seq[index]?.toUpperCase()
      if (!residue || residue === '-' || residue === '.') return
      total += 1
      counts.set(residue, (counts.get(residue) ?? 0) + 1)
    })
    let residue: string | null = null
    let count = 0
    counts.forEach((candidateCount, candidate) => {
      if (candidateCount > count || (candidateCount === count && candidate < (residue ?? candidate))) {
        residue = candidate
        count = candidateCount
      }
    })
    return {
      residue,
      count,
      total,
      percentage: total > 0 ? (count / total) * 100 : null,
    }
  })
}

export function formatColumnStatistic(statistic: ColumnStatistic): string {
  if (!statistic.residue || statistic.percentage === null) return ''
  return `Частота: ${statistic.percentage.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}% (${statistic.count} из ${statistic.total})`
}