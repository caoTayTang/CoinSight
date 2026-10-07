FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --timeout 120 --no-cache-dir -r requirements.txt
COPY . ./pipeline
