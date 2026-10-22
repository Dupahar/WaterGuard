FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 WATERGUARD_DATA=/data WATERGUARD_TELEMETRY=1
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -c "import whitebox; whitebox.WhiteboxTools().version()"

COPY waterguard/ waterguard/
COPY web/ web/
COPY contracts/ contracts/
# the container has no git history: the analysis-code version that names reports on the ledger
ARG WATERGUARD_VERSION
ENV WATERGUARD_VERSION=${WATERGUARD_VERSION}

EXPOSE 8000
CMD ["uvicorn", "waterguard.server:app", "--host", "0.0.0.0", "--port", "8000"]
