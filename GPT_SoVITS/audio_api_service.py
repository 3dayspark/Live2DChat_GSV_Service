
import base64
import re
import os
import json
import time
import shutil
import struct
import logging
import asyncio
from typing import List, Dict, Optional, Any
from xml.etree import ElementTree

# 環境変数の設定: HuggingFaceとTransformersのオフラインモードを強制
# オンライン接続によるGSVの遅延（ラグ）を防ぐための設定
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import soundfile as sf
import numpy as np
import requests
import edge_tts

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

# キャラクター設定とプロセス管理のインポート
from api_character_loader import CharacterAttributes
from gptsovits_process_manager import GPTSovitsProcessManager

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# プロセス管理マネージャー（fastapi_main.pyで初期化される想定）
global_gptsovits_manager: GPTSovitsProcessManager = None
_global_emotion_model: Any = None

# 外部サービスURL設定
GEMINI_TTS_URL = "https://asynchronousblocking.asia/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"
RVC_SERVICE_URL = "http://127.0.0.1:8001/rvc_convert"  # RVC FastAPIサービスのポート設定を確認すること

# Azure TTS 関連設定
AZURE_TTS_REGION = "japanwest"
AZURE_TTS_ENDPOINT = f"https://{AZURE_TTS_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
AZURE_TTS_TOKEN_URL = f"https://{AZURE_TTS_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
AZURE_TTS_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
AZURE_TTS_OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
AZURE_TTS_USER_AGENT = "Chat_backend"


def parse_audio_mime_type(mime_type: str) -> dict[str, Optional[int]]:
    """MIMEタイプから音声パラメータを解析するヘルパー関数"""
    bits_per_sample = 16
    rate = 24000
    return {"bits_per_sample": bits_per_sample, "rate": rate}


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """PCMデータをWAVフォーマットに変換する"""
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",          # ChunkID
        chunk_size,       # ChunkSize
        b"WAVE",          # Format
        b"fmt ",          # Subchunk1ID
        16,               # Subchunk1Size (PCM)
        1,                # AudioFormat (PCM)
        num_channels,     # NumChannels
        sample_rate,      # SampleRate
        byte_rate,        # ByteRate
        block_align,      # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",          # Subchunk2ID
        data_size         # Subchunk2Size
    )
    return header + audio_data


