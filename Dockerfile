FROM python:3.11-slim

# 设置时区与环境变量
ENV TZ=Asia/Shanghai
ENV PORT=8888
ENV CONFIG_PATH=/app/data/config.yaml
ENV DB_PATH=/app/data/myrss.db

WORKDIR /app

# 安装时区支持与基本系统依赖（用于调试或运维）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖定义并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码并配置权限
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

# 暴露服务端口
EXPOSE 8888

# 使用入口点脚本启动
ENTRYPOINT ["/app/docker-entrypoint.sh"]
