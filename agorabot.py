import discord
from discord.ext import commands
import requests
from io import BytesIO
import json
import urllib.parse
import yt_dlp
from yt_dlp.utils import DownloadError
import uuid
import yaml
import asyncio
from pydub import AudioSegment
import time
import os
import shutil

intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

base_path = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_path, "config.yaml")
user_character_path = os.path.join(base_path, "user_character.json")
uuid_path = os.path.join(base_path, "uuid.json")
priv_path = os.path.join(base_path, "privilege.yaml")
SAVE_REC_DIR = os.path.join(base_path, "recordings")
SAVE_VIDEO_DIR = os.path.join(base_path, "saved_video")
SAVE_AUDIO_DIR = os.path.join(base_path, "saved_audio")

active_text_channel = None
user_audio = {}

with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)
TOKEN = config["token"]
DEFAULT_CHARACTER = config["default_character_name"]
CHARACTER_MAP = config["character_map"]
VOICEVOX_URL = config["voicevox_url"]
AUDIOPLAY = config["audioplay"]
DOWNLOAD_URL = config["Developper_Mode_**DO_NOT_CHANGE_HERE**"]

async def status():
    if active_text_channel == None:
        await bot.change_presence(activity=discord.Game(name="試運転中"))
    else:
        await bot.change_presence(activity=discord.Game(name="VC接続中"))

def classify_attachment(filename):
    extension = filename.split(".")[-1].lower()
    if extension in ["jpg", "jpeg", "png", "gif"]:
        return "画像"
    elif extension in ["mp4", "mkv", "avi", "mov"]:
        return "動画"
    elif extension in ["pdf", "txt", "doc", "docx"]:
        return "ドキュメント"
    elif extension in ["wav", "mp3", "aac", "flac"]:
        return "音声"
    else:
        return "ファイル"

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if (message.author.bot or not message.guild or active_text_channel != message.channel):
        return
    if message.guild.voice_client and message.guild.voice_client.is_connected():
        if message.content.startswith(bot.command_prefix):
            return
    if message.attachments:
        for attachment in message.attachments:
            file_type = classify_attachment(attachment.filename)
            if file_type == "音声":
                if AUDIOPLAY == True:
                    tts_text = "添付された音声ファイルを再生します"
                    await generate_and_play_tts(message.guild.voice_client, tts_text, CHARACTER_MAP[DEFAULT_CHARACTER])
                    await play_audio_from_url(message.guild.voice_client, attachment.url)
                else:
                    tts_text = "音声ファイル添付"
                    await generate_and_play_tts(message.guild.voice_client, tts_text, CHARACTER_MAP[DEFAULT_CHARACTER])
            else:
                tts_text = f"{file_type}ファイル添付"
                await generate_and_play_tts(message.guild.voice_client, tts_text, CHARACTER_MAP[DEFAULT_CHARACTER])
    elif any(word.startswith("http") for word in message.content.split()):
        await generate_and_play_tts(message.guild.voice_client, "リンク省略", CHARACTER_MAP[DEFAULT_CHARACTER])
    elif any(word.startswith("||") for word in message.content.split()):
        await generate_and_play_tts(message.guild.voice_client, "センシティブ発言", CHARACTER_MAP[DEFAULT_CHARACTER])
    else:
        if str(message.author.id) in user_character:
            character_id = user_character[str(message.author.id)]
        else:
            character_id = CHARACTER_MAP[DEFAULT_CHARACTER]
        await generate_and_play_tts(message.guild.voice_client, message.content, character_id)

async def generate_and_play_tts(voice_client, text, character_id):
    try:
        encoded_text = urllib.parse.quote(text)
        query_response = requests.post(f"{VOICEVOX_URL}/audio_query?text={encoded_text}&speaker={character_id}")
        query_response.raise_for_status()
        audio_query = query_response.json()

        synthesis_response = requests.post(f"{VOICEVOX_URL}/synthesis?speaker={character_id}&enable_interrogative_upspeak=true",json=audio_query,)
        synthesis_response.raise_for_status()
        audio_data = BytesIO(synthesis_response.content)
        while voice_client.is_playing():
            await asyncio.sleep(0.5)
        voice_client.play(discord.FFmpegPCMAudio(audio_data, pipe=True))
    
    except AttributeError:
        return

    except Exception as e:
        await active_text_channel.send("ズモモエラー！！TTS生成のエラーが出たぞ！人間！対応しろ！")
        print(f"ttsエラー({query_response.status_code}): {e}")
        print(f"ttsエラー({synthesis_response.status_code}): {e}")

