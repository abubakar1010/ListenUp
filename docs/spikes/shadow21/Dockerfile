FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY docs/spikes/shadow20/requirements.txt /tmp/requirements.txt
# Arm CPU wheels use the un-suffixed version from PyPI.
RUN pip install --no-cache-dir -r /tmp/requirements.txt torch==2.8.0 torchaudio==2.8.0
WORKDIR /repo
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
