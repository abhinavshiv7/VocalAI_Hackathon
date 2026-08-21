FROM golang:1.24-alpine AS httpx-builder
RUN go install github.com/projectdiscovery/httpx/cmd/httpx@v1.7.1

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends nmap ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=httpx-builder /go/bin/httpx /usr/local/bin/httpx
COPY backend ./
COPY evaluation /workspace/evaluation
RUN mkdir -p data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