async def play_audio_from_url(voice_client, url):
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        audio_data = BytesIO(response.content)
        while voice_client.is_playing():
            await asyncio.sleep(0.5)
        voice_client.play(discord.FFmpegPCMAudio(audio_data, pipe=True))

    except Exception as e:
        await active_text_channel.send(f"ズモモエラー！！音声ファイル再生のエラーが出たぞ！人間！対応しろ！: {e}")
        print(f"音声ファイル再生エラー: {e}")

@bot.command()
async def join(ctx):
    global active_text_channel
    global voice_channel
    global user_character
    voice_channel = ctx.author.voice.channel
    for vc in bot.voice_clients:
        if vc.guild != ctx.guild:
            await ctx.send("ボットは別のサーバーのVCに接続しており、現在利用できません。後ほど再接続してください。")
            await vc.disconnect()
            active_text_channel = None
            await vc.send("別のサーバーからの接続が試みられたため、システム保護のため切断されました。使用を継続するには再接続してください。")
            return
    if ctx.voice_client:
        await ctx.voice_client.move_to(voice_channel)
        await ctx.send(f"ボイスチャンネル「 {voice_channel.name} 」に移動しました！ｷﾀ━━━━(ﾟ∀ﾟ)━━━━!!")
        active_text_channel = ctx.channel
        with open(user_character_path, "r", encoding="utf-8") as f:
            user_character = json.load(f)
        await status()
        await generate_and_play_tts(ctx.voice_client, "接続しました", CHARACTER_MAP[DEFAULT_CHARACTER])
    else:
        await voice_channel.connect()
        await ctx.send(f"ボイスチャンネル「 {voice_channel.name} 」に接続しました！ｷﾀ━━━━(ﾟ∀ﾟ)━━━━!!")
        active_text_channel = ctx.channel
        with open(user_character_path, "r", encoding="utf-8") as f:
            user_character = json.load(f)
        await status()
        await generate_and_play_tts(ctx.voice_client, "接続しました", CHARACTER_MAP[DEFAULT_CHARACTER])
    
@bot.command()
async def leave(ctx):
    global active_text_channel
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("切断しました！─=≡Σ((( つ•̀ω•́)つ")
        active_text_channel = None
        await status()
    else:
        await ctx.send("このコマンドを実行するには、botがボイスチャンネルに接続されている必要があります。")

