FROM ubuntu:22.04

RUN apt-get update -qq && \
    apt-get install -y -qq sox ffmpeg rclone python3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace

COPY resample.py /resample.py

CMD ["python3", "/resample.py"]
