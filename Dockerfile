FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot.py .

ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "bot.py"]
