FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD gunicorn pos_system.main:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
