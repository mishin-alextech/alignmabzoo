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
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, type Animal, type Job, type JobSelection } from '../api/client'

type Props = { onCreated: (job: Job) => void }
type ProjectKey = `${string}\u0000${string}`

const keyFor = (animalCode: string, project: string): ProjectKey => `${animalCode}\u0000${project}`

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
    const absent = selectedAnimals.filter((code) => projects[code] === undefined)
    void Promise.all(absent.map(async (code) => [code, await api.projects(code)] as const)).then(
      (items) => {
        if (!active) return
        setProjects((current) => ({ ...current, ...Object.fromEntries(items) }))
      },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить проекты.') },
    )
    return () => { active = false }
  }, [selectedAnimals, projects])

  useEffect(() => {
    let active = true
    const missing = selectedProjects.filter((projectKey) => groups[projectKey] === undefined)
    void Promise.all(missing.map(async (projectKey) => {
      const [animalCode, project] = projectKey.split('\u0000')
      return [projectKey, await api.groups(animalCode, project)] as const
    })).then(
      (items) => {
        if (!active) return
        setGroups((current) => ({ ...current, ...Object.fromEntries(items) }))
      },
      (reason) => { if (active) setError(reason instanceof ApiError ? reason.message : 'Не удалось загрузить группы.') },
    )
    return () => { active = false }
  }, [selectedProjects, groups])

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
    setSelectedAnimals((current) => current.includes(code) ? current.filter((item) => item !== code) : [...current, code])
  }

  const toggleProject = (animalCode: string, project: string) => {
    const projectKey = keyFor(animalCode, project)
    setSelectedProjects((current) => current.includes(projectKey) ? current.filter((item) => item !== projectKey) : [...current, projectKey])
  }

  const setProjectAllGroups = (projectKey: ProjectKey, useAll: boolean) => {
    setAllGroups((current) => ({ ...current, [projectKey]: useAll }))
    if (applyToAll) {
      setAllGroups((current) => Object.fromEntries(selectedProjects.map((key) => [key, useAll])))
      if (!useAll) {
        const source = selectedGroups[projectKey] ?? []
        setSelectedGroups((current) => Object.fromEntries(selectedProjects.map((key) => [key, source.filter((group) => (groups[key] ?? []).includes(group))])))
      }
    }
  }

  const toggleGroup = (projectKey: ProjectKey, group: string) => {
    const next = (selectedGroups[projectKey] ?? []).includes(group)
      ? (selectedGroups[projectKey] ?? []).filter((item) => item !== group)
      : [...(selectedGroups[projectKey] ?? []), group]
    setAllGroups((current) => ({ ...current, [projectKey]: false }))
    if (applyToAll) {
      setAllGroups((current) => Object.fromEntries(selectedProjects.map((key) => [key, false])))
      setSelectedGroups((current) => ({
        ...current,
        ...Object.fromEntries(selectedProjects.map((key) => [key, next.filter((item) => (groups[key] ?? []).includes(item))])),
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
              {projects[code] === undefined ? <CircularProgress size={20} /> : projects[code].length === 0 ? <Typography color="text.secondary">Проекты не найдены.</Typography> : projects[code].map((project) => <FormControlLabel key={project} control={<Checkbox checked={selectedProjects.includes(keyFor(code, project))} onChange={() => toggleProject(code, project)} />} label={selectedAnimals.length > 1 ? `${code} ${project}` : project} />)}
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
                {!allGroups[projectKey] && (knownGroups.length === 0 ? <Typography color="text.secondary">Группы не найдены.</Typography> : <Box display="flex" flexWrap="wrap" gap={1}>{knownGroups.map((group) => <FormControlLabel key={group} control={<Checkbox checked={(selectedGroups[projectKey] ?? []).includes(group)} onChange={() => toggleGroup(projectKey, group)} />} label={group} />)}</Box>)}
              </>}
            </Box>
          })}
        </>}
        <Box><Button variant="contained" disabled={creating || loading} onClick={() => void createJob()}>{creating ? 'Создание…' : 'Запустить пайплайн'}</Button></Box>
      </Stack>
    </Paper>
  )
}
