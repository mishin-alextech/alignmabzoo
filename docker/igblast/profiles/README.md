# IMGT-профили IgBLAST

В репозитории хранятся manifest и `profile.json` для восьми подготовленных
профилей. Каталоги `databases/` и `igdata/` представлены заранее, а их
содержимое воспроизводимо создаётся Dockerfile из зафиксированных архивов.

| Profile | Код | Таксон | Разметка IgBLAST |
|---|---|---|---|
| `hu` | `Hu` | *Homo sapiens* | `human` |
| `ms` | `Ms` | *Mus musculus* | `mouse` |
| `rb` | `Rb` | *Oryctolagus cuniculus* | `rabbit` |
| `rt` | `Rt` | *Rattus norvegicus* | `rat` |
| `pg` | `Pg` | *Sus scrofa* | собственная из IMGT |
| `ov` | `Ov` | *Ovis aries* | собственная из IMGT |
| `gt` | `Gt` | *Capra hircus* | собственная из IMGT, только K/L |
| `bv` | `Bv` | *Bos taurus* | собственная из IMGT |

`profiles/<id>/profile.json` содержит строковые поля `id`, `version`,
`v_db`, `d_db`, `j_db`, `auxiliary_data` и `igdata`. Встроенные профили задают
`organism`, а custom-профили — `custom_internal_data`. Пути должны находиться
внутри `/opt/igblast`; backend проверяет это перед запуском.

Готовый профиль имеет структуру:

```text
profiles/<id>/
├── profile.json
├── databases/
│   ├── source/{IGHV,IGHD,IGHJ,IGKV,IGKJ,IGLV,IGLJ}.fasta
│   ├── imgt_<id>_{v,d,j}.raw.fasta
│   ├── imgt_<id>_{v,d,j}.fasta
│   └── imgt_<id>_{v,d,j}.{ndb,nhr,nin,...}
└── igdata/
    ├── internal_data/<profile>/<profile>.ndm.imgt
    └── optional_file/<profile>_gl.aux
```

Лёгкие цепи используют V/J; поле D в общем профиле нужно для тяжёлых цепей.
Профиль `Gt` явно ограничен группами `VKappa` и `VLambda`: для тяжёлых цепей
он возвращает статус недоступности, поскольку в релизе нет козьих IGHV/D/J.
Все выбранные последовательности анализируются независимо. `Pg`, `Ov` и `Bv`
используют `.ndm.imgt` и `.aux`, которые воспроизводимо строятся из собственных
IMGT-gapped V и J FASTA утилитами receptor-utils `0.0.67`. Для остальных
животных будут добавляться только отдельные собственные IMGT-профили.
