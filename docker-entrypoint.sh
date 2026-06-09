#!/bin/sh
set -e

# 如果持久化目录下没有 config.yaml，将代码库中的默认模板复制过去
if [ ! -f /app/data/config.yaml ]; then
    echo "Initializing default config.yaml in /app/data..."
    mkdir -p /app/data
    cp /app/config.yaml.example /app/data/config.yaml
fi

# 启动 Python 应用程序
exec python main.py
