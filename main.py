import discord
from discord.ext import commands
import requests
from io import BytesIO
import json
import yt_dlp
from yt_dlp.utils import DownloadError
import uuid
import yaml
import asyncio
import urllib.parse
import shutil
from gtts import gTTS
from datetime import datetime
from pathlib import Path
import os
import sys
import logging
from dotenv import load_dotenv
import audioop
import threading

# ---------------------------------------------------------
# ログ設定
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# ---------------------------------------------------------
# 設定と初期化
# ---------------------------------------------------------
BASE_PATH = Path(__file__).parent
CONFIG_PATH = BASE_PATH / "config.yaml"
USER_CHAR_PATH = BASE_PATH / "user_character.json"
DICT_PATH = BASE_PATH / "user_dict.json"
VIDEO_DIR = BASE_PATH / "saved_video"
AUDIO_DIR = BASE_PATH / "saved_audio"
OUTPUT_WAV_PATH = BASE_PATH / "output.wav"

load_dotenv(BASE_PATH / ".env")

for dir_path in [VIDEO_DIR, AUDIO_DIR]:
    dir_path.mkdir(exist_ok=True)

if not CONFIG_PATH.exists():
    logging.critical(f"設定ファイルが見つかりません: {CONFIG_PATH}")
    sys.exit(1)

try:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
except Exception as e:
    logging.critical(f"Config読み込みエラー: {e}")
    sys.exit(1)

TOKEN = config["token"]
DEFAULT_CHARACTER = config["default_character_name"]
CHARACTER_MAP = config["character_map"]
AUDIOPLAY = config["audioplay"]
DEVELOPER_MODE = config.get("developer_mode_**DO_NOT_CHANGE_HERE**", False)
VOICEVOX_URL = config["VOICEVOX_URL"]
# メンテナンスモードの設定読み込み (デフォルトはFalse)
MAINTENANCE_MODE = config.get("maintenance_mode", False)

# ---------------------------------------------------------
# 起動チェック
# ---------------------------------------------------------
if DEVELOPER_MODE:
    if not (BASE_PATH / ".env").exists():
        logging.critical("必要なファイルが不足しています: .envファイルが見つかりません。(Developer Mode)")
        sys.exit(1)

# ---------------------------------------------------------
# ミキシング用クラス (音声合成)
# ---------------------------------------------------------
class MixingAudioSource(discord.AudioSource):
    def __init__(self, main_source=None):
        self.sources = []
        self.lock = threading.Lock()
        if main_source:
            self.add_source(main_source)

    def add_source(self, source):
        with self.lock:
            self.sources.append(source)

    def read(self):
        FRAME_SIZE = 3840
        mixed = None
        
        with self.lock:
            active_sources = self.sources[:]
            if not active_sources:
                return b'\x00' * FRAME_SIZE

            for source in active_sources:
                chunk = source.read()
                if not chunk:
                    self.sources.remove(source)
                    if hasattr(source, 'cleanup'):
                        source.cleanup()
                    continue
                
                if len(chunk) < FRAME_SIZE:
                    chunk += b'\x00' * (FRAME_SIZE - len(chunk))
                
                try:
                    if mixed is None:
                        mixed = chunk
                    else:
                        mixed = audioop.add(mixed, chunk, 2)
                except Exception:
                    pass
                    
        return mixed if mixed is not None else b'\x00' * FRAME_SIZE

    def cleanup(self):
        for source in self.sources:
            if hasattr(source, 'cleanup'):
                source.cleanup()

def play_mixed(voice_client, new_source):
    if voice_client.is_playing():
        if isinstance(voice_client.source, MixingAudioSource):
            voice_client.source.add_source(new_source)
        else:
            current_source = voice_client.source
            voice_client.pause()
            mixer = MixingAudioSource(current_source)
            mixer.add_source(new_source)
            voice_client.source = mixer
            voice_client.resume()
    else:
        voice_client.play(new_source)

# ---------------------------------------------------------
# Bot設定
# ---------------------------------------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

active_text_channel = None
user_character = {}

today = datetime.now()
AprilFool = (today.month == 4 and today.day == 1)

