import type { AlignmentGroup, AlignmentResponse, AlignmentSequence, CdrScheme } from '../../api/client'

export type ViewerSequence = AlignmentSequence & { id: string }
export type ViewerGroup = Omit<AlignmentGroup, 'sequences'> & { sequences: ViewerSequence[] }
export type ViewerAlignment = Omit<AlignmentResponse, 'groups'> & { groups: ViewerGroup[] }
export type ViewerSelection = { groupName: string; sequenceId: string }
export type ViewerSnapshot = {
  jobId: string
  warning?: string
  alignment: ViewerAlignment
  order: Record<string, string[]>
  includedIds: string[]
}
export type ViewerState = {
  jobId: string
  original: ViewerAlignment | null
  present: ViewerSnapshot | null
  past: ViewerSnapshot[]
  future: ViewerSnapshot[]
  selected: ViewerSelection | null
  draftExcludedIds: string[]
}

export type ViewerAction =
  | { type: 'reset'; jobId: string }
  | { type: 'loaded'; jobId: string; alignment: AlignmentResponse }
  | { type: 'select'; selection: ViewerSelection | null }
  | { type: 'setDraftExclusions'; sequenceIds: string[] }
  | { type: 'toggleDraftExclusion'; sequenceId: string }
  | { type: 'resetDraftExclusions' }
  | { type: 'setOrder'; groupName: string; sequenceIds: string[] }
  | { type: 'setOrders'; orders: Record<string, string[]> }
  | { type: 'sortCdr3'; groupName: string; scheme: CdrScheme; direction: 'ascending' | 'descending' }
  | { type: 'move'; groupName: string; sequenceId: string; offset: -1 | 1 }
  | { type: 'applyAlignment'; jobId: string; sourceJobId: string; alignment: AlignmentResponse; warning?: string }
  | { type: 'undo' }
  | { type: 'redo' }

export function createViewerState(jobId: string): ViewerState {
  return { jobId, original: null, present: null, past: [], future: [], selected: null, draftExcludedIds: [] }
}

// Для старых результатов ID воспроизводится из панели, имени и номера повтора.
export function normalizeViewerAlignment(alignment: AlignmentResponse): ViewerAlignment {
  return {
    ...alignment,
    groups: (alignment.groups ?? []).map((group) => {
      const occurrences = new Map<string, number>()
      return {
        ...group,
        sequences: group.sequences.map((sequence) => {
          const occurrence = occurrences.get(sequence.name) ?? 0
          occurrences.set(sequence.name, occurrence + 1)
          const id = (sequence as AlignmentSequence & { id?: string }).id
          return { ...sequence, id: id || `legacy:${JSON.stringify([group.name, sequence.name, occurrence])}` }
        }),
      }
    }),
  }
}

function createSnapshot(jobId: string, alignment: ViewerAlignment, previous?: ViewerSnapshot): ViewerSnapshot {
  const order = Object.fromEntries(alignment.groups.map((group) => {
    const ids = group.sequences.map((sequence) => sequence.id)
    const available = new Set(ids)
    const retained = (previous?.order[group.name] ?? []).filter((id) => available.has(id))
    const seen = new Set(retained)
    return [group.name, [...retained, ...ids.filter((id) => !seen.has(id))]]
  }))
  return { jobId, alignment, order, includedIds: alignment.groups.flatMap((group) => group.sequences.map((sequence) => sequence.id)) }
}

export function orderedViewerGroups(snapshot: ViewerSnapshot | null): ViewerGroup[] {
  if (!snapshot) return []
  return snapshot.alignment.groups.map((group) => {
    const byId = new Map(group.sequences.map((sequence) => [sequence.id, sequence]))
    return { ...group, sequences: (snapshot.order[group.name] ?? []).flatMap((id) => {
      const sequence = byId.get(id)
      return sequence ? [sequence] : []
    }) }
  })
}

function appliedExclusions(state: ViewerState, snapshot: ViewerSnapshot | null): string[] {
  const included = new Set(snapshot?.includedIds ?? [])
  return (state.original?.groups ?? []).flatMap((group) => group.sequences.filter((sequence) => !included.has(sequence.id)).map((sequence) => sequence.id))
}

function restoreSnapshot(state: ViewerState, present: ViewerSnapshot): ViewerState {
  const selected = state.selected
  const selectionExists = present.alignment.groups.some((group) => group.name === selected?.groupName && group.sequences.some((sequence) => sequence.id === selected.sequenceId))
  return { ...state, present, selected: selectionExists ? selected : null, draftExcludedIds: appliedExclusions(state, present) }
}

function commitSnapshot(state: ViewerState, present: ViewerSnapshot): ViewerState {
  return restoreSnapshot({ ...state, past: state.present ? [...state.past, state.present] : state.past, future: [] }, present)
}

