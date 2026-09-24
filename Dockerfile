FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN python -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements-lock.txt
COPY . .
RUN .venv/bin/python scripts/build_index.py && useradd -m appuser && chown -R appuser /app
USER appuser
ENV PYTHONPATH=/app
EXPOSE 8501 8502
CMD ["bash", "run_demo.sh"]