async def update_status():
    if active_text_channel is None:
        if MAINTENANCE_MODE:
            await bot.change_presence(status=discord.Status.dnd, activity=discord.Game(name="メンテナンス中"))
        else:
            await bot.change_presence(activity=discord.Game(name="スタンバイ"))
    else:
        if MAINTENANCE_MODE:
             await bot.change_presence(status=discord.Status.dnd, activity=discord.Game(name="メンテナンス中"))
        else:
             await bot.change_presence(activity=discord.Game(name="VC接続中"))

def classify_attachment(filename):
    extension = filename.split(".")[-1].lower()
    if extension in ["jpg", "jpeg", "png", "gif"]: return "画像"
    if extension in ["mp4", "mkv", "avi", "mov"]: return "動画"
    if extension in ["pdf", "txt", "doc", "docx"]: return "ドキュメント"
    if extension in ["wav", "mp3", "aac", "flac"]: return "音声"
    return "ファイル"

# ---------------------------------------------------------
# イベント
# ---------------------------------------------------------
@bot.event
async def on_ready():
    logging.info(f"Botは[{bot.user}]としてログインしました。スタンバイ完了。")
    if MAINTENANCE_MODE:
        logging.warning("現在メンテナンスモードで動作しています。")
    await update_status()

@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author.bot:
        return

    # メンテナンスモード時の処理
    if MAINTENANCE_MODE:
        # コマンドプレフィックスで始まる場合のみ警告を返す
        # (普通の会話すべてに反応するとうるさいため)
        if message.content.startswith(bot.command_prefix):
            await message.channel.send("現在メンテナンス中のため使用できません")
        # メンテナンス中はここで処理終了（コマンド実行も読み上げもしない）
        return

    # 以下、通常時の処理
    await bot.process_commands(message)

    if (not message.guild or 
        active_text_channel != message.channel):
        return
    
    if not (message.guild.voice_client and message.guild.voice_client.is_connected()):
        return

    if message.content.startswith(bot.command_prefix):
        return

    tts_text = ""
    try:
        if message.attachments:
            for attachment in message.attachments:
                file_type = classify_attachment(attachment.filename)
                if file_type == "音声":
                    if AUDIOPLAY:
                        tts_text = "添付された音声ファイルを再生します"
                        await generate_and_play_tts(message.guild.voice_client, tts_text, CHARACTER_MAP[DEFAULT_CHARACTER])
                        await play_audio_from_url(message.guild.voice_client, attachment.url)
                        return
                    else:
                        tts_text = "音声ファイル添付"
                else:
                    tts_text = f"{file_type}ファイル添付"
        elif any(word.startswith("http") for word in message.content.split()):
            tts_text = "リンク省略"
        elif any(word.startswith("||") for word in message.content.split()):
            tts_text = "センシティブ発言"
        else:
            tts_text = message.content

        if not tts_text:
            return

        user_id = str(message.author.id)
        style_id = user_character.get(user_id, CHARACTER_MAP[DEFAULT_CHARACTER])
        
        await generate_and_play_tts(message.guild.voice_client, tts_text, style_id)

    except Exception as e:
        logging.error(f"on_message Error: {e}")

async def generate_and_play_tts(voice_client, text, character_id):
    if not voice_client or not voice_client.is_connected():
        return

    temp_filename = f"tts_{uuid.uuid4()}.wav"
    temp_path = BASE_PATH / temp_filename

    try:
        if AprilFool:
            tts = gTTS(text, lang="en")
            tts.save(str(temp_path))
        else:
            encoded_text = urllib.parse.quote(text)
            query_res = requests.post(f"{VOICEVOX_URL}/audio_query?text={encoded_text}&speaker={character_id}")
            query_res.raise_for_status()
            audio_query = query_res.json()

            syn_res = requests.post(f"{VOICEVOX_URL}/synthesis?speaker={character_id}&enable_interrogative_upspeak=true", json=audio_query)
            syn_res.raise_for_status()
            
            with open(temp_path, 'wb') as f:
                f.write(syn_res.content)
        
        source = discord.FFmpegPCMAudio(str(temp_path))
        play_mixed(voice_client, source)

    except Exception as e:
        logging.error(f"TTS Error: {e}")
        if active_text_channel:
            await active_text_channel.send("ズモモエラー！！")

