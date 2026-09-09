# 后端容器：部署到 Render（参考项目同款架构）
FROM python:3.10-slim

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 云端无 Milvus，退化为精确匹配 + 规则/LLM 抽取
ENV USE_MILVUS=false

EXPOSE 8000

# Render 会注入 PORT 环境变量；本地兜底 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
