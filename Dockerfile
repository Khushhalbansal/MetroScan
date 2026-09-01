# The API + OCR pipeline, for a host that can run a long-lived Python process
# (Fly.io). The frontend deploys separately to Vercel; the database is Supabase
# Postgres. See docs/deploy.md.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RULES_DIR=/app/rules \
    STORAGE_DIR=/data/storage \
    ENVIRONMENT=production

# Runtime shared libraries: OpenMP + glib for onnxruntime/opencv-headless, and the
# Pango stack WeasyPrint binds to (without it `import weasyprint` raises OSError and
# the report renderer silently falls back to the pure-Python one).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 libglib2.0-0 \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 libfontconfig1 \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y opencv-python 2>/dev/null || true

# Bake the PP-OCRv4 ONNX weights into the image so the first scan does not wait on a
# ~180 MB download (and works even if the host blocks outbound during a request).
RUN python -c "from rapidocr import RapidOCR; RapidOCR()"

COPY backend/ ./
COPY rules/ ./rules/

RUN chmod +x ./entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