async def play_audio_from_url(voice_client, url):
    try:
        res = requests.get(url, stream=True)
        res.raise_for_status()
        audio_data = BytesIO(res.content)
        
        source = discord.FFmpegPCMAudio(audio_data, pipe=True)
        play_mixed(voice_client, source)

    except Exception as e:
        if active_text_channel:
            await active_text_channel.send(f"ズモモエラー！！音声再生エラーだ！")
        logging.error(f"Audio URL Playback Error: {e}")

# ---------------------------------------------------------
# コマンド
# ---------------------------------------------------------
@bot.command()
async def join(ctx):
    global active_text_channel
    global user_character
    
    if not ctx.author.voice:
        await ctx.send("ボイスチャンネルに接続してからコマンドを実行してください。")
        return

    target_channel = ctx.author.voice.channel

    for vc in bot.voice_clients:
        if vc.guild != ctx.guild:
            await ctx.send(f"現在、別のサーバーで使用中のため接続できません。")
            logging.info(f"Join refused: Active in {vc.guild.name}")
            return

    try:
        voice_client = ctx.guild.voice_client

        if voice_client:
            if voice_client.channel != target_channel:
                await voice_client.move_to(target_channel)
                await ctx.send(f"ボイスチャンネル「{target_channel.name}」に移動しました！")
            else:
                await ctx.send(f"既に「{target_channel.name}」に接続しています。")
        else:
            await target_channel.connect()
            await ctx.send(f"ボイスチャンネル「 {target_channel.name} 」に接続しました！ｷﾀ━━━━(ﾟ∀ﾟ)━━━━!!")

        active_text_channel = ctx.channel
        
        if USER_CHAR_PATH.exists():
            try:
                with open(USER_CHAR_PATH, "r", encoding="utf-8") as f:
                    user_character = json.load(f)
            except json.JSONDecodeError:
                user_character = {}
        else:
            user_character = {}

        await update_status()
        await generate_and_play_tts(ctx.guild.voice_client, "接続しました", CHARACTER_MAP[DEFAULT_CHARACTER])

    except Exception as e:
        await ctx.send("接続時にエラーが発生しました。")
        logging.error(f"Join Command Error: {e}")

@bot.command()
async def leave(ctx):
    global active_text_channel
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("切断しました！─=≡Σ((( つ•̀ω•́)つ")
        active_text_channel = None
        await update_status()
    else:
        await ctx.send("Botはボイスチャンネルに接続していません。")

@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.send("再生を停止しました。")
    else:
        await ctx.send("再生中の音声がありません。")

