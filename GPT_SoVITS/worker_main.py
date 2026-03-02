import redis
import json
import logging
import base64
import argparse
import sys
import os
import glob
from gptsovits_process_manager import GPTSovitsProcessManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] Worker: %(message)s')
logger = logging.getLogger(__name__)

ref_audio_language_list =[
    "中文", "英文", "日文", "粤语", "韩文",
    "中英混合", "日英混合", "粤英混合", "韩英混合",
    "多语种混合", "多语种混合(粤语)"
]

def find_models_for_character(character_folder: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    char_audio_dir = os.path.abspath(os.path.join(script_dir, "..", "reference_audio", character_folder))

    if not os.path.exists(char_audio_dir):
        raise FileNotFoundError(f"ディレクトリが見つかりません: {char_audio_dir}")

    gpt_files = glob.glob(os.path.join(char_audio_dir, 'GPT-SoVITS_models', "*.ckpt"))
    sovits_files = glob.glob(os.path.join(char_audio_dir, 'GPT-SoVITS_models', "*.pth"))
    if not gpt_files or not sovits_files:
        raise FileNotFoundError(f"キャラクター '{character_folder}' の音声モデルファイルが見つかりません。")
    
    gpt_path = max(gpt_files, key=os.path.getmtime)
    sovits_path = max(sovits_files, key=os.path.getmtime)

    lang_file_path = os.path.join(char_audio_dir, 'reference_audio_language.txt')
    ref_audio_lan = "中文"
    if os.path.exists(lang_file_path):
        with open(lang_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ref_audio_lan = ref_audio_language_list[int(line) - 1]
                    break

    return char_audio_dir, gpt_path, sovits_path, ref_audio_lan

def run_worker(redis_host: str = 'localhost'):
    try:
        redis_client = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)
        redis_client.ping()
        logger.info(f"Redis ({redis_host}:6379) に接続しました。")
    except redis.ConnectionError:
        logger.error(f"Redisサーバーに接続できません。")
        sys.exit(1)

    manager = GPTSovitsProcessManager([]) 
    manager.start_process()

    queue_name = "queue:audio:global"
    logger.info(f"グローバルキュー '{queue_name}' を監視しています...")

    current_loaded_character = None

    while True:
        try:
            _, task_json = redis_client.brpop(queue_name, timeout=0)
            task = json.loads(task_json)
            
            task_id = task.get("task_id")
            text = task.get("text")
            target_character_folder = task.get("character_folder")
            sakiko_state = task.get("sakiko_state", True)
            audio_language_choice = task.get("audio_language_choice", "中英混合")
            
            logger.info(f"[Task: {task_id}] キャラクター '{target_character_folder}' のタスクを受信。")

            if current_loaded_character != target_character_folder:
                logger.info(f"モデルの切り替えが必要: {current_loaded_character} -> {target_character_folder}")
                char_audio_dir, gpt_path, sovits_path, ref_audio_lan = find_models_for_character(target_character_folder)
                
                with manager.execution_lock:
                    manager.to_gptsovits_com_queue.put([0, gpt_path, sovits_path, f"switch_{task_id}"])
                    manager.current_gpt_path = gpt_path
                    manager.current_sovits_path = sovits_path
                    
                    while True:
                        msg = manager.from_gptsovits_com_queue.get()
                        if msg == 'done':
                            logger.info(f"'{target_character_folder}' のモデルロードが完了しました。")
                            break
                            
                current_loaded_character = target_character_folder
            else:
                char_audio_dir, _, _, ref_audio_lan = find_models_for_character(target_character_folder)

            if target_character_folder == 'sakiko':
                if sakiko_state:
                    ref_wav = os.path.join(char_audio_dir, "black_sakiko.wav")
                    ref_txt_path = os.path.join(char_audio_dir, "reference_text_black_sakiko.txt")
                else:
                    ref_wav = os.path.join(char_audio_dir, "white_sakiko.wav")
                    ref_txt_path = os.path.join(char_audio_dir, "reference_text_white_sakiko.txt")
            else:
                wavs = glob.glob(os.path.join(char_audio_dir, "*.wav")) + glob.glob(os.path.join(char_audio_dir, "*.mp3"))
                ref_wav = max(wavs, key=os.path.getmtime)
                ref_txt_path = os.path.join(char_audio_dir, "reference_text.txt")

            ref_text = ""
            if os.path.exists(ref_txt_path):
                with open(ref_txt_path, 'r', encoding='utf-8') as f:
                    ref_text = f.read().strip()

            speed = 0.9
            if audio_language_choice == '粤英混合' and target_character_folder == 'sakiko':
                speed = 0.85 

            with manager.execution_lock:
                manager.to_gptsovits_com_queue.put([
                    1, ref_wav, ref_txt_path, ref_audio_lan, text, audio_language_choice,
                    manager.program_output_path, speed, '不切', 1, 1, 16, 0.4
                ])

                output_audio_path = None
                while True:
                    result = manager.from_gptsovits_com_queue.get()
                    if isinstance(result, str) and (result.endswith('.wav') or 'silence.wav' in result):
                        output_audio_path = result
                        break

                with open(output_audio_path, "rb") as f:
                    audio_data_bytes = f.read()
            
            audio_base64 = base64.b64encode(audio_data_bytes).decode("utf-8")
            redis_client.set(f"result:{task_id}", json.dumps({"audio_base64": audio_base64}), ex=60)
            logger.info(f"[Task: {task_id}] 完了。結果をRedisに送信しました。")

        except Exception as e:
            logger.error(f"エラー発生: {e}", exc_info=True)
            if 'task_id' in locals() and task_id:
                redis_client.set(f"result:{task_id}", json.dumps({"error": str(e)}), ex=60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis", type=str, default="localhost", help="Redis host")
    args = parser.parse_args()
    
    run_worker(args.redis)