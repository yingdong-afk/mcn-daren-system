FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py domain.py extensions.py schema.sql ./
COPY templates ./templates
COPY static ./static
RUN useradd --uid 10001 --create-home mcn && mkdir /data && chown mcn:mcn /data && chmod 700 /data
ENV MCN_INSTANCE_DIR=/data PYTHONUNBUFFERED=1
USER mcn
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--threads=4", "--call", "app:create_app"]
