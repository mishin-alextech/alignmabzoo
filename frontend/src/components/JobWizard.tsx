import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Divider,
  FormControlLabel,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, api, type Animal, type Job, type JobSelection } from '../api/client'

type Props = { onCreated: (job: Job) => void }
type ProjectKey = `${string}\u0000${string}`

const keyFor = (animalCode: string, project: string): ProjectKey => `${animalCode}\u0000${project}`

const VIRTUAL_ITEM_HEIGHT = 40
const VIRTUAL_VIEWPORT_HEIGHT = 320

function VirtualizedList({ items, renderItem }: { items: string[]; renderItem: (item: string) => ReactNode }) {
  const [scrollTop, setScrollTop] = useState(0)
  const overscan = 4
  const start = Math.max(0, Math.floor(scrollTop / VIRTUAL_ITEM_HEIGHT) - overscan)
  const end = Math.min(items.length, Math.ceil((scrollTop + VIRTUAL_VIEWPORT_HEIGHT) / VIRTUAL_ITEM_HEIGHT) + overscan)
  const visibleItems = items.slice(start, end)

  return (
    <Box
      sx={{ height: Math.min(VIRTUAL_VIEWPORT_HEIGHT, Math.max(VIRTUAL_ITEM_HEIGHT, items.length * VIRTUAL_ITEM_HEIGHT)), overflowY: 'auto', position: 'relative', border: 1, borderColor: 'divider', borderRadius: 1 }}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <Box sx={{ height: items.length * VIRTUAL_ITEM_HEIGHT, position: 'relative' }}>
        {visibleItems.map((item, index) => (
          <Box key={item} sx={{ height: VIRTUAL_ITEM_HEIGHT, position: 'absolute', top: (start + index) * VIRTUAL_ITEM_HEIGHT, left: 0, right: 0, display: 'flex', alignItems: 'center' }}>
            {renderItem(item)}
          </Box>
        ))}
      </Box>
    </Box>
  )
}

