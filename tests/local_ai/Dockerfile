FROM python:3.10-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install AI libraries
# FIX: Pin datasets to 2.17.0 to bypass the "Dataset scripts" error
RUN pip install --no-cache-dir \
    flask \
    faster-whisper \
    optimum[openvino] \
    diffusers \
    transformers \
    scipy \
    "datasets==2.17.0" \
    sentencepiece \
    soundfile \
    requests \
    accelerate \
    sentence-transformers \
    gunicorn \
    pymongo \
    redis

COPY server.py .

EXPOSE 5005

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5005", "server:app"]