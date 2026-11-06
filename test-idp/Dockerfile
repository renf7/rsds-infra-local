FROM python:3.15.2-alpine
RUN apk upgrade --no-cache
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.15/ensurepip
COPY provider.py .
USER 10001:10001
EXPOSE 9000
ENTRYPOINT ["python","provider.py"]

