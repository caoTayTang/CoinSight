ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
WORKDIR /service
COPY agents/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r /tmp/requirements.txt
COPY agents /service/agents
COPY pipeline /service/pipeline
RUN useradd --uid 10001 --create-home service
USER service
EXPOSE 8000
CMD ["python", "-m", "agents.server"]
