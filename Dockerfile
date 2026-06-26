FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector.py config.py ./
COPY adapters ./adapters

RUN mkdir -p /app/config /app/data/sungrow /app/data/huawei /app/logs

CMD ["python", "collector.py"]
