# PaddleOCR requires a compatible PaddlePaddle runtime; official image avoids native lib conflicts.
FROM paddlepaddle/paddle:2.6.2

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV FLAGS_use_mkldnn=0
ENV MALLOC_ARENA_MAX=2
ENV OMP_NUM_THREADS=1

COPY requirements-ocr.txt requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-ocr.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-dev.txt \
    && pip install --no-cache-dir numpy==1.26.4

COPY . .

RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
