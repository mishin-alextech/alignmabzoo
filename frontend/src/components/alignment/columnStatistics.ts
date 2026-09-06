import type { AlignmentSequence } from '../../api/client'

export function formatResidueFrequency(
  sequences: AlignmentSequence[],
  index: number,
  residue: string,
): string {
  const normalizedResidue = residue.toUpperCase()
  if (!normalizedResidue || normalizedResidue === '-' || normalizedResidue === '.') return ''
  let count = 0
  let total = 0
  sequences.forEach((sequence) => {
    const candidate = sequence.seq[index]?.toUpperCase()
    if (!candidate || candidate === '-' || candidate === '.') return
    total += 1
    if (candidate === normalizedResidue) count += 1
  })
  if (total === 0) return ''
  const percentage = (count / total) * 100
  return `Частота: ${percentage.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
}