export function JobWizard({ onCreated }: Props) {
  const [name, setName] = useState('')
  const [animals, setAnimals] = useState<Animal[]>([])
  const [selectedAnimals, setSelectedAnimals] = useState<string[]>([])
  const [projects, setProjects] = useState<Record<string, string[]>>({})
  const [selectedProjects, setSelectedProjects] = useState<ProjectKey[]>([])
  const [groups, setGroups] = useState<Record<ProjectKey, string[]>>({})
  const [selectedGroups, setSelectedGroups] = useState<Record<ProjectKey, string[]>>({})
  const [allGroups, setAllGroups] = useState<Record<ProjectKey, boolean>>({})
  const [applyToAll, setApplyToAll] = useState(false)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string>()
  const [logLines, setLogLines] = useState<string[]>([])
  const logRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)

  // Лог «под капотом»: пользователь видит, что именно происходит при выборе
  // животных/проектов/групп (запросы к API, найденные проекты и группы).
  const appendLog = useCallback((line: string) => {
    const timestamp = new Date().toLocaleTimeString('ru-RU', { hour12: false })
    setLogLines((current) => [...current.slice(-499), `[${timestamp}] ${line}`])
  }, [])

  // Автопрокрутка лога вниз при новых строках, если пользователь не прокрутил вверх.
  useEffect(() => {
    const element = logRef.current
    if (element && stickToBottomRef.current) {
      element.scrollTop = element.scrollHeight
    }
  }, [logLines])

  const handleLogScroll = () => {
    const element = logRef.current
    if (!element) return
    stickToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24
  }

  useEffect(() => {
    let active = true
    void api.animals().then(
      (items) => { if (active) setAnimals(items) },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить животных.') },
    ).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const absent = selectedAnimals.filter((code) => projects[code] === undefined)
    if (absent.length > 0) {
      appendLog(`Загружаю проекты для: ${absent.join(', ')}…`)
    }
    void (async () => {
      try {
        for (const code of absent) {
          const list: string[] = []
          let offset = 0
          while (active) {
            const page = await api.projects(code, offset, controller.signal)
            list.push(...page.items)
            appendLog(`Проекты ${code}: загружено ${list.length}.`)
            if (page.nextOffset === null) break
            offset = page.nextOffset
          }
          if (active) setProjects((current) => ({ ...current, [code]: list }))
        }
      } catch (reason) {
        if (!active || (reason instanceof DOMException && reason.name === 'AbortError')) return
        appendLog(`Ошибка загрузки проектов: ${reason instanceof ApiError ? reason.message : 'не удалось загрузить проекты.'}`)
        setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить проекты.')
      }
    })()
    return () => { active = false; controller.abort() }
  }, [selectedAnimals, projects, appendLog])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const missing = selectedProjects.filter((projectKey) => groups[projectKey] === undefined)
    if (missing.length > 0) {
      appendLog(`Загружаю группы для: ${missing.map((key) => key.split('\u0000').join(' / ')).join(', ')}…`)
    }
    void (async () => {
      try {
        for (const projectKey of missing) {
          const [animalCode, project] = projectKey.split('\u0000')
          const list: string[] = []
          let offset = 0
          while (active) {
            const page = await api.groups(animalCode, project, offset, controller.signal)
            list.push(...page.items)
            appendLog(`Группы ${animalCode} / ${project}: загружено ${list.length}.`)
            if (page.nextOffset === null) break
            offset = page.nextOffset
          }
          if (active) setGroups((current) => ({ ...current, [projectKey]: list }))
        }
      } catch (reason) {
        if (!active || (reason instanceof DOMException && reason.name === 'AbortError')) return
        appendLog(`Ошибка загрузки групп: ${reason instanceof ApiError ? reason.message : 'не удалось загрузить группы.'}`)
        setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить группы.')
      }
    })()
    return () => { active = false; controller.abort() }
  }, [selectedProjects, groups, appendLog])

  const selection = useMemo<JobSelection>(() => ({
    animals: selectedAnimals.map((code) => ({
      code,
      projects: selectedProjects
        .filter((projectKey) => projectKey.startsWith(`${code}\u0000`))
        .map((projectKey) => {
          const [, project] = projectKey.split('\u0000')
          return {
            name: project,
            groups: allGroups[projectKey] ? (groups[projectKey] ?? []) : (selectedGroups[projectKey] ?? []),
          }
        })
        .filter((project) => project.groups.length > 0),
    })).filter((animal) => animal.projects.length > 0),
  }), [allGroups, groups, selectedAnimals, selectedGroups, selectedProjects])

  const toggleAnimal = (code: string) => {
    const isRemoving = selectedAnimals.includes(code)
    appendLog(isRemoving ? `Снято животное: ${code}` : `Выбрано животное: ${code}`)
    setSelectedAnimals((current) => current.includes(code) ? current.filter((item) => item !== code) : [...current, code])
    if (isRemoving) {
      // При снятии животного удаляем его проекты и группы, чтобы не было
      // висящих selectedProjects/selectedGroups и лишних запросов к API.
      const prefix = `${code}\u0000`
      setSelectedProjects((current) => current.filter((key) => !key.startsWith(prefix)))
      setSelectedGroups((current) => {
        const next: Record<ProjectKey, string[]> = {}
        for (const key of Object.keys(current) as ProjectKey[]) {
          if (!key.startsWith(prefix)) next[key] = current[key]
        }
        return next
      })
      setAllGroups((current) => {
        const next: Record<ProjectKey, boolean> = {}
        for (const key of Object.keys(current) as ProjectKey[]) {
          if (!key.startsWith(prefix)) next[key] = current[key]
        }
        return next
      })
    }
  }

  const toggleProject = (animalCode: string, project: string) => {
    const projectKey = keyFor(animalCode, project)
    const isRemoving = selectedProjects.includes(projectKey)
    appendLog(isRemoving ? `Снят проект: ${animalCode} / ${project}` : `Выбран проект: ${animalCode} / ${project}`)
    setSelectedProjects((current) => current.includes(projectKey) ? current.filter((item) => item !== projectKey) : [...current, projectKey])
  }

  const setProjectAllGroups = (projectKey: ProjectKey, useAll: boolean) => {
    setAllGroups((current) => ({ ...current, [projectKey]: useAll }))
    if (applyToAll) {
      setAllGroups((current) => ({ ...current, ...Object.fromEntries(selectedProjects.map((key) => [key, useAll] as const)) }))
      if (!useAll) {
        const source = selectedGroups[projectKey] ?? []
        setSelectedGroups((current) => ({ ...current, ...Object.fromEntries(selectedProjects.map((key) => [key, source.filter((group) => (groups[key] ?? []).includes(group))] as const)) }))
      }
    }
  }

  const toggleGroup = (projectKey: ProjectKey, group: string) => {
    const isRemoving = (selectedGroups[projectKey] ?? []).includes(group)
    appendLog(isRemoving ? `Снята группа: ${projectKey.split('\u0000').join(' / ')} / ${group}` : `Выбрана группа: ${projectKey.split('\u0000').join(' / ')} / ${group}`)
    const next = isRemoving
      ? (selectedGroups[projectKey] ?? []).filter((item) => item !== group)
      : [...(selectedGroups[projectKey] ?? []), group]
    setAllGroups((current) => ({ ...current, [projectKey]: false }))
    if (applyToAll) {
      setAllGroups((current) => ({ ...current, ...Object.fromEntries(selectedProjects.map((key) => [key, false] as const)) }))
      setSelectedGroups((current) => ({
        ...current,
        ...Object.fromEntries(selectedProjects.map((key) => [key, next.filter((item) => (groups[key] ?? []).includes(item))] as const)),
      }))
    } else setSelectedGroups((current) => ({ ...current, [projectKey]: next }))
  }

  const createJob = async () => {
    if (!name.trim()) { setError('Укажите название job.'); return }
    if (selection.animals.length === 0) { setError('Выберите хотя бы одну группу для обработки.'); return }
    setCreating(true)
    setError(undefined)
    try {
      onCreated(await api.createJob(name.trim(), selection))
      setName('')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Не удалось создать job.')
    } finally { setCreating(false) }
  }

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Typography component="h2" variant="h5">Новая job</Typography>
        {error && <Alert severity="error" onClose={() => setError(undefined)}>{error}</Alert>}
        <TextField label="Название job" value={name} inputProps={{ maxLength: 200 }} helperText={`${name.length}/200`} onChange={(event) => setName(event.target.value)} required fullWidth />
        <Divider />
        <Typography component="h3" variant="h6">1. Животные</Typography>
        {loading ? <CircularProgress size={24} /> : (
          <Box display="flex" flexWrap="wrap" gap={1}>
            {animals.map((animal) => <FormControlLabel key={animal.code} control={<Checkbox checked={selectedAnimals.includes(animal.code)} onChange={() => toggleAnimal(animal.code)} />} label={`${animal.code} — ${animal.name}`} />)}
          </Box>
        )}
        {selectedAnimals.length > 0 && <>
          <Divider />
          <Typography component="h3" variant="h6">2. Проекты</Typography>
          {selectedAnimals.map((code) => (
            <Box key={code}>
              <Typography variant="subtitle1">{animals.find((animal) => animal.code === code)?.name ?? code}</Typography>
              {projects[code] === undefined ? <CircularProgress size={20} /> : projects[code].length === 0 ? <Typography color="text.secondary">Проекты не найдены.</Typography> : <VirtualizedList items={projects[code]} renderItem={(project) => <FormControlLabel control={<Checkbox checked={selectedProjects.includes(keyFor(code, project))} onChange={() => toggleProject(code, project)} />} label={selectedAnimals.length > 1 ? `${code} ${project}` : project} />} />}
            </Box>
          ))}
        </>}
        {selectedProjects.length > 0 && <>
          <Divider />
          <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
            <Typography component="h3" variant="h6">3. Группы</Typography>
            <FormControlLabel control={<Checkbox checked={applyToAll} onChange={(event) => setApplyToAll(event.target.checked)} />} label="Применить ко всем проектам" />
          </Box>
          {selectedProjects.map((projectKey) => {
            const [code, project] = projectKey.split('\u0000')
            const knownGroups = groups[projectKey]
            return <Box key={projectKey} sx={{ pl: 1, borderLeft: 2, borderColor: 'divider' }}>
              <Typography variant="subtitle1">{selectedAnimals.length > 1 ? `${code} ${project}` : project}</Typography>
              {knownGroups === undefined ? <CircularProgress size={20} /> : <>
                <FormControlLabel control={<Checkbox checked={Boolean(allGroups[projectKey])} onChange={(event) => setProjectAllGroups(projectKey, event.target.checked)} />} label="Все группы этого проекта" />
                {!allGroups[projectKey] && (knownGroups.length === 0 ? <Typography color="text.secondary">Группы не найдены.</Typography> : <VirtualizedList items={knownGroups} renderItem={(group) => <FormControlLabel control={<Checkbox checked={(selectedGroups[projectKey] ?? []).includes(group)} onChange={() => toggleGroup(projectKey, group)} />} label={group} />} />)}
              </>}
            </Box>
          })}
        </>}
        <Box><Button variant="contained" disabled={creating || loading} onClick={() => void createJob()}>{creating ? 'Создание…' : 'Запустить пайплайн'}</Button></Box>
        <Divider />
        <Typography component="h3" variant="subtitle1">Журнал выбора (что происходит «под капотом»)</Typography>
        <Box
          ref={logRef}
          onScroll={handleLogScroll}
          component="pre"
          sx={{ m: 0, maxHeight: 240, overflow: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13, bgcolor: 'grey.50', border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5 }}
        >
          {logLines.length > 0 ? logLines.join('\n') : 'Пока пусто. Выберите животное — здесь появится, какие проекты и группы загружаются.'}
        </Box>
      </Stack>
    </Paper>
  )
}
