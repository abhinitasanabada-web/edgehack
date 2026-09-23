FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY . .
RUN python scripts/build_index.py && useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app/ui.py", "--server.address=0.0.0.0"]
