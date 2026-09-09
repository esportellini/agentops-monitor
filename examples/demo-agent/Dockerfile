FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY sdk-python /tmp/sdk-python
RUN pip install --no-cache-dir /tmp/sdk-python \
    && useradd --create-home demo \
    && mkdir -p /app/.demo \
    && chown -R demo:demo /app
COPY --chown=demo:demo examples/demo-agent /app/demo
USER demo
ENTRYPOINT ["python", "/app/demo/run_demo.py"]
