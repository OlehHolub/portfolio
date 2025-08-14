FROM jupyter/scipy-notebook:latest

# Ставим зависимости для BigQuery и датафреймов
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