@bot.command()
async def audioplay(ctx, state: str):
    global AUDIOPLAY
    state_bool = state.lower() == "true"
    if state.lower() not in ["true", "false"]:
        await ctx.send("無効な設定です。")
        return

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["audioplay"] = state_bool
        AUDIOPLAY = state_bool
        with open(CONFIG_PATH, mode="w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, indent=4)
        msg = "再生する" if state_bool else "再生しない"
        await ctx.send(f"音声ファイルの再生設定を「{msg}」に変更しました。")
    except Exception as e:
        logging.error(f"Audioplay config error: {e}")

@bot.command()
async def set(ctx, target_name: str, character_name: str):
    global user_character

    # 1. キャラクター名の存在確認
    if character_name not in CHARACTER_MAP:
        await ctx.send(f"キャラクター名「{character_name}」は存在しません。`!char` で一覧を確認してください。")
        return

    # 2. ユーザー（メンバー）の検索
    # サーバー内のメンバーから、表示名(display_name) または ユーザー名(name) が一致する人を探す
    target_member = discord.utils.find(
        lambda m: m.display_name == target_name or m.name == target_name, 
        ctx.guild.members
    )

    if not target_member:
        await ctx.send(f"ユーザー「{target_name}」が見つかりませんでした。\n※名前にスペースが含まれる場合は `\"名前\"` のように引用符で囲ってください。")
        return

    # 3. 設定の保存
    try:
        if USER_CHAR_PATH.exists():
            with open(USER_CHAR_PATH, "r", encoding="utf-8") as f:
                user_character = json.load(f)
        else:
            user_character = {}

        # 見つかったメンバーのIDをキーにして保存
        user_character[str(target_member.id)] = CHARACTER_MAP[character_name]
        
        with open(USER_CHAR_PATH, "w", encoding="utf-8") as f:
            json.dump(user_character, f, ensure_ascii=False, indent=4)
        
        await ctx.send(f"{target_member.display_name} さんのキャラクターを「{character_name}」に設定しました。")
        logging.info(f"Set character for {target_member.display_name}: {character_name}")

    except Exception as e:
        await ctx.send("設定の保存に失敗しました。")
        logging.error(f"Set character error: {e}")

@bot.command()
async def char(ctx):
    # キャラクター名のリストを作成
    char_list = "\n".join([f"・{name}" for name in CHARACTER_MAP.keys()])
    
    embed = discord.Embed(title="使用可能なキャラクター一覧", description=char_list, color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command()
async def add(ctx, word: str, pronunciation: str):
    try:
        if DICT_PATH.exists():
            with open(DICT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}

        new_data = {"surface": word, "pronunciation": pronunciation, "accent_type": 0}
        res = requests.post(f"{VOICEVOX_URL}/user_dict_word", params=new_data)
        res.raise_for_status()
        uuid_val = json.loads(res.text)
        data[word] = uuid_val
        with open(DICT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        await ctx.send(f"`{word}` を `{pronunciation}`として登録しました。")
    except Exception as e:
        await ctx.send("ズモモエラー！！辞書エラーが出たぞ！人間！対応しろ！")
        logging.error(f"Add dictionary error: {e}")

@bot.command()
async def delete(ctx, word: str):
    try:
        if not DICT_PATH.exists():
            await ctx.send(f"`{word}` は辞書に存在しません。")
            return
        with open(DICT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if word not in data:
            await ctx.send(f"`{word}` は辞書に存在しません。")
            return
        res = requests.delete(f"{VOICEVOX_URL}/user_dict_word/{data[word]}")
        res.raise_for_status()
        del data[word]
        with open(DICT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        await ctx.send(f"`{word}` を辞書から削除しました。")
    except Exception as e:
        await ctx.send("ズモモエラー！！辞書エラーが出たぞ！人間！対応しろ！")
        logging.error(f"Delete dictionary error: {e}")

@bot.command()
async def save(ctx, param: str, url: str):
    filename = str(uuid.uuid4())
    # URLドメインに基づくサイト別設定
    domain = urllib.parse.urlparse(url).netloc.lower()

    if param == "video":
        target_dir = VIDEO_DIR
        ext = "mp4"
        # デフォルトは汎用ベスト動画
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'format': 'bestvideo*+bestaudio/best',
            'outtmpl': f'{target_dir}/{filename}.%(ext)s',
            'merge_output_format': 'mp4',
        }
        # Twitter/Xはmp4が多いのでそのままmp4にマージ
        if ('twitter.com' in domain) or ('x.com' in domain):
            ydl_opts.update({
                'format': 'bestvideo*+bestaudio/best/best',
            })
        # SoundCloudは動画がないため音声保存に切り替え
        if ('soundcloud.com' in domain) or ('sndcdn.com' in domain):
            await ctx.send("SoundCloudは動画に非対応のため音声保存に切り替えます。")
            target_dir = AUDIO_DIR
            ext = "mp3"
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'format': 'bestaudio/best',
                'outtmpl': f'{target_dir}/{filename}.%(ext)s',
                'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
            }
    elif param == "audio":
        target_dir = AUDIO_DIR
        ext = "mp3"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'format': 'bestaudio/best',
            'outtmpl': f'{target_dir}/{filename}.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        }
        # SoundCloudはそのまま音声扱いでOK
        # Twitter/Xもbestaudioで抽出し、mp3へ変換
    else:
        await ctx.send("video または audio を指定してください。")
        return

    await ctx.send(f"ダウンロードを開始しました...")

    async with ctx.typing():
        try:
            # ダウンロード実行
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            saved_path = f"{target_dir}/{filename}.{ext}"

            # Nginxが読み取れるようにファイルのパーミッションを変更 (644)
            try:
                os.chmod(saved_path, 0o644)
            except Exception as e:
                logging.warning(f"Permission change failed: {e}")
            
            if DEVELOPER_MODE:
                # .env から共有用URLのベースのみ取得
                env_url_key = f"SHARE_{param.upper()}_URL"
                share_url_base = os.getenv(env_url_key)

                if share_url_base:
                    # URLを結合して表示 (末尾のスラッシュ有無を考慮)
                    share_url = share_url_base.rstrip('/') + f"/{filename}.{ext}"
                    await ctx.send(f"以下のURLからダウンロードできます。\n{share_url}")
                else:
                    logging.warning(f"ENV variable {env_url_key} not found.")
                    await ctx.send("ダウンロード完了。（公開用URL設定が見つかりませんでした）")
            else:
                await ctx.send(f"ダウンロード完了。サーバー内に保存されました。")

        except Exception as e:
            await active_text_channel.send("ズモモエラー！！保存エラーが出たぞ！人間！対応しろ！")
            logging.error(f"Save command error: {e}")

@bot.command()
async def play(ctx, url):
    if not ctx.voice_client:
        await ctx.send("先にボイスチャンネルに接続してください。")
        return

    async with ctx.typing():
        try:
            ydl_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "noplaylist": True,
                "extract_flat": False,
                "no_warnings": True
            }
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            
            if "entries" in data: 
                data = data["entries"][0]
            
            # HTTPヘッダーを構築
            headers = ""
            if "http_headers" in data:
                for key, value in data["http_headers"].items():
                    headers += f"{key}: {value}\r\n"
            
            ffmpeg_opts = {
                "before_options": f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -headers {repr(headers)}",
                "options": "-vn"
            }
            
            await generate_and_play_tts(ctx.voice_client, "リンク先の音声を再生します", CHARACTER_MAP[DEFAULT_CHARACTER])
            
            source = discord.FFmpegPCMAudio(data["url"], **ffmpeg_opts)
            play_mixed(ctx.voice_client, source)
            
        except Exception as e:
            await ctx.send("再生に失敗しました。")
            logging.error(f"Play command error: {e}")

@bot.command()
async def fool(ctx, state: str):
    global AprilFool
    if state == "true": AprilFool = True; await ctx.send(":parrot: :thumbsup:")
    elif state == "false": AprilFool = False; await ctx.send(":angry:")

@bot.command()
async def help(ctx):
    help_message = f"""
    **使用可能なコマンド一覧**
    
    `!join`: ボイスチャンネルに接続・移動

    `!leave`: ボイスチャンネルから切断

    `!stop`: 再生中の音声を停止

    `!audioplay <true|false>`: 添付された音声ファイルの再生設定を変更
        true: 再生する
        false: 再生しない

    `!set <ユーザー名> <キャラクター名>`: あなたのキャラクターを設定

    `!char`: 使用可能なキャラクター名の一覧を表示

    `!add <単語> <カタカナ読み>`: 辞書に単語の読み方を登録

    `!delete <単語>`: 辞書から単語の読み方を削除

    `!save <video|audio> <url>`: YouTubeから音声・動画をダウンロード
        audio: 音声をダウンロード
        video: 動画をダウンロード

    `!play <url>`: YouTubeの音声を再生します

    `!help`: このヘルプを表示
    """
    await ctx.send(help_message)

@bot.event
async def on_voice_state_update(member, before, after):
    global active_text_channel
    if member.bot: return
    try:
        if before.channel is None and after.channel is not None:
            if active_text_channel and after.channel.guild.voice_client:
                 if after.channel == after.channel.guild.voice_client.channel:
                    await generate_and_play_tts(after.channel.guild.voice_client, f"{member.display_name}さんが入室しました", CHARACTER_MAP[DEFAULT_CHARACTER])
        if before.channel is not None and after.channel is None:
            if active_text_channel and before.channel.guild.voice_client:
                if before.channel == before.channel.guild.voice_client.channel:
                    members = [m for m in before.channel.members if not m.bot]
                    if len(members) == 0:
                        await before.channel.guild.voice_client.disconnect()
                        active_text_channel = None
                        await update_status()
                    else:
                        await generate_and_play_tts(before.channel.guild.voice_client, f"{member.display_name}さんが退室しました", CHARACTER_MAP[DEFAULT_CHARACTER])
    except Exception as e:
        logging.error(f"VoiceStateUpdate Error: {e}")

@bot.event
async def on_command_error(ctx, error):
    logging.error(f"Command Error: {error}")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logging.critical(f"Bot起動失敗: {e}")