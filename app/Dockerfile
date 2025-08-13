FROM python:3.11-slim

# Не буферизовать вывод (логи сразу в stdout)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Рабочая директория в контейнере
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY app/ ./

# Настройки для простого старта встроенного сервера Flask
# ВАЖНО: слушать 0.0.0.0 и порт 8000 (на него идёт Traefik)
ENV FLASK_APP=app.py \
    FLASK_ENV=production \
    FLASK_DEBUG=0 \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=8000

# Запуск
CMD ["python", "-m", "flask", "run", "--no-reload", "--no-debugger"]





# COPY app /app

# EXPOSE 8000

# HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
#   CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# CMD ["python", "app.py"]
