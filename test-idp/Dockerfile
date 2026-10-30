FROM python:3.13-alpine
RUN apk upgrade --no-cache
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY provider.py .
USER 10001:10001
EXPOSE 9000
ENTRYPOINT ["python","provider.py"]

