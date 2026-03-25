FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p downloads outputs

CMD sh -c 'if [ -n "$YOUTUBE_COOKIES" ]; then echo "$YOUTUBE_COOKIES" > /app/cookies.txt && echo "✅ cookies.txt written"; else echo "⚠️ YOUTUBE_COOKIES not set"; fi && gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 300'