@bot.command()
async def stop(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("再生を停止しました。")
    else:
        await ctx.send("再生中の音声がありません。")

@bot.command()
async def audioplay(ctx, state: str):
    if state == "true":
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["audioplay"] = True
        with open(config_path, mode="w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, indent=4)
            await ctx.send(f"音声ファイルの再生設定を「再生する」に変更しました。")
        return
    if state == "false":
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["audioplay"] = False
        with open(config_path, mode="w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, indent=4)
            await ctx.send(f"音声ファイルの再生設定を「再生しない」に変更しました。")
        return
    else:
        await ctx.send("無効な設定です。有効な値: true または false")

@bot.command()
async def set(ctx, character_name: str):
    global user_character_map
    if character_name not in CHARACTER_MAP:
        await ctx.send(f"キャラクター名「{character_name}」は存在しません。有効なキャラクターを指定/config.yamlを確認してください。")
    else:
        with open(user_character_path, "r", encoding="utf-8") as f:
            user_character_map = json.load(f)
        user_character_map[str(ctx.author.id)] = CHARACTER_MAP[character_name]
        with open(user_character_path, "w", encoding="utf-8") as f:
            json.dump(user_character_map, f, ensure_ascii=False, indent=4)
        await ctx.send(f"キャラクターを「{character_name}」に設定しました。")

@bot.command()
async def add(ctx, word: str, pronunciation: str):
    try:
        with open(uuid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        new_data = {"surface": word,"pronunciation": pronunciation,"accent_type": 0,}
        response = requests.post(f"{VOICEVOX_URL}/user_dict_word", params=new_data)
        response.raise_for_status()
        uuid = json.loads(response.text)
        if response.status_code == 200:
            data[word] = uuid
            with open(uuid_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            await ctx.send(f"`{word}` を `{pronunciation}`として登録しました。")
        else:
            await ctx.send(f"単語登録に失敗しました(ステータスコード{response.status_code})。各パラメーターが正しく入力されているか確認してください(特にカタカナ読み)。")
    except Exception as e:
        await ctx.send("ズモモエラー！！辞書追加のエラーが出たぞ！人間！対応しろ！")
        print(f"addエラー({response.status_code}): {e}")

@bot.command()
async def delete(ctx, word: str):
    try:
        with open(uuid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        response = requests.delete(f"{VOICEVOX_URL}/user_dict_word/{data[word]}")
        response.raise_for_status()
        if response.status_code == 204:
            del data[word]
            with open(uuid_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            await ctx.send(f"`{word}` を辞書から削除しました。")
        else:
            await ctx.send(f"単語削除に失敗しました(ステータスコード{response.status_code})。単語が正しく入力されているか確認してください。")
    except Exception as e:
        await ctx.send("ズモモエラー！！辞書削除のエラーが出たぞ！人間！対応しろ！")
        print(f"deleteエラー({response.status_code}): {e}")

@bot.command()
async def save(ctx, param: str, url: str):
    try:
        filename = str(uuid.uuid4())
        if param == "video":
            await ctx.send("動画のダウンロードを開始しました。しばらくお待ちください...") 
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                'outtmpl': f'{SAVE_VIDEO_DIR}/{filename}.%(ext)s',
                'merge_output_format': 'mp4',
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            path = f"{SAVE_VIDEO_DIR}/{filename}.mp4"
            if DOWNLOAD_URL == True:
                with open(priv_path, encoding="utf-8") as f:
                    privilege = yaml.safe_load(f)
                new_path = privilege["save_download_dir"]
                url = privilege["share_video_url"]
                shutil.move(path, new_path)
                await ctx.send(f"""
以下のURLからダウンロードしてください。
{url}/{filename}.mp4
""")
                return
            else:
                await ctx.send(f"ダウンロードしたデータがサーバーに保存されました。")
                return

        if param == "audio":
            await ctx.send("音声のダウンロードを開始しました。しばらくお待ちください...") 
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{SAVE_AUDIO_DIR}/{filename}.%(ext)s',
                'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192', 
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            path = f"{SAVE_AUDIO_DIR}/{filename}.mp4"
            if DOWNLOAD_URL == True:
                with open(priv_path, encoding="utf-8") as f:
                    privilege = yaml.safe_load(f)
                new_path = privilege["save_download_dir"]
                url = privilege["share_audio_url"]
                shutil.move(path, new_path)
                await ctx.send(f"""
以下のURLからダウンロードしてください。
{url}/{filename}.mp3
""")
                return
            else:
                await ctx.send(f"ダウンロードしたデータがサーバーに保存されました。")
                return
        else:
            await ctx.send("適切なパラメーターを指定してください。詳細は `!help` で確認してください。")
    except DownloadError:
        await ctx.send("無効なURLです。動画が利用可能か、URLが正しく入力されているか確認してください。")
    except Exception as e:
        await active_text_channel.send("ズモモエラー！！YouTube保存のエラーが出たぞ！人間！対応しろ！")
        print(f"yt_dlpエラー: {e}")

async def finished_callback(sink: discord.sinks.MP3Sink, ctx: discord.ApplicationContext):
    for user_id, audio in sink.audio_data.items():
        member = ctx.guild.get_member(user_id)
        display_name = member.display_name if member else str(user_id)
        safe_name = "_".join(display_name.split())
        song = AudioSegment.from_file(audio.file, format="mp3")
        song.export(f"{SAVE_REC_DIR}/{safe_name}.mp3", format="mp3")
        duration_ms = end_time - start_time
        def add_silence_to_mp3(SAVE_REC_DIR, duration_ms):
            for filename in os.listdir(SAVE_REC_DIR):
                if filename.lower().endswith(".mp3"):
                    filepath = os.path.join(SAVE_REC_DIR, filename)
                    audio = AudioSegment.from_mp3(filepath)
                    audio_length = len(audio) / 1000
                    if audio_length < duration_ms:
                        silence_duration = int((duration_ms - audio_length) * 1000)
                        silence = AudioSegment.silent(duration=silence_duration)
                        new_audio = silence + audio
                        new_audio.export(filepath, format="mp3")
        add_silence_to_mp3(SAVE_REC_DIR, duration_ms)
    await active_text_channel.send("録音データの合成完了！`!output`を実行してください。")

@bot.command()
async def rec(ctx):
    global start_time
    for file in os.listdir(SAVE_REC_DIR):
        file_path = os.path.join(SAVE_REC_DIR, file)
        os.remove(file_path)
        print(f"deleted'{file_path}'")
        user_audio.clear()
    if ctx.voice_client:
        start_time = int(time.time())
        ctx.voice_client.start_recording(discord.sinks.MP3Sink(), finished_callback, ctx)
        await ctx.send("録音を開始しました。")
    else:
        await ctx.send("ボイスチャンネルに接続してからコマンドを実行してください！")

@bot.command()
async def recstop(ctx):
    global end_time
    end_time  = int(time.time())
    ctx.voice_client.stop_recording()
    await ctx.send("録音を終了しました。音声を合成中...")

@bot.command()
async def output(ctx, display_name: str):
    if display_name.lower() == "merge":
        mp3_files = [f for f in os.listdir(SAVE_REC_DIR) if f.endswith(".mp3") and f != "merged.mp3"]
        if not mp3_files:
            await ctx.send("録音データが見つかりません。")
            return
        base = AudioSegment.silent(duration=0)
        for mp3 in mp3_files:
            audio = AudioSegment.from_file(os.path.join(SAVE_REC_DIR, mp3))
            if len(base) < len(audio):
                base = base + AudioSegment.silent(duration=len(audio) - len(base))  # 長さを調整
            else:
                audio = audio + AudioSegment.silent(duration=len(base) - len(audio))
            base = base.overlay(audio)  # オーバーレイ
        output_path = os.path.join(SAVE_REC_DIR, "merged.mp3")
        base.export(output_path, format="mp3")
        await ctx.send(file=discord.File(os.path.join(SAVE_REC_DIR, "merged.mp3")))
        return
    elif display_name.lower() == "all":
        files = [f for f in os.listdir(SAVE_REC_DIR) if f.endswith(".mp3")]
        for file in files:
            await ctx.send(file=discord.File(os.path.join(SAVE_REC_DIR, file)))
        return
    else:
        file_path = os.path.join(SAVE_REC_DIR, f"{display_name}.mp3")
        if os.path.exists(file_path):
            await ctx.send(file=discord.File(file_path))
            return
        else:
            await ctx.send(f"{display_name}.mp3 が見つかりません。指定したユーザー名が間違っているか、存在しない可能性があります。")
    await ctx.send(f"{display_name}.mp3 が見つかりません。指定したユーザー名が間違っているか、存在しない可能性があります。")
    
@bot.command()
async def help(ctx):
    help_message = """
    **使用可能なコマンド一覧**:
    `!join`: ボイスチャンネルに接続・移動

    `!leave`: ボイスチャンネルから切断

    `!stop`: 再生中の音声を停止

    `!audioplay <true|false>`: 添付された音声ファイルの再生設定を変更
        true: 再生する
        false: 再生しない

    `!set <キャラクター名>`: あなたのキャラクターを設定

    `!add <単語> <カタカナ読み>`: 辞書に単語の読み方を登録

    `!delete <単語>`: 辞書から単語の読み方を削除

    `!save <video|audio> <url>`: YouTubeから音声/動画をダウンロード
        audio: 音声をダウンロード
        video: 動画をダウンロード
    `!rec`: ボイスチャンネルの録音を開始

    `!recstop`: ボイスチャンネルの録音を停止

    `!output <<ユーザー表示名>|all|merge>`: 録音した音声を出力
        ユーザー表示名: 特定のユーザーの録音音声を出力
            ※ただしユーザー表示名に空白が含まれる場合はアンダーバー"_"を使用すること。
        all: 全ユーザーの録音音声を出力
        merge: 全ユーザーの録音音声を1つにまとめて出力

    `!help`: このヘルプを表示
    """
    await ctx.send(help_message)
    
@bot.event
async def on_ready():
    print(f"Botは[{bot.user}]としてログインしました。スタンバイ完了。")
    await status()
    
@bot.event
async def on_voice_state_update(member, before, after):
    global active_text_channel
    if before.channel != after.channel:
        if member.bot:
            return
        if before.channel is None and after.channel is not None and active_text_channel != None:
            await generate_and_play_tts(discord.utils.get(bot.voice_clients, guild=after.channel.guild), f"{member.display_name}さんが入室しました", CHARACTER_MAP[DEFAULT_CHARACTER])
        if before.channel is not None and after.channel is None and active_text_channel != None:
            members = [m for m in before.channel.members if not m.bot]
            if len(members) > 0:
                await generate_and_play_tts(discord.utils.get(bot.voice_clients, guild=before.channel.guild), f"{member.display_name}さんが退室しました", CHARACTER_MAP[DEFAULT_CHARACTER])
            else:
                vc: discord.VoiceClient = discord.utils.get(bot.voice_clients, guild=member.guild)
                await vc.disconnect()
                active_text_channel = None
                await status()

@audioplay.error
async def add_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("適切なパラメーターを指定してください。詳細は `!help` で確認してください。")

@add.error
async def add_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("適切なパラメーターを指定してください。詳細は `!help` で確認してください。")

@delete.error
async def deldic_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("適切なパラメーターを指定してください。詳細は `!help` で確認してください。")

@save.error
async def save_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("適切なパラメーターを指定してください。詳細は `!help` で確認してください。")

@output.error
async def save_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("適切なパラメーターを指定してください。詳細は `!help` で確認してください。")

bot.run(TOKEN)
