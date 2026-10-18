FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 WATERGUARD_DATA=/data
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -c "import whitebox; whitebox.WhiteboxTools().version()"

COPY waterguard/ waterguard/
COPY web/ web/
COPY contracts/ contracts/

EXPOSE 8000
CMD ["uvicorn", "waterguard.server:app", "--host", "0.0.0.0", "--port", "8000"]
