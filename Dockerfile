FROM python:3.12-slim

# 必要なシステムパッケージのインストール (ffmpegは音声再生に必須)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
    curl \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Node.jsのインストール (yt-dlpのJavaScriptランタイム用)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# uvのインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 作業ディレクトリの設定
WORKDIR /app

# 依存関係ファイルのコピー
COPY pyproject.toml requirements.lock ./

# 依存ライブラリのインストール
RUN uv pip install --system -r requirements.lock

# ソースコードと設定ファイルのコピー
COPY . .

# Botの起動
CMD ["python", "main.py"]