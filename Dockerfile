FROM python:3.11-slim

# 必要なシステムパッケージのインストール (ffmpegは音声再生に必須)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 作業ディレクトリの設定
WORKDIR /app

# 依存ライブラリのインストール
# 先ほど修正したrequirements.txtを使用します
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ソースコードと設定ファイルのコピー
COPY . .

# Botの起動
CMD ["python", "agorabot.py"]