FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tor curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data

EXPOSE 8110
ENTRYPOINT ["/entrypoint.sh"]
