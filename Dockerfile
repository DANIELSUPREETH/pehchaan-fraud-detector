FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Install dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pehchaan ./pehchaan
COPY tests ./tests
COPY pytest.ini .

CMD ["sh", "-c", "python -m pehchaan.generator && python -m uvicorn pehchaan.api.main:app --host 0.0.0.0 --port ${PORT}"]
