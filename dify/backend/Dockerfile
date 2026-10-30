# 《记仇小镇》游戏后端镜像
#
# 镜像里只装后端运行时依赖；数据目录（schema.sql / seed.sql）通过
# volume 挂载进 /app/data，因此改表结构不需要重新构建镜像。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖，利用镜像层缓存。
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY town_backend /app/town_backend

EXPOSE 8848

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8848/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "town_backend"]
