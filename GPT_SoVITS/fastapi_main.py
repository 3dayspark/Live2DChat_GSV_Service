
import uvicorn
import os
import json
import logging
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ローカルモジュールのインポート
from api_character_loader import GetCharacterAttributes, CharacterAttributes
from gptsovits_process_manager import GPTSovitsProcessManager
import audio_api_service
import text_api_service
import inference_emotion_detect

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS設定：フロントエンドからのアクセスを許可
# 開発環境のIPアドレスが含まれています
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.1.36:5173",
        "http://192.168.1.41:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# リクエストボディ用モデル定義
class ChatRequest(BaseModel):
    user_message: str
    character_index: int
    chat_history: List[Dict]
    language_choice: str
    sakiko_state: bool = True
    use_modelscope: bool = False  # デフォルトはFalse (Geminiを使用)
    is_dual_character_mode: bool = False
    secondary_character_index: Optional[int] = None

class CharacterInfo(BaseModel):
    id: int
    character_name: str
    icon_path: Optional[str]
    live2d_json: str
    character_description: str

# グローバル変数：各生成器インスタンスを保持
audio_gen_instance: audio_api_service.SimpleAudioGenerator = None
text_gen_instance: text_api_service.SimpleTextGenerator = None
character_configs: List[CharacterAttributes] = []
_global_gptsovits_manager_instance: GPTSovitsProcessManager = None
emotion_detector = inference_emotion_detect.EmotionDetect()
emotion_model = None

@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の初期化処理"""
    global audio_gen_instance, text_gen_instance, character_configs, _global_gptsovits_manager_instance, emotion_model
    
    logger.info("FastAPI starting up...")
    logger.info("Initializing emotion detection model...")
    emotion_model = emotion_detector.launch_emotion_detect()
    logger.info("Emotion detection model initialized.")

    # 1. キャラクター設定の読み込み
    try:
        get_char_attrs = GetCharacterAttributes()
        character_configs = get_char_attrs.character_class_list
        if not character_configs:
            raise ValueError("No character configurations loaded. Check character.py and data files.")
        logger.info(f"Loaded {len(character_configs)} character configurations.")
    except Exception as e:
        logger.error(f"Failed to load character configurations: {e}")
        raise RuntimeError(f"Failed to load character configurations: {e}")

    # 2. APIキーの読み込み (JSONファイルから)
    gemini_keys = []
    modelscope_keys = []
    
    # JSONファイルは親ディレクトリにあると仮定
    api_key_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api_keys.json"))
    
    if os.path.exists(api_key_file):
        try:
            with open(api_key_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                gemini_keys = data.get("gemini", [])
                modelscope_keys = data.get("modelscope", [])
                
            logger.info(f"Loaded {len(gemini_keys)} Gemini Keys, {len(modelscope_keys)} ModelScope Keys.")
        except json.JSONDecodeError:
            logger.error(f"Error: '{api_key_file}' JSON format is invalid.")
        except Exception as e:
            logger.error(f"Failed to load API Keys: {e}")
    else:
        logger.warning(f"Warning: '{api_key_file}' not found.")

    # デフォルト値のフォールバック
    if not gemini_keys:
        gemini_keys = ["YOUR_DEFAULT_GEMINI_API_KEY_HERE"]
        logger.warning("Warning: No available Gemini Keys. Using default placeholder.")
    
    if not modelscope_keys:
        modelscope_keys = ["ms-default-token"]
        logger.warning("Warning: No available ModelScope Keys. Using default placeholder.")

    # 3. GPT-SoVITS プロセスマネージャーの初期化
    _global_gptsovits_manager_instance = GPTSovitsProcessManager(character_configs)
    audio_api_service.set_gptsovits_manager_instance(_global_gptsovits_manager_instance)

    # 4. 音声生成器の初期化
    audio_gen_instance = audio_api_service.SimpleAudioGenerator(character_configs)
    # 非同期でGeminiおよびAzure TTSのAPIキーをロード
    await audio_gen_instance.load_gemini_api_key()
    await audio_gen_instance.load_azure_tts_subscription_key()
    audio_api_service.set_audio_generator_instance(audio_gen_instance)

    # 5. テキスト生成器の初期化
    text_gen_instance = text_api_service.SimpleTextGenerator(character_configs, gemini_keys, modelscope_keys)
    logger.info("FastAPI startup complete. Service ready.")

    # emotion_modelをaudio_api_serviceへ渡す
    audio_api_service.set_emotion_model(emotion_model)

@app.on_event("shutdown")
async def shutdown_event():
    """アプリケーション終了時のクリーンアップ処理"""
    global _global_gptsovits_manager_instance
    if _global_gptsovits_manager_instance:
        _global_gptsovits_manager_instance.stop_process()
        logger.info("FastAPI shutdown: GPT-SoVITS process stopped.")

# audio_api_service のルーターを含める
app.include_router(audio_api_service.audio_router, prefix="/api/audio")

@app.get("/characters", response_model=List[CharacterInfo])
async def get_characters():
    """ロードされたキャラクター情報のリストを取得するエンドポイント"""
    global character_configs
    return [
        CharacterInfo(
            id=i,
            character_name=char.character_name,
            icon_path=char.icon_path,
            live2d_json=char.live2d_json,
            character_description=char.character_description
        ) for i, char in enumerate(character_configs)
    ]

@app.post("/generate_text_response")
async def generate_text_response_endpoint(request: ChatRequest):
    """テキスト応答生成のエンドポイント"""
    if text_gen_instance is None:
        raise HTTPException(status_code=500, detail="Text generator not initialized.")

    speaker_char_index = request.character_index
    response_text = ""

    try:
        response_text, speaker_char_index = await text_gen_instance.generate_text_response_for_api(
            request.user_message,
            request.character_index,
            request.chat_history,
            request.language_choice,
            request.sakiko_state,
            request.use_modelscope,
            request.is_dual_character_mode,
            request.secondary_character_index
        )
        return {"response_text": response_text, "speaker_char_index": speaker_char_index}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error in /generate_text_response: {e}")
        # クライアント側でどのキャラクターでエラーが起きたかを識別するためのヘッダーを追加
        raise HTTPException(status_code=500, detail=f"Text generation failed: {e}", headers={"X-Speaker-Index-On-Error": str(speaker_char_index)})

def get_emotion_model():
    """感情分析モデルを取得する依存関係関数"""
    return emotion_model

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)