# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM rust:1.88-bookworm AS mmseqs-builder

ARG MMSEQS_REPOSITORY=https://github.com/soedinglab/MMseqs2.git
ARG MMSEQS_GIT_REF=master

WORKDIR /build

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        cmake \
        g++ \
        git \
        make \
        zlib1g-dev \
        libbz2-dev \
    && rustc --version \
    && cargo --version \
    && mkdir mmseqs2 \
    && cd mmseqs2 \
    && git init \
    && git remote add origin "$MMSEQS_REPOSITORY" \
    && git fetch --depth 1 origin "$MMSEQS_GIT_REF" \
    && git checkout --detach FETCH_HEAD \
    && git rev-parse HEAD > /build/mmseqs2-revision \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/mmseqs2 \
    && cmake --build build --parallel 2 \
    && cmake --install build \
    && rm -rf /var/lib/apt/lists/* /build/mmseqs2/.git


FROM python:3.12-slim-bookworm AS runtime

ARG IGBLAST_REQUIRED=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    IGDATA=/opt/igblast \
    PATH=/opt/igblast/bin:/opt/mmseqs2/bin:$PATH

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        clustalo \
        hmmer \
        libatomic1 \
        libgomp1 \
        libbz2-1.0 \
        perl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=mmseqs-builder /opt/mmseqs2/ /opt/mmseqs2/
COPY --from=mmseqs-builder /build/mmseqs2-revision /usr/local/share/mmseqs2-revision

# IgBLAST 1.22.0 и IMGT/V-QUEST 202631-1 поставляются как зафиксированные
# исходные архивы. FASTA без IMGT-gap и BLAST-индексы создаются внутри Linux-
# образа официальными edit_imgt_file.pl и makeblastdb.
COPY docker/igblast/ /tmp/igblast-source/
RUN set -eu; \
    if [ "$IGBLAST_REQUIRED" = "1" ]; then \
        test -f /tmp/igblast-source/igblast.sha256; \
        test -f /tmp/igblast-source/imgt.sha256; \
        set -- /tmp/igblast-source/dist/*.tar.gz; \
        test -f "$1" && test "$#" -eq 1; \
        (cd /tmp/igblast-source && sha256sum --check igblast.sha256); \
        (cd /tmp/igblast-source && sha256sum --check imgt.sha256); \
        mkdir -p /tmp/igblast-unpack /opt/igblast/bin /opt/igblast/profiles; \
        tar -xzf "$1" -C /tmp/igblast-unpack; \
        package_root="$(dirname "$(dirname "$(find /tmp/igblast-unpack -type f -name igblastn -print -quit)")")"; \
        test -x "$package_root/bin/igblastn" && test -x "$package_root/bin/makeblastdb"; \
        install -m 0755 "$package_root/bin/igblastn" /opt/igblast/bin/igblastn; \
        install -m 0755 "$package_root/bin/makeblastdb" /opt/igblast/bin/makeblastdb; \
        install -m 0755 "$package_root/bin/edit_imgt_file.pl" /opt/igblast/bin/edit_imgt_file.pl; \
        cp -a "$package_root/internal_data" "$package_root/optional_file" /opt/igblast/; \
        install -m 0644 "$package_root/LICENSE" /opt/igblast/NCBI-LICENSE; \
        test -f /tmp/igblast-source/profiles/manifest.json; \
        cp -a /tmp/igblast-source/profiles/. /opt/igblast/profiles/; \
        python -m zipfile -e /tmp/igblast-source/IMGT_V-QUEST_reference_directory.zip /tmp/imgt; \
        for specification in \
            'hu:Homo_sapiens:human' \
            'ms:Mus_musculus:mouse' \
            'rb:Oryctolagus_cuniculus:rabbit' \
            'rt:Rattus_norvegicus:rat'; do \
            profile="${specification%%:*}"; remainder="${specification#*:}"; \
            species="${remainder%%:*}"; organism="${remainder#*:}"; \
            source_root="/tmp/imgt/IMGT_V-QUEST_reference_directory/$species/IG"; \
            profile_root="/opt/igblast/profiles/$profile"; \
            database_root="$profile_root/databases"; \
            igdata_root="$profile_root/igdata"; \
            test -f "$profile_root/profile.json"; \
            mkdir -p "$database_root/source" "$igdata_root/internal_data" "$igdata_root/optional_file"; \
            for segment in IGHV IGHD IGHJ IGKV IGKJ IGLV IGLJ; do \
                test -s "$source_root/$segment.fasta"; \
                cp "$source_root/$segment.fasta" "$database_root/source/$segment.fasta"; \
            done; \
            cat "$source_root/IGHV.fasta" "$source_root/IGKV.fasta" "$source_root/IGLV.fasta" > "$database_root/imgt_${profile}_v.raw.fasta"; \
            cat "$source_root/IGHJ.fasta" "$source_root/IGKJ.fasta" "$source_root/IGLJ.fasta" > "$database_root/imgt_${profile}_j.raw.fasta"; \
            cp "$source_root/IGHD.fasta" "$database_root/imgt_${profile}_d.raw.fasta"; \
            for region in v d j; do \
                perl /opt/igblast/bin/edit_imgt_file.pl "$database_root/imgt_${profile}_${region}.raw.fasta" > "$database_root/imgt_${profile}_${region}.fasta"; \
                makeblastdb -parse_seqids -dbtype nucl -in "$database_root/imgt_${profile}_${region}.fasta" -out "$database_root/imgt_${profile}_${region}"; \
            done; \
            cp -a "/opt/igblast/internal_data/$organism" "$igdata_root/internal_data/"; \
            cp "/opt/igblast/optional_file/${organism}_gl.aux" "$igdata_root/optional_file/"; \
            test -s "$igdata_root/internal_data/$organism/${organism}.ndm.imgt"; \
            test -s "$igdata_root/optional_file/${organism}_gl.aux"; \
        done; \
        (cd /opt/igblast/profiles && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS); \
        (cd /opt/igblast/profiles && sha256sum --check SHA256SUMS); \
        chmod -R a-w /opt/igblast; \
        command -v igblastn; \
        command -v makeblastdb; \
        igblastn -version; \
        makeblastdb -version; \
    else \
        mkdir -p /opt/igblast/profiles; \
        printf '%s\\n' 'V(D)J support was explicitly disabled with IGBLAST_REQUIRED=0.' > /opt/igblast/profiles/UNAVAILABLE; \
        chmod -R a-w /opt/igblast; \
    fi; \
    rm -rf /tmp/igblast-source /tmp/igblast-unpack

# Backend — устанавливаемый Python-пакет с ASGI-приложением app.main:app.
COPY backend/ /build/backend/
RUN pip install --no-cache-dir /build/backend

# ANARCI — локальная проверенная поставка. setup.py проекта скачивает
# germline-данные из сети, поэтому его намеренно не запускаем: копируем уже
# подготовленные пакет и HMM-базу непосредственно в образ.
COPY anarci-master/ /tmp/anarci/
RUN anarci_site="$(python -c 'import site; print(site.getsitepackages()[0])')" \
    && mkdir -p "$anarci_site/anarci" \
    && cp -a /tmp/anarci/lib/python/anarci/. "$anarci_site/anarci/" \
    && install -m 0755 /tmp/anarci/bin/ANARCI /usr/local/bin/ANARCI \
    && python -c "import anarci; from pathlib import Path; hmm = Path(anarci.__file__).parent / 'dat' / 'HMMs' / 'ALL.hmm'; assert hmm.is_file(), hmm" \
    && command -v ANARCI \
    && command -v hmmscan \
    && command -v clustalo \
    && command -v mmseqs \
    && ANARCI --help >/dev/null \
    && mmseqs version \
    && rm -rf /tmp/anarci

COPY backend/ /app/backend/
COPY --from=frontend-builder /build/frontend/dist/ /app/app/static/

# Единственное место для записываемых результатов job внутри контейнера.
RUN mkdir -p /app/jobs

WORKDIR /app/backend

EXPOSE 8000

# Реестр и семафор общие внутри одного процесса; вычисления идут в фоновых потоках.
CMD ["python", "-m", "gunicorn", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker"]
