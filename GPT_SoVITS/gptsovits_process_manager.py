

import os
import time
import shutil
import uuid
import threading
import atexit
import logging
import soundfile as sf
import numpy as np
from multiprocessing import Process, Queue
from queue import Empty

# オリジナルの推論関数をインポート
from inference_cli import synthesize as original_synthesize

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GPTSovitsProcessManager:
    """
    GPT-SoVITSの推論プロセスを管理するクラス。
    モデルのロード、切り替え、および音声合成タスクの排他制御を行う。
    """
    def __init__(self, character_list):
        self.to_gptsovits_com_queue = Queue()
        self.from_gptsovits_com_queue = Queue()
        self.from_gptsovits_com_queue2 = Queue()  # メッセージ/進捗用
        self.gptsovits_process = None
        self.character_list = character_list
        
        # 状態管理用変数
        self.current_gpt_path = None
        self.current_sovits_path = None
        self.current_loaded_character_index = -1
        
        # 出力ディレクトリ設定
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.program_output_path = os.path.join(base_dir, "..", "reference_audio", "generated_audios_temp")
        os.makedirs(self.program_output_path, exist_ok=True)

        self._ensure_silent_audio_exists()

        # 排他制御用ロック（モデル切り替えと合成処理の原子性を保証）
        self.execution_lock = threading.Lock() 

    def _ensure_silent_audio_exists(self):
        """デフォルトの無音オーディオファイルが存在することを確認する"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        silent_audio_path = os.path.join(base_dir, "..", "reference_audio", "silent_audio", "silence.wav")
        os.makedirs(os.path.dirname(silent_audio_path), exist_ok=True)
        if not os.path.exists(silent_audio_path):
            sample_rate = 22050
            duration = 1
            silent_data = np.zeros(int(sample_rate * duration), dtype=np.float32)
            sf.write(silent_audio_path, silent_data, sample_rate)

    def start_process(self):
        """GPT-SoVITS推論プロセスを開始する"""
        if self.gptsovits_process and self.gptsovits_process.is_alive():
            return
        logger.info("Starting GPT-SoVITS process...")
        self.gptsovits_process = Process(target=original_synthesize,
                                           args=(self.to_gptsovits_com_queue,
                                                 self.from_gptsovits_com_queue,
                                                 self.from_gptsovits_com_queue2))
        self.gptsovits_process.start()
        
        # プロセス再起動時は状態をリセット
        self.current_gpt_path = None 
        self.current_sovits_path = None
        self.current_loaded_character_index = -1

    def stop_process(self):
        """GPT-SoVITS推論プロセスを停止する"""
        if self.gptsovits_process and self.gptsovits_process.is_alive():
            logger.info("Stopping GPT-SoVITS process...")
            self.to_gptsovits_com_queue.put('bye')
            self.gptsovits_process.join(timeout=5)
            if self.gptsovits_process.is_alive():
                self.gptsovits_process.terminate()
        self.current_loaded_character_index = -1

    def _switch_model_if_needed(self, character_index: int):
        """
        必要に応じてモデルを切り替える内部メソッド。
        execution_lock内で呼び出されることを前提とする。
        """
        if not self.gptsovits_process or not self.gptsovits_process.is_alive():
            self.start_process()
            time.sleep(2)

        current_char = self.character_list[character_index]
        gpt_path = current_char.GPT_model_path
        sovits_path = current_char.sovits_model_path

        # 現在ロードされているモデルと一致する場合はスキップ
        if (self.current_loaded_character_index == character_index and 
            self.current_gpt_path == gpt_path and 
            self.current_sovits_path == sovits_path):
            return

        # 残留キューのクリア
        while not self.from_gptsovits_com_queue.empty():
            try: self.from_gptsovits_com_queue.get_nowait()
            except Empty: pass
        
        current_request_id = str(uuid.uuid4())
        logger.info(f"Switching to character {character_index} (ID: {current_request_id})")
        
        # モデル切り替えコマンド送信 (info[0]=0)
        self.to_gptsovits_com_queue.put([0, gpt_path, sovits_path, current_request_id])

        # 完了待機
        timeout = 60
        start_time = time.time()
        
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for model switch.")
            
            # ログキューの消費（ブロッキング防止）
            while not self.from_gptsovits_com_queue2.empty():
                try: self.from_gptsovits_com_queue2.get_nowait()
                except Empty: pass

            try:
                msg = self.from_gptsovits_com_queue.get(timeout=0.1)

                if msg == 'done':
                    break  # 切り替え成功
                elif msg == 'wait':
                    continue  # ロード中
                elif msg == 'error':
                    raise RuntimeError(f"Model switch failed for char {character_index}")
            except Empty:
                continue

        # 状態更新
        self.current_gpt_path = gpt_path
        self.current_sovits_path = sovits_path
        self.current_loaded_character_index = character_index
        logger.info(f"Model switched to character {character_index}")

    def initialize_models_for_character(self, character_index: int):
        """外部APIからのモデル初期化リクエスト用ラッパー"""
        with self.execution_lock:
            self._switch_model_if_needed(character_index)

    def generate_audio_sync(self, text: str,
                            ref_wav_path: str,
                            prompt_text: str,
                            prompt_language: str,
                            text_language: str,
                            character_index: int,
                            speed: float = 1.0,
                            how_to_cut: str = '不切',
                            top_p: float = 1,
                            temperature: float = 1,
                            sample_steps: int = 16,
                            pause_second: float = 0.4):
        """
        同期的に音声を生成する。
        モデルの切り替えと生成プロセス全体をロックし、排他制御を行う。
        """
        with self.execution_lock:
            # 1. モデルの確認と切り替え
            self._switch_model_if_needed(character_index)

            # 2. プロンプトテキスト用の一時ファイル作成
            temp_ref_text_file = os.path.join(self.program_output_path, f"temp_ref_text_{uuid.uuid4()}.txt")
            with open(temp_ref_text_file, 'w', encoding='utf-8') as f:
                f.write(prompt_text)

            # 3. 合成コマンドの送信
            info = [
                1,  # コマンドタイプ：1 = 音声合成
                ref_wav_path,
                temp_ref_text_file,
                prompt_language,
                text,
                text_language,
                self.program_output_path,
                speed,
                how_to_cut,
                top_p,
                temperature,
                sample_steps,
                pause_second
            ]
            
            # 結果キューのクリア（今回の結果のみを取得するため）
            while not self.from_gptsovits_com_queue.empty():
                try: self.from_gptsovits_com_queue.get_nowait()
                except Empty: pass

            self.to_gptsovits_com_queue.put(info)

            # 4. 結果待機
            timeout = 120
            start_time = time.time()
            output_audio_path = None

            try:
                while True:
                    if time.time() - start_time > timeout:
                        raise TimeoutError("Timeout waiting for audio generation.")
                    
                    # ログ/進捗キューの消費
                    while not self.from_gptsovits_com_queue2.empty():
                        try: self.from_gptsovits_com_queue2.get_nowait()
                        except Empty: pass
                    
                    try:
                        result = self.from_gptsovits_com_queue.get(timeout=0.2)
                        if isinstance(result, str):
                            if result.endswith('.wav'):
                                output_audio_path = result
                                break
                            elif 'silence.wav' in result:
                                output_audio_path = result  # エラー時の無音対応
                                break
                    except Empty:
                        continue

            finally:
                if os.path.exists(temp_ref_text_file):
                    os.remove(temp_ref_text_file)

            # 5. 音声データの読み込みと返却
            if output_audio_path:
                if os.path.exists(output_audio_path):
                    with open(output_audio_path, "rb") as f:
                        audio_data = f.read()
                    return audio_data
            
            raise RuntimeError("Failed to generate audio")

# プロセス終了時のクリーンアップ登録
_global_gptsovits_manager = None

@atexit.register
def _cleanup_gptsovits_process():
    global _global_gptsovits_manager
    if _global_gptsovits_manager:
        _global_gptsovits_manager.stop_process()