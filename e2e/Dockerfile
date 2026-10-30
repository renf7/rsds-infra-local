FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && mkdir /artifacts && chown pwuser:pwuser /artifacts
COPY --chown=pwuser:pwuser test_site.py .
USER pwuser
HEALTHCHECK NONE
CMD ["python", "test_site.py"]
