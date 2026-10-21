# Existing local predictor image supplies the validated A2A/MCP/numeric runtime.
ARG BASE_IMAGE=coinsight-local-agents:0.1.0
FROM ${BASE_IMAGE}
USER root
COPY warehouse_agents/requirements.lock /tmp/warehouse-requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 3 -r /tmp/warehouse-requirements.txt
COPY warehouse_agents /service/warehouse_agents
USER service
CMD ["python", "-m", "warehouse_agents.server"]
