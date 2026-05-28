FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir python-telegram-bot==13.15

COPY . .

CMD ["python", "main.py"]
