FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get upgrade -y \
    && apt-get purge -y gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall -y virtualenv filelock msgpack urllib3 certifi setuptools \
    && python -m pip uninstall -y pip \
    && rm -rf /root/.cache /ms-playwright/firefox-* /ms-playwright/webkit-* \
    && mkdir /artifacts && chown pwuser:pwuser /artifacts
COPY --chown=pwuser:pwuser test_site.py .
COPY --chown=pwuser:pwuser test_auth.py .
USER pwuser
HEALTHCHECK NONE
CMD ["python", "test_site.py"]
