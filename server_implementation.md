# AlignMabZoo — журнал реализации

## 2026-09-05. Маппинг кода животного → имя директории (исправление бага «зависание при выборе животного»)

### Проблема
При выборе любого животного (например, `Rb` — кролик) веб-интерфейс зависал:
`GET /api/animals/Rb/projects` сканировал несуществующий каталог
`<data_root>/Rb`, а реальные данные лежат в каталогах с полным именем.

### Причина
`DiscoveryService` (и `validate_selection` в `job_pipeline.py`) строили путь как
`data_root / <двухбуквенный код>`, тогда как реальная структура данных:

```
/home/bioinfo/synced/data/mabzoo/
├── 1-2_Mouse mAbs_seq results/        → Ms
├── 3_Rabbit mAbs_seq results/        → Rb
├── 4-5_Rat mAbs_seq results/         → Rt
├── 6_Pig_mAbs_seq_results/           → Pg
├── 7_Human_mAbs_seq_results/         → Hu
├── 80_83_Hamster_mAbs_seq_results/   → Hs
├── 90_Ovis_Aries_mAbs_seq_results/   → Ov
├── 92_Goat_mAbs_seq_results/         → Gt
├── 94_95_Camelids_mAbs_seq_results/  → Cm
└── 96_97_Bovine_mAbs_seq_results/    → Bv
```

Имена директорий животных неизменны — маппинг имя→код хардкодится.

### Изменения

#### 1. `backend/app/services/discovery.py`
- Добавлен `ANIMAL_DIRECTORIES: Final[dict[str, str]]` — хардкодированный
  маппинг код животного → имя директории (10 записей из структуры данных).
- `ANIMAL_NAMES` сохранён без изменений (порядок и коды не изменились).
- Добавлен метод `animal_directory_name(animal_code) -> str` (ValueError для
  неизвестного кода).
- `list_projects`: путь каталога животного теперь
  `self._data_root / self.animal_directory_name(animal_code)`.
- `list_groups`: аналогично — `animal_directory = self._child_directory(
  self._data_root, self.animal_directory_name(animal_code))`.

#### 2. `backend/app/services/job_pipeline.py`
- `validate_selection`: путь каталога группы теперь
  `data_root / discovery.animal_directory_name(code) / project_name / group_name`
  (ранее `data_root / code / project_name / group_name`).

#### 3. `docker-compose.yml`
- Volume: `/home/bioinfo/synced_data/mabzoo:/synced_data/mabzoo:ro`
  (реальный путь данных на хосте — `/home/bioinfo/synced_data/mabzoo`).

#### 4. `backend/app/config.py`
- Значение по умолчанию `data_root`: `/synced_data/mabzoo` →
  `/home/bioinfo/synced_data/mabzoo` (совпадает с путём на хосте; в контейнере
  путь переопределяется `ALIGNMABZOO_DATA_ROOT=/synced_data/mabzoo`).

### Не изменено
- API-контракты (`/api/animals`, `/api/animals/{code}/projects`,
  `/api/animals/{code}/projects/{project}/groups`) — коды животных в URL
  остаются двухбуквенными.
- Фронтенд — без изменений.
- `naming.py`, `parser.py`, `anarci_runner.py`, `alignment.py`, `cdr_extract.py`,
  `job_registry.py` — без изменений.

### Тесты
Не проводились (по правилу: тесты только по явному указанию пользователя).
