# IMGT-профили IgBLAST

В репозитории хранятся manifest и `profile.json` для четырёх профилей первого
выпуска. Каталоги `databases/` и `igdata/` представлены заранее, а их
содержимое воспроизводимо создаётся Dockerfile из зафиксированных архивов.

| Profile | Код | Таксон | IgBLAST organism |
|---|---|---|---|
| `hu` | `Hu` | *Homo sapiens* | `human` |
| `ms` | `Ms` | *Mus musculus* | `mouse` |
| `rb` | `Rb` | *Oryctolagus cuniculus* | `rabbit` |
| `rt` | `Rt` | *Rattus norvegicus* | `rat` |

`profiles/<id>/profile.json` содержит строковые поля `id`, `version`,
`organism`, `v_db`, `d_db`, `j_db`, `auxiliary_data` и `igdata`. Пути должны
находиться внутри `/opt/igblast`; backend проверяет это перед запуском.

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
    ├── internal_data/<organism>/<organism>.ndm.imgt
    └── optional_file/<organism>_gl.aux
```

Лёгкие цепи используют V/J; поле D в общем профиле нужно для тяжёлых цепей.
Все выбранные последовательности анализируются независимо. Для остальных
животных будут добавляться только отдельные собственные IMGT-профили.