function changeOrder(state: ViewerState, groupName: string, sequenceIds: string[]): ViewerState {
  const present = state.present
  const current = present?.order[groupName]
  if (!present || !current || current.length !== sequenceIds.length) return state
  const allowed = new Set(current)
  if (new Set(sequenceIds).size !== current.length || sequenceIds.some((id) => !allowed.has(id))) return state
  if (current.every((id, index) => id === sequenceIds[index])) return state
  // Перестановка строк сохраняет ещё не применённый выбор исключений.
  return { ...commitSnapshot(state, { ...present, order: { ...present.order, [groupName]: [...sequenceIds] } }), draftExcludedIds: state.draftExcludedIds }
}

function cdr3Length(sequence: ViewerSequence, scheme: CdrScheme): number | null {
  const indices = sequence.cdr?.[scheme]?.cdr3
  if (!indices?.length) return null
  return [...new Set(indices)].filter((index) => {
    const residue = sequence.seq[index]
    return residue && residue !== '-' && residue !== '.'
  }).length
}

export function viewerReducer(state: ViewerState, action: ViewerAction): ViewerState {
  switch (action.type) {
    case 'reset': return createViewerState(action.jobId)
    case 'loaded': {
      if (action.jobId !== state.jobId) return state
      const original = normalizeViewerAlignment(action.alignment)
      return { ...createViewerState(state.jobId), original, present: createSnapshot(state.jobId, original) }
    }
    case 'select': {
      const selection = action.selection
      if (selection && !state.present?.alignment.groups.some((group) => group.name === selection.groupName && group.sequences.some((sequence) => sequence.id === selection.sequenceId))) return state
      return { ...state, selected: selection }
    }
    case 'setDraftExclusions': {
      const available = new Set(state.original?.groups.flatMap((group) => group.sequences.map((sequence) => sequence.id)))
      return { ...state, draftExcludedIds: [...new Set(action.sequenceIds)].filter((id) => available.has(id)) }
    }
    case 'toggleDraftExclusion':
      return viewerReducer(state, { type: 'setDraftExclusions', sequenceIds: state.draftExcludedIds.includes(action.sequenceId) ? state.draftExcludedIds.filter((id) => id !== action.sequenceId) : [...state.draftExcludedIds, action.sequenceId] })
    case 'resetDraftExclusions': return { ...state, draftExcludedIds: appliedExclusions(state, state.present) }
    case 'setOrder': return changeOrder(state, action.groupName, action.sequenceIds)
    case 'setOrders': {
      const present = state.present
      if (!present) return state
      const order = { ...present.order }
      let changed = false
      for (const [groupName, sequenceIds] of Object.entries(action.orders)) {
        const current = order[groupName]
        if (!current || current.length !== sequenceIds.length) return state
        const allowed = new Set(current)
        if (new Set(sequenceIds).size !== current.length || sequenceIds.some((id) => !allowed.has(id))) return state
        if (current.some((id, index) => id !== sequenceIds[index])) {
          order[groupName] = [...sequenceIds]
          changed = true
        }
      }
      return changed
        ? { ...commitSnapshot(state, { ...present, order }), draftExcludedIds: state.draftExcludedIds }
        : state
    }
    case 'sortCdr3': {
      const group = orderedViewerGroups(state.present).find((item) => item.name === action.groupName)
      if (!group) return state
      const rows = group.sequences.map((sequence, index) => ({ sequence, index, length: cdr3Length(sequence, action.scheme) }))
      rows.sort((left, right) => {
        if (left.length === null) return right.length === null ? left.index - right.index : 1
        if (right.length === null) return -1
        return (left.length - right.length) * (action.direction === 'ascending' ? 1 : -1) || left.index - right.index
      })
      return changeOrder(state, action.groupName, rows.map(({ sequence }) => sequence.id))
    }
    case 'move': {
      const order = [...(state.present?.order[action.groupName] ?? [])]
      const index = order.indexOf(action.sequenceId)
      const target = index + action.offset
      if (index < 0 || target < 0 || target >= order.length) return state
      ;[order[index], order[target]] = [order[target], order[index]]
      return changeOrder(state, action.groupName, order)
    }
    case 'applyAlignment': {
      if (action.sourceJobId !== state.jobId || !state.original || !state.present) return state
      const alignment = normalizeViewerAlignment(action.alignment)
      if (!alignment.groups.some((group) => group.sequences.length > 0)) return state
      return commitSnapshot(state, { ...createSnapshot(action.jobId, alignment, state.present), warning: action.warning })
    }
    case 'undo': {
      const present = state.past[state.past.length - 1]
      if (!present || !state.present) return state
      return restoreSnapshot({ ...state, past: state.past.slice(0, -1), future: [state.present, ...state.future] }, present)
    }
    case 'redo': {
      const present = state.future[0]
      if (!present || !state.present) return state
      return restoreSnapshot({ ...state, past: [...state.past, state.present], future: state.future.slice(1) }, present)
    }
  }
}
