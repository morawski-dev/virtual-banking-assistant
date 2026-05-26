FROM python:3.12-slim
WORKDIR /app
COPY mock_cb/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY mock_cb /app/mock_cb
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz').read()" || exit 1
CMD ["uvicorn", "mock_cb.main:app", "--host", "0.0.0.0", "--port", "8000"]
