# Изменения для anarci_runner

1. Переименовать chains_named.txt в chains_named.fasta и обновить все ссылки.

2. Передавать все последовательности одним FASTA-файлом. Для каждой схемы выполнять ровно один запуск:

```python
command = ["ANARCI", "-i", str(chains_named_fasta), "--scheme", scheme,
           "--csv", "--outfile", str(output_csv)]
```

3. Добавлять `--use_species` только при выборе пользователем ровно одного вида:

```python
ANARCI_SPECIES = {"Ms":"mouse", "Rb":"rabbit", "Rt":"rat", "Pg":"pig",
                  "Hu":"human", "Cm":"alpaca", "Bv":"cow"}
selected_species = list(selected_animals)
if len(selected_species) == 1:
    species = ANARCI_SPECIES.get(selected_species[0])
    if species:
        command.extend(["--use_species", species])
```

Для Hs, Ov, Gt и при выборе нескольких видов параметр не добавлять. Проверять именно выбор пользователя, а не число найденных последовательностей.

Для каждой схемы сохранять CSV в anarci; фактическую команду и результат писать в log.txt.