FROM python:3.11-slim

# System dependencies:
#   poppler-utils  → pdf2image (PDF → images)
#   tesseract-ocr  → pytesseract (fallback OCR engine)
#   libgomp1       → OpenMP required by PaddlePaddle / OpenCV
#   libgl1-mesa-glx, libglib2.0-0, libsm6, libxext6, libxrender-dev → OpenCV headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . .

# Install the doctra package and the API dependencies
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart

EXPOSE 10000

CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-10000}
