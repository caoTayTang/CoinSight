FROM apache/airflow:3.3.2-python3.12

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
COPY create_metadata_db.py /opt/airflow/create_metadata_db.py

COPY requirements-tracing.txt /requirements-tracing.txt
RUN pip install --timeout 120 --no-cache-dir -r /requirements-tracing.txt && pip check