class SimpleAudioGenerator:
    """音声生成ロジックを管理するクラス"""

    def __init__(self, character_list: List[CharacterAttributes]):
        self.character_list = character_list
        
        # 絶対パスの構築
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.ref_audio_file_white_sakiko = os.path.join(base_dir, "..", "reference_audio", "sakiko", "white_sakiko.wav")
        self.ref_audio_file_black_sakiko = os.path.join(base_dir, "..", "reference_audio", "sakiko", "black_sakiko.wav")
        self.ref_text_file_white_sakiko = os.path.join(base_dir, "..", "reference_audio", "sakiko", "reference_text_white_sakiko.txt")
        self.ref_text_file_black_sakiko = os.path.join(base_dir, "..", "reference_audio", "sakiko", "reference_text_black_sakiko.txt")

        # 前処理用置換ルール
        # 日本語合成時の読み間違い（人名など）を修正する辞書
        self.replacements_jap = {
            '豊川祥子': 'とがわさきこ',
            '祥子': 'さきこ',
            '三角初華': 'みすみういか',
            '初華': 'ういか',
            '若葉睦': 'わかばむつみ',
            '睦': 'むつみ',
            '八幡海鈴': 'やはたうみり',
            '海鈴': 'うみり',
            '海铃': 'うみり',
            '祐天寺': 'ゆうてんじ',
            '若麦': 'にゃむ',
            '喵梦': 'にゃむ',
            '高松燈':'たかまつともり',
            '燈':'ともり',
            '灯': 'ともり',
            '椎名立希':'しいなたき',
            '莉莎':'リサ',
            '愛音':'アノン',
            '素世': 'そよ',
            '爽世': 'そよ',
            '千早愛音':'ちはやアノン',
            '爱音': 'アノン',
            '要楽奈':'かなめらーな',
            '楽奈': 'らーな',
            '春日影':'はるひかげ',
            'Doloris':'ドロリス',
            'Mortis':'モーティス',
            'Timoris':'ティモリス',
            'Amoris':'アモーリス',
            'Oblivionis':'オブリビオニス',
            'live':'ライブ',
            'RiNG':'リング',
            '珠手知由':'たまでちゆ',
            'CHUCHU':'チュチュ',
            'CHU²':'チュチュ',
            'CHU2':'チュチュ',
            '友希那':'ゆきな',
            '纱夜':'サヨ',
            '牛肉干':'ジャーキー',
            'Roselia':'ロゼリア',
            '垃圾桶':'ゴミ箱',
            '髪型':'かみがた',
            '髪型':'かみがた',
            'RAISE A SUILEN':'レイズアスイレン',
            'Senior Yukina':'ゆきな先輩',
            'MyGO!!!!!':'まいご'
        }
        self.replacements_chi ={
            'CRYCHIC':'C团',
            'live':"演出",
            'RiNG':"ring",
            'Doloris': '初华',
            'Mortis': '睦',
            'Timoris': '海铃',
            'Amoris': '喵梦',
            'Oblivionis': '我',
            'MyGO':'mygo',
            'ちゃん':'',
            'CHU²':'楚楚',
            'CHU2':'楚楚'
        }
        self.replacements_yue = {
            '丰川祥子': 'fung1 cyun1 coeng4 zi2',
            '祥子': 'coeng4 zi2',
            '睦': 'muk6',
            '爱音': 'oi3 jam1',
            '千早爱音': 'cin1 zou2 oi3 jam1',
            '立希': 'lap6 hei1',
            '椎名立希': 'ceoi1 naa4 lap6 hei1',
            '爽世': 'song2 sai3',
            '要乐奈': 'jiu3 lok6 naa4',
            '乐奈': 'lok6 naa4',
            '春日影':'har1 jat6 jing2',
            'CRYCHIC': 'klai4 sik1',
            'Ave Mujica': 'aai1 wai1 muk6 zi1 gaa3',
            'Doloris': 'do1 lo4 lei6 si1',
            'Mortis': 'muk6 ti4 si1',
            'Timoris': 'ti4 mo1 lei6 si1',
            'Amoris': 'aa3 mo1 lei6 si1',
            'Oblivionis': 'o1 bi1 lip6 bi1 o1 nis1',
            'live': 'laai1 fuk6',
            'MyGO': 'mai5 go1',
            'RiNG': 'ring1',
        }

        self.GEMINI_API_KEY = None
        self.generated_audio_folder = os.path.join(base_dir, "..", "reference_audio", "generated_audios_temp")
        os.makedirs(self.generated_audio_folder, exist_ok=True)

        # Edge TTS 設定
        self.EDGE_TTS_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
        self.EDGE_TTS_DEFAULT_RATE = "+0%"
        self.EDGE_TTS_DEFAULT_VOLUME = "+0%"

        # Azure TTS 設定
        self.AZURE_TTS_SUBSCRIPTION_KEY = None
        self.azure_tts_access_token = None
        self.azure_tts_token_expiry_time = 0

        self.last_gemini_request_time = 0
        self.gemini_request_interval = 2  # レート制限防止用のインターバル（秒）
        self.edge_tts_lock = asyncio.Lock()

    async def load_gemini_api_key(self):
        """API Key.txt から Gemini API キーを読み込む"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        key_file_path = os.path.join(script_dir, "..", "API Key.txt")
        try:
            with open(key_file_path, "r", encoding="utf-8") as f:
                self.GEMINI_API_KEY = f.read().strip()
            logger.info("Gemini API Key loaded successfully.")
        except FileNotFoundError:
            logger.error(f"ERROR: API Key file not found at {key_file_path}. Gemini TTS will not work.")
            self.GEMINI_API_KEY = None
        except Exception as e:
            logger.error(f"ERROR loading Gemini API Key: {e}")
            self.GEMINI_API_KEY = None

    async def load_azure_tts_subscription_key(self):
        """API Key_Azure.txt から Azure TTS キーを読み込む"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        azure_key_file_path = os.path.join(script_dir, "..", "API Key_Azure.txt")
        logger.info(f"Attempting to load Azure TTS key from: {azure_key_file_path}")
        try:
            with open(azure_key_file_path, "r", encoding="utf-8") as f:
                azure_key = f.read().strip()
                if azure_key:
                    self.AZURE_TTS_SUBSCRIPTION_KEY = azure_key
                    logger.info("Azure TTS Subscription Key loaded successfully.")
                else:
                    logger.warning(f"'{azure_key_file_path}' is empty. Azure TTS will not work.")
        except FileNotFoundError:
            logger.error(f"ERROR: Azure TTS Key file not found at {azure_key_file_path}. Azure TTS will not work.")
            self.AZURE_TTS_SUBSCRIPTION_KEY = None
        except Exception as e:
            logger.error(f"ERROR loading Azure TTS Subscription Key: {e}")
            self.AZURE_TTS_SUBSCRIPTION_KEY = None

    async def _get_azure_tts_access_token(self):
        """Azure TTSのアクセストークンを取得または更新する"""
        if not self.AZURE_TTS_SUBSCRIPTION_KEY:
            raise RuntimeError("Azure TTS Subscription Key is not loaded.")

        if self.azure_tts_access_token and not self._is_azure_tts_token_expired():
            return self.azure_tts_access_token

        try:
            headers = {
                'Ocp-Apim-Subscription-Key': self.AZURE_TTS_SUBSCRIPTION_KEY
            }
            response = requests.post(AZURE_TTS_TOKEN_URL, headers=headers, timeout=10)
            response.raise_for_status()
            self.azure_tts_access_token = str(response.text)
            self.azure_tts_token_expiry_time = time.time() + 9 * 60  # 有効期限（通常10分）より早めに更新
            logger.info("Azure TTS Access Token acquired successfully.")
            return self.azure_tts_access_token
        except requests.exceptions.RequestException as e:
            logger.error(f"Error acquiring Azure TTS Access Token: {e}")
            if hasattr(response, 'text'):
                logger.error(f"Azure TTS Token Error Response: {response.text}")
            raise RuntimeError(f"Failed to acquire Azure TTS Access Token: {e}")

    def _is_azure_tts_token_expired(self):
        """トークンの有効期限を確認する"""
        return not self.azure_tts_access_token or time.time() >= self.azure_tts_token_expiry_time

    def _cleanup_generated_audios_temp(self):
        """一時音声フォルダのクリーンアップを行う"""
        logger.info(f"Cleaning up temporary audio files in: {self.generated_audio_folder}")
        try:
            for filename in os.listdir(self.generated_audio_folder):
                if filename.endswith(".wav") or filename.endswith(".txt"):
                    file_path = os.path.join(self.generated_audio_folder, filename)
                    try:
                        os.remove(file_path)
                        logger.debug(f"Removed temporary file: {filename}")
                    except OSError as e:
                        logger.warning(f"Error removing temporary file {filename}: {e}")
        except Exception as e:
            logger.error(f"Error during cleanup of generated_audios_temp: {e}")

    async def _generate_audio_gpt_sovits(
        self,
        text: str,
        character_index: int,
        audio_language_choice: str,
        sakiko_state: bool
    ) -> tuple[str, str]:
        """GPT-SoVITSを使用した音声合成処理"""
        global global_gptsovits_manager, _global_emotion_model

        if global_gptsovits_manager is None:
            raise RuntimeError("GPT-SoVITS process manager is not initialized.")

        if not (0 <= character_index < len(self.character_list)):
            raise ValueError(f"Invalid character index: {character_index}")

        current_char = self.character_list[character_index]

        # 2. テキスト前処理
        translation_pattern_to_remove = r"(?:\[翻译\]|\[翻訳\]).*?(?:\[翻译结束\]|\[翻訳結束\]|\[翻訳終了\])"
        cleaned_text = re.sub(translation_pattern_to_remove, "", text, flags=re.DOTALL).strip()

        processed_text = cleaned_text
        if audio_language_choice == '日英混合':
            processed_text = re.sub(r'CRYCHIC', 'クライシック', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'\bave\s*mujica\b', 'あヴぇムジカ', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'立希', ('りっき' if self.character_list[character_index].character_name == '爱音' else 'たき'), processed_text, flags=re.IGNORECASE)
            for key, value in self.replacements_jap.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        elif audio_language_choice == '粤英混合':
            for key, value in self.replacements_yue.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        else:  # 中国語
            for key, value in self.replacements_chi.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)

        pattern = r'^[^A-Za-z0-9\u3040-\u30FF\u4E00-\u9FFF]+\'\''  # 文頭の記号除去
        processed_text = re.sub(pattern, '', processed_text)
        processed_text = processed_text.replace(' ', '')

        # 感情分析の実行
        emotion_label = "neutral"
        if _global_emotion_model and processed_text.strip():
            try:
                emotion_result = await run_in_threadpool(_global_emotion_model, processed_text)
                emotion_label = emotion_result[0]['label']
                logger.debug(f"Emotion detected for text '{processed_text}': {emotion_label}")
            except Exception as e:
                logger.warning(f"Emotion detection failed: {e}")

        if processed_text == '' or processed_text == '不能送去合成':
            processed_text = '今年'  # エラー回避用のデフォルト値

        # 3. 参照オーディオとテキストファイルの決定
        ref_audio_file_to_use = current_char.gptsovits_ref_audio
        ref_text_to_use = ""
        if os.path.exists(current_char.gptsovits_ref_audio_text):
            with open(current_char.gptsovits_ref_audio_text, 'r', encoding='utf-8') as f:
                ref_text_to_use = f.read().strip()

        if current_char.character_name == '祥子':
            if sakiko_state:  # 黒祥子
                ref_audio_file_to_use = self.ref_audio_file_black_sakiko
                if os.path.exists(self.ref_text_file_black_sakiko):
                    with open(self.ref_text_file_black_sakiko, 'r', encoding='utf-8') as f:
                        ref_text_to_use = f.read().strip()
            else:  # 白祥子
                ref_audio_file_to_use = self.ref_audio_file_white_sakiko
                if os.path.exists(self.ref_text_file_white_sakiko):
                    with open(self.ref_text_file_white_sakiko, 'r', encoding='utf-8') as f:
                        ref_text_to_use = f.read().strip()

        # 4. GPT-SoVITSプロセスの呼び出し
        speed = 1.0
        if audio_language_choice == '日英混合':
            speed = 0.9
        elif audio_language_choice == '粤英混合':
            speed = 0.85 if current_char.character_name == '祥子' else 0.8
        else:  # 中国語
            speed = 0.9

        try:
            audio_data_bytes = await run_in_threadpool(
                global_gptsovits_manager.generate_audio_sync,
                text=processed_text,
                ref_wav_path=ref_audio_file_to_use,
                prompt_text=ref_text_to_use,
                prompt_language=current_char.gptsovits_ref_audio_lan,
                text_language=audio_language_choice,
                character_index=character_index,
                speed=speed
            )
            # クリーンアップ実行
            self._cleanup_generated_audios_temp()
            return base64.b64encode(audio_data_bytes).decode("utf-8"), emotion_label
        except Exception as e:
            logger.error(f"Error during GPT-SoVITS audio generation for character {current_char.character_name}: {e}")
            # 無音オーディオを返す（エラーハンドリング）
            silent_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference_audio", "silent_audio", "silence.wav")
            if not os.path.exists(silent_audio_path):
                sample_rate = 22050
                duration = 1
                silent_data = np.zeros(int(sample_rate * duration), dtype=np.float32)
                os.makedirs(os.path.dirname(silent_audio_path), exist_ok=True)
                sf.write(silent_audio_path, silent_data, sample_rate)
            with open(silent_audio_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8"), emotion_label

    async def _generate_audio_tts_rvc(self, text: str, character_index: int, audio_language_choice: str) -> tuple[str, str]:
        """Gemini TTS + RVC を使用した音声合成処理"""
        # 1. RVCモデルパスの取得
        if not (0 <= character_index < len(self.character_list)):
            raise ValueError(f"Invalid character index: {character_index}")

        current_char = self.character_list[character_index]
        rvc_model_dir_id = current_char.rvc_model_dir_id
        rvc_index_dir_id = current_char.rvc_index_dir_id

        if not rvc_model_dir_id or not rvc_index_dir_id:
            raise ValueError(f"RVC model or index directory ID not configured for character: {current_char.character_name}")

        # 2. Gemini TTS呼び出し
        if not self.GEMINI_API_KEY:
            raise RuntimeError("Gemini API Key is not loaded. Cannot use TTS+RVC method.")

        # テキスト前処理
        translation_pattern_to_remove = r"(?:\[翻译\]|\[翻訳\]).*?(?:\[翻译结束\]|\[翻訳結束\]|\[翻訳終了\])"
        cleaned_text = re.sub(translation_pattern_to_remove, "", text, flags=re.DOTALL).strip()

        processed_text = cleaned_text
        if audio_language_choice == '日英混合':
            processed_text = re.sub(r'CRYCHIC', 'クライシック', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'\bave\s*mujica\b', 'あヴぇムジカ', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'立希', ('りっき' if self.character_list[character_index].character_name == '爱音' else 'たき'), processed_text, flags=re.IGNORECASE)
            for key, value in self.replacements_jap.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        elif audio_language_choice == '粤英混合':
            for key, value in self.replacements_yue.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        else:  # 中国語
            for key, value in self.replacements_chi.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)

        pattern = r'^[^A-Za-z0-9\u3040-\u30FF\u4E00-\u9FFF]+\'\''
        processed_text = re.sub(pattern, '', processed_text)
        processed_text = processed_text.replace(' ', '')

        tts_payload = {
            "contents": [{
                "parts": [{"text": processed_text}]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": "Aoede"
                        }
                    }
                }
            },
            "model": "gemini-2.5-flash-preview-tts",
        }
        tts_headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": self.GEMINI_API_KEY,
        }

        emotion_label = "neutral"

        try:
            # 感情分析
            if _global_emotion_model and processed_text.strip():
                try:
                    emotion_result = await run_in_threadpool(_global_emotion_model, processed_text)
                    emotion_label = emotion_result[0]['label']
                    logger.debug(f"Emotion detected for text '{processed_text}' (TTS+RVC): {emotion_label}")
                except Exception as e:
                    logger.warning(f"Emotion detection failed for TTS+RVC: {e}")

            logger.info(f"Sending Gemini TTS request with payload: {json.dumps(tts_payload, indent=2)}")
            response = requests.post(GEMINI_TTS_URL, headers=tts_headers, json=tts_payload, timeout=30)
            
            logger.info(f"Received Gemini TTS response status: {response.status_code}")
            logger.info(f"Received Gemini TTS raw response: {response.text}")

            response.raise_for_status()
            response_json = response.json()

            if "error" in response_json:
                error_message = response_json["error"].get("message", "Unknown Gemini TTS API error")
                logger.error(f"Gemini TTS API returned an error: {error_message}")
                raise RuntimeError(f"Gemini TTS API error: {error_message}")

            base64_audio_data = response_json.get("candidates", [{}])[0]\
                                             .get("content", {})\
                                             .get("parts", [{}])[0]\
                                             .get("inlineData", {})\
                                             .get("data")

            if not base64_audio_data:
                raise RuntimeError("No audio data received from Gemini TTS (data field missing or empty).")

            decoded_audio_data = base64.b64decode(base64_audio_data)
            tts_wav_data = convert_to_wav(decoded_audio_data, "audio/L16;rate=24000")

        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error from Gemini TTS: {http_err}")
            if hasattr(response, 'text'):
                try:
                    error_details = response.json()
                    error_message = error_details.get("error", {}).get("message", "Unknown HTTP error from Gemini TTS.")
                    logger.error(f"Gemini TTS HTTP error details: {error_message}")
                    raise RuntimeError(f"Gemini TTS HTTP error: {error_message}") from http_err
                except json.JSONDecodeError:
                    logger.error(f"Could not decode error response from Gemini TTS as JSON: {response.text}")
                    raise RuntimeError(f"Gemini TTS HTTP error: {http_err}, response: {response.text}") from http_err
            else:
                raise RuntimeError(f"Gemini TTS HTTP error: {http_err}") from http_err
        except requests.exceptions.RequestException as e:
            logger.error(f"Network or request error calling Gemini TTS: {e}")
            raise RuntimeError(f"Network or request error to Gemini TTS: {e}") from e
        except Exception as e:
            logger.error(f"An unexpected error occurred during Gemini TTS call: {e}")
            raise RuntimeError(f"Unexpected error during Gemini TTS call: {e}") from e

        # 3. RVCサービスによる音色変換
        rvc_payload = {
            "audio_data_base64": base64.b64encode(tts_wav_data).decode('utf-8'),
            "rvc_model_relative_dir": rvc_model_dir_id, 
            "rvc_index_relative_dir": rvc_index_dir_id, 
            "pitch_shift": 0,
            "f0_method": "rmvpe",
            "index_rate": 0.75,
            "filter_radius": 3,
            "resample_sr": 0,
            "rms_mix_rate": 0.25,
            "protect": 0.33
        }
        rvc_headers = {"Content-Type": "application/json"}

        try:
            rvc_response = requests.post(RVC_SERVICE_URL, headers=rvc_headers, json=rvc_payload, timeout=60)
            rvc_response.raise_for_status()
            rvc_response_json = rvc_response.json()
            converted_audio_base64 = rvc_response_json.get("converted_audio_base64")

            if not converted_audio_base64:
                raise RuntimeError("No converted audio received from RVC service.")

            converted_audio_bytes = base64.b64decode(converted_audio_base64)
            return base64.b64encode(converted_audio_bytes).decode("utf-8"), emotion_label

        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling RVC service for character {current_char.character_name}: {e}")
            if hasattr(rvc_response, 'content'):
                logger.error(f"RVC Error Response: {rvc_response.text}")
            raise
        except Exception as e:
            logger.error(f"Unhandled error during RVC conversion for character {current_char.character_name}: {e}")
            raise

    async def _generate_audio_edge_tts_rvc(self, text: str, character_index: int, audio_language_choice: str) -> tuple[str, str]:
        """Edge TTS + RVC を使用した音声合成処理"""
        # 1. RVCモデルパスの取得
        if not (0 <= character_index < len(self.character_list)):
            raise ValueError(f"Invalid character index: {character_index}")

        current_char = self.character_list[character_index]
        rvc_model_dir_id = current_char.rvc_model_dir_id
        rvc_index_dir_id = current_char.rvc_index_dir_id

        if not rvc_model_dir_id or not rvc_index_dir_id:
            raise ValueError(f"RVC model or index directory ID not configured for character: {current_char.character_name}")

        # 2. Edge TTS 音声生成
        edge_tts_voice = self.EDGE_TTS_DEFAULT_VOICE

        # カスタム音声設定の読み込み (azure_voice.txt)
        character_audio_base_dir_in_chat_backend = os.path.dirname(current_char.gptsovits_ref_audio)
        azure_voice_config_path = os.path.join(character_audio_base_dir_in_chat_backend, "azure_voice.txt")
        custom_voices = []

        if os.path.exists(azure_voice_config_path):
            try:
                with open(azure_voice_config_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    custom_voices = [line.strip() for line in lines if line.strip()]
                logger.info(f"Custom voices loaded from {azure_voice_config_path}: {custom_voices}")
            except Exception as e:
                logger.warning(f"Failed to read custom voices from {azure_voice_config_path}: {e}")

        if custom_voices:
            if audio_language_choice == "日英混合":
                if len(custom_voices) >= 2:
                    edge_tts_voice = custom_voices[1]
                    logger.info(f"Using custom Edge TTS voice for Ja-En mix: {edge_tts_voice}")
                else:
                    logger.warning(f"'{azure_voice_config_path}' does not have enough lines for Ja-En mix. Using default.")
            elif audio_language_choice == "粤英混合":
                if len(custom_voices) >= 3:
                    edge_tts_voice = custom_voices[2]
                    logger.info(f"Using custom Edge TTS voice for Canto-En mix: {edge_tts_voice}")
                else:
                    logger.warning(f"'{azure_voice_config_path}' does not have enough lines for Canto-En mix. Using default.")
            else:  # デフォルト/中英混合
                if len(custom_voices) >= 1:
                    edge_tts_voice = custom_voices[0]
                    logger.info(f"Using custom Edge TTS voice for Default/Zh-En mix: {edge_tts_voice}")
                else:
                    logger.warning(f"'{azure_voice_config_path}' is empty or does not have a first line. Using default.")

        if audio_language_choice == "日英混合":
            if not custom_voices or len(custom_voices) < 2:
                edge_tts_voice = "ja-JP-AoiNeural"
        elif audio_language_choice == "粤英混合":
            if not custom_voices or len(custom_voices) < 3:
                edge_tts_voice = "zh-HK-HiuGaaiNeural"

        # テキスト前処理
        translation_pattern_to_remove = r"(?:\[翻译\]|\[翻訳\]).*?(?:\[翻译结束\]|\[翻訳結束\]|\[翻訳終了\])"
        cleaned_text = re.sub(translation_pattern_to_remove, "", text, flags=re.DOTALL).strip()

        processed_text = cleaned_text
        if audio_language_choice == '日英混合':
            processed_text = re.sub(r'CRYCHIC', 'クライシック', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'\bave\s*mujica\b', 'あヴぇムジカ', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'立希', ('りっき' if self.character_list[character_index].character_name == '爱音' else 'たき'), processed_text, flags=re.IGNORECASE)
            for key, value in self.replacements_jap.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        elif audio_language_choice == '粤英混合':
            for key, value in self.replacements_yue.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        else:  # 中国語
            for key, value in self.replacements_chi.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)

        pattern = r'^[^A-Za-z0-9\u3040-\u30FF\u4E00-\u9FFF]+\'\''
        processed_text = re.sub(pattern, '', processed_text)
        processed_text = processed_text.replace(' ', '')

        emotion_label = "neutral"

        try:
            # 感情分析
            global _global_emotion_model
            if _global_emotion_model and processed_text.strip():
                try:
                    emotion_result = await run_in_threadpool(_global_emotion_model, processed_text)
                    emotion_label = emotion_result[0]['label']
                    logger.debug(f"Emotion detected for text '{processed_text}' (EdgeTTS+RVC): {emotion_label}")
                except Exception as e:
                    logger.warning(f"Emotion detection failed for EdgeTTS+RVC: {e}")

            communicate = edge_tts.Communicate(
                processed_text,
                edge_tts_voice,
                rate=self.EDGE_TTS_DEFAULT_RATE,
                volume=self.EDGE_TTS_DEFAULT_VOLUME,
            )

            audio_data_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data_chunks.append(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    pass
            
            edge_tts_raw_audio_bytes = b"".join(audio_data_chunks)
            edge_tts_wav_data = edge_tts_raw_audio_bytes
            logger.info(f"Edge TTS generated audio in memory. Length: {len(edge_tts_wav_data)} bytes")

        except Exception as e:
            logger.error(f"Error calling Edge TTS for character {current_char.character_name}: {e}")
            raise RuntimeError(f"Error during Edge TTS call: {e}")

        # 3. RVCサービスによる音色変換
        rvc_payload = {
            "audio_data_base64": base64.b64encode(edge_tts_wav_data).decode('utf-8'),
            "rvc_model_relative_dir": rvc_model_dir_id, 
            "rvc_index_relative_dir": rvc_index_dir_id,
            "pitch_shift": 0,
            "f0_method": "rmvpe",
            "index_rate": 0.75,
            "filter_radius": 3,
            "resample_sr": 0,
            "rms_mix_rate": 0.25,
            "protect": 0.33
        }
        rvc_headers = {"Content-Type": "application/json"}

        try:
            rvc_response = requests.post(RVC_SERVICE_URL, headers=rvc_headers, json=rvc_payload, timeout=60)
            rvc_response.raise_for_status()
            rvc_response_json = rvc_response.json()
            converted_audio_base64 = rvc_response_json.get("converted_audio_base64")

            if not converted_audio_base64:
                raise RuntimeError("No converted audio received from RVC service.")

            converted_audio_bytes = base64.b64decode(converted_audio_base64)
            return base64.b64encode(converted_audio_bytes).decode("utf-8"), emotion_label

        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling RVC service for character {current_char.character_name}: {e}")
            if hasattr(rvc_response, 'content'):
                logger.error(f"RVC Error Response: {rvc_response.text}")
            raise
        except Exception as e:
            logger.error(f"Unhandled error during RVC conversion for character {current_char.character_name}: {e}")
            raise

    async def _generate_audio_azure_tts_rvc(self, text: str, character_index: int, audio_language_choice: str) -> tuple[str, str]:
        """Azure TTS + RVC を使用した音声合成処理"""
        # 1. RVCモデルパスの取得
        if not (0 <= character_index < len(self.character_list)):
            raise ValueError(f"Invalid character index: {character_index}")

        current_char = self.character_list[character_index]
        rvc_model_dir_id = current_char.rvc_model_dir_id
        rvc_index_dir_id = current_char.rvc_index_dir_id

        if not rvc_model_dir_id or not rvc_index_dir_id:
            raise ValueError(f"RVC model or index directory ID not configured for character: {current_char.character_name}")

        # 2. Azure TTS 音声生成
        if not self.AZURE_TTS_SUBSCRIPTION_KEY:
            raise RuntimeError("Azure TTS Subscription Key is not loaded. Cannot use Azure TTS+RVC method.")

        # テキスト前処理
        translation_pattern_to_remove = r"(?:\[翻译\]|\[翻訳\]).*?(?:\[翻译结束\]|\[翻訳結束\]|\[翻訳終了\])"
        cleaned_text = re.sub(translation_pattern_to_remove, "", text, flags=re.DOTALL).strip()

        processed_text = cleaned_text
        if audio_language_choice == '日英混合':
            processed_text = re.sub(r'CRYCHIC', 'クライシック', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'\bave\s*mujica\b', 'あヴぇムジカ', processed_text, flags=re.IGNORECASE)
            processed_text = re.sub(r'立希', ('りっき' if self.character_list[character_index].character_name == '爱音' else 'たき'), processed_text, flags=re.IGNORECASE)
            for key, value in self.replacements_jap.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        elif audio_language_choice == '粤英混合':
            for key, value in self.replacements_yue.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)
        else:  # 中国語
            for key, value in self.replacements_chi.items():
                processed_text = re.sub(re.escape(key), value, processed_text, flags=re.IGNORECASE)

        pattern = r'^[^A-Za-z0-9\u3040-\u30FF\u4E00-\u9FFF]+\'\''
        processed_text = re.sub(pattern, '', processed_text)
        processed_text = processed_text.replace(' ', '')

        emotion_label = "neutral"

        try:
            # 感情分析
            global _global_emotion_model
            if _global_emotion_model and processed_text.strip():
                try:
                    emotion_result = await run_in_threadpool(_global_emotion_model, processed_text)
                    emotion_label = emotion_result[0]['label']
                    logger.debug(f"Emotion detected for text '{processed_text}' (AzureTTS+RVC): {emotion_label}")
                except Exception as e:
                    logger.warning(f"Emotion detection failed for AzureTTS+RVC: {e}")

            access_token = await self._get_azure_tts_access_token()

            # SSMLペイロードの構築
            azure_tts_voice_name = AZURE_TTS_DEFAULT_VOICE

            # カスタム音声設定の読み込み
            character_audio_base_dir_in_chat_backend = os.path.dirname(current_char.gptsovits_ref_audio)
            azure_voice_config_path = os.path.join(character_audio_base_dir_in_chat_backend, "azure_voice.txt")
            custom_voices = []

            if os.path.exists(azure_voice_config_path):
                try:
                    with open(azure_voice_config_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        custom_voices = [line.strip() for line in lines if line.strip()]
                    logger.info(f"Custom voices loaded from {azure_voice_config_path}: {custom_voices}")
                except Exception as e:
                    logger.warning(f"Failed to read custom voices from {azure_voice_config_path}: {e}")

            if custom_voices:
                if audio_language_choice == "日英混合":
                    if len(custom_voices) >= 2:
                        azure_tts_voice_name = custom_voices[1]
                        logger.info(f"Using custom Azure TTS voice for Ja-En mix: {azure_tts_voice_name}")
                    else:
                        logger.warning(f"'{azure_voice_config_path}' does not have enough lines for Ja-En mix. Using default.")
                elif audio_language_choice == "粤英混合":
                    if len(custom_voices) >= 3:
                        azure_tts_voice_name = custom_voices[2]
                        logger.info(f"Using custom Azure TTS voice for Canto-En mix: {azure_tts_voice_name}")
                    else:
                        logger.warning(f"'{azure_voice_config_path}' does not have enough lines for Canto-En mix. Using default.")
                else:  # デフォルト/中英混合
                    if len(custom_voices) >= 1:
                        azure_tts_voice_name = custom_voices[0]
                        logger.info(f"Using custom Azure TTS voice for Default/Zh-En mix: {azure_tts_voice_name}")
                    else:
                        logger.warning(f"'{azure_voice_config_path}' is empty or does not have a first line. Using default.")

            xml_body = ElementTree.Element('speak', version='1.0')
            voice = ElementTree.SubElement(xml_body, 'voice')

            if audio_language_choice == "日英混合":
                if not custom_voices or len(custom_voices) < 2:
                    azure_tts_voice_name = "ja-JP-AoiNeural"
                xml_body.set('{http://www.w3.org/XML/1998/namespace}lang', 'ja-JP')
                voice.set('{http://www.w3.org/XML/1998/namespace}lang', 'ja-JP')
            elif audio_language_choice == "粤英混合":
                if not custom_voices or len(custom_voices) < 3:
                    azure_tts_voice_name = "zh-HK-HiuGaaiNeural"
                xml_body.set('{http://www.w3.org/XML/1998/namespace}lang', 'zh-HK')
                voice.set('{http://www.w3.org/XML/1998/namespace}lang', 'zh-HK')
            else:
                xml_body.set('{http://www.w3.org/XML/1998/namespace}lang', 'zh-CN')
                voice.set('{http://www.w3.org/XML/1998/namespace}lang', 'zh-CN')

            voice.set('name', azure_tts_voice_name)
            voice.text = processed_text
            body = ElementTree.tostring(xml_body, encoding='utf-8')

            azure_tts_headers = {
                'Authorization': 'Bearer ' + access_token,
                'Content-Type': 'application/ssml+xml',
                'X-Microsoft-OutputFormat': AZURE_TTS_OUTPUT_FORMAT,
                'User-Agent': AZURE_TTS_USER_AGENT
            }

            response = requests.post(AZURE_TTS_ENDPOINT, headers=azure_tts_headers, data=body, timeout=30)
            response.raise_for_status()
            azure_tts_audio_data = response.content

        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling Azure TTS for character {current_char.character_name}: {e}")
            if hasattr(response, 'content'):
                logger.error(f"Azure TTS Error Response: {response.content.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"Error during Azure TTS call: {e}")
        except Exception as e:
            logger.error(f"Unhandled error during Azure TTS for character {current_char.character_name}: {e}")
            raise RuntimeError(f"Unhandled error during Azure TTS call: {e}")

        # 3. RVCサービスによる音色変換
        base64_azure_tts_audio = base64.b64encode(azure_tts_audio_data).decode('utf-8')

        rvc_payload = {
            "audio_data_base64": base64_azure_tts_audio,
            "rvc_model_relative_dir": rvc_model_dir_id, 
            "rvc_index_relative_dir": rvc_index_dir_id,
            "f0_up_key": 0,
            "f0_method": "rmvpe",
            "protect": 0.5,
            "index_rate": 0.75,
            "resample_sr": 0,
            "rms_mix_rate": 1,
            "tuner_steps": 200
        }
        rvc_headers = {"Content-Type": "application/json"}

        logger.debug(f"Sending RVC request for character {current_char.character_name}.")

        try:
            rvc_response = requests.post(RVC_SERVICE_URL, headers=rvc_headers, json=rvc_payload, timeout=60)
            rvc_response.raise_for_status()
            rvc_response_json = rvc_response.json()

            logger.debug(f"Received RVC response: {rvc_response_json}")

            converted_audio_base64 = rvc_response_json.get("converted_audio_base64")

            if not converted_audio_base64:
                logger.error(f"RVC service did not return converted_audio_base64 for character {current_char.character_name}.")
                raise RuntimeError("No converted audio received from RVC service.")

            logger.info(f"RVC converted audio base64 length: {len(converted_audio_base64)}")
            converted_audio_bytes = base64.b64decode(converted_audio_base64)

            if not converted_audio_bytes:
                logger.error(f"Decoded RVC audio bytes are empty for character {current_char.character_name}.")
                raise RuntimeError("RVC converted audio data is empty after decoding.")
            else:
                logger.info(f"Decoded RVC audio bytes size: {len(converted_audio_bytes)} bytes.")

            return base64.b64encode(converted_audio_bytes).decode("utf-8"), emotion_label

        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling RVC service for character {current_char.character_name}: {e}")
            if hasattr(rvc_response, 'content'):
                logger.error(f"RVC Error Response: {rvc_response.text}")
            raise
        except Exception as e:
            logger.error(f"Unhandled error during RVC conversion for character {current_char.character_name}: {e}")
            raise

    async def generate_audio(
        self,
        text: str,
        character_index: int,
        audio_language_choice: str,
        sakiko_state: bool,
        synthesis_method: str = "gpt_sovits"
    ) -> tuple[str, str]:
        """指定された合成方法に基づいて音声を生成する"""
        if synthesis_method == "gpt_sovits":
            return await self._generate_audio_gpt_sovits(text, character_index, audio_language_choice, sakiko_state)
        elif synthesis_method == "tts_rvc":
            return await self._generate_audio_tts_rvc(text, character_index, audio_language_choice)
        elif synthesis_method == "edge_tts_rvc":
            return await self._generate_audio_edge_tts_rvc(text, character_index, audio_language_choice)
        elif synthesis_method == "azure_tts_rvc":
            return await self._generate_audio_azure_tts_rvc(text, character_index, audio_language_choice)
        else:
            raise ValueError(f"Unknown synthesis method: {synthesis_method}. Must be 'gpt_sovits', 'tts_rvc', 'edge_tts_rvc', or 'azure_tts_rvc'.")


# FastAPI ルーティングとエンドポイント定義
audio_router = APIRouter()

class SynthesizeAudioSegmentRequest(BaseModel):
    text_segment: str
    character_index: int
    audio_language_choice: str
    sakiko_state: Optional[bool] = False
    synthesis_method: Optional[str] = "gpt_sovits"

class InitializeModelRequest(BaseModel):
    character_index: int

_current_audio_generator: SimpleAudioGenerator = None

def get_audio_generator():
    global _current_audio_generator
    if _current_audio_generator is None:
        raise RuntimeError("SimpleAudioGenerator not initialized in audio_api_service.py")
    return _current_audio_generator

def set_audio_generator_instance(generator: SimpleAudioGenerator):
    global _current_audio_generator
    _current_audio_generator = generator

def set_gptsovits_manager_instance(manager: GPTSovitsProcessManager):
    global global_gptsovits_manager
    global_gptsovits_manager = manager

def set_emotion_model(model: Any):
    global _global_emotion_model
    _global_emotion_model = model


@audio_router.post("/initialize_gptsovits_model")
async def initialize_gptsovits_model_endpoint(
    request: InitializeModelRequest,
    audio_generator: SimpleAudioGenerator = Depends(get_audio_generator)
):
    global global_gptsovits_manager
    if global_gptsovits_manager is None:
        logger.error("GPT-SoVITS process manager is not initialized.")
        raise HTTPException(status_code=500, detail="GPT-SoVITS process manager is not initialized.")
    
    try:
        # FastAPIのイベントループ内で同期コードを安全に実行するためにrun_in_threadpoolを使用
        await run_in_threadpool(global_gptsovits_manager.initialize_models_for_character, request.character_index)
        logger.info(f"GPT-SoVITS model for character index {request.character_index} initialized/confirmed.")
        return {"message": f"Model for character index {request.character_index} initialized successfully."}
    except Exception as e:
        logger.exception(f"Error initializing GPT-SoVITS model for character index {request.character_index}:")
        raise HTTPException(status_code=500, detail=f"Failed to initialize model: {e}")


@audio_router.post("/synthesize_audio_segment")
async def synthesize_audio_segment(
    request: SynthesizeAudioSegmentRequest,
    audio_generator: SimpleAudioGenerator = Depends(get_audio_generator)
):
    try:
        audio_base64, emotion_label = await audio_generator.generate_audio(
            text=request.text_segment,
            character_index=request.character_index,
            audio_language_choice=request.audio_language_choice,
            sakiko_state=request.sakiko_state,
            synthesis_method=request.synthesis_method
        )
        return {"text_segment": request.text_segment, "audio_base64": audio_base64, "emotion": emotion_label}
    except Exception as e:
        logger.exception("Error synthesizing audio segment:")
        # エラー時は静音オーディオを返す
        silent_audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference_audio", "silent_audio", "silence.wav")
        if not os.path.exists(silent_audio_path):
            sample_rate = 22050
            duration = 1
            silent_data = np.zeros(int(sample_rate * duration), dtype=np.float32)
            os.makedirs(os.path.dirname(silent_audio_path), exist_ok=True)
            sf.write(silent_audio_path, silent_data, sample_rate)
        
        with open(silent_audio_path, "rb") as f:
            silent_audio_base64 = base64.b64encode(f.read()).decode("utf-8")
        
        return {"text_segment": request.text_segment, "audio_base64": silent_audio_base64, "error": str(e), "emotion": "neutral"}