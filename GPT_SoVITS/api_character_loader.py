

import os
import glob
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CharacterAttributes:
    """キャラクターの属性情報を保持するデータクラス"""
    def __init__(self):
        self.character_folder_name = ''
        self.character_name = ''
        self.icon_path = None
        self.live2d_json = ''
        self.GPT_model_path = ''
        self.sovits_model_path = ''
        self.character_description = ''
        self.gptsovits_ref_audio = ''
        self.gptsovits_ref_audio_text = ''
        self.gptsovits_ref_audio_lan = ''
        self.qt_css = None
        self.rvc_model_dir_id = ''  # RVCモデルパス
        self.rvc_index_dir_id = ''  # RVCインデックスパス

    def log_attributes(self):
        """現在の属性値をログに出力する（デバッグ用）"""
        for key, value in self.__dict__.items():
            logger.info(f"{key} = {value}")

# 推論エンジンで使用される言語リスト（※値はAPI仕様依存のため変更不可）
ref_audio_language_list = [
    "中文",
    "英文",
    "日文",
    "粤语",
    "韩文",
    "中英混合",
    "日英混合",
    "粤英混合",
    "韩英混合",
    "多语种混合",
    "多语种混合(粤语)"
]

class GetCharacterAttributes:
    """キャラクター設定ファイルを読み込み、属性リストを生成するクラス"""
    def __init__(self):
        self.character_num = 0
        self.character_class_list = []
        self.load_data()
        
        logger.info('Loaded Characters:')
        for char in self.character_class_list:
            logger.info(f"- {char.character_name}")

    def load_data(self):
        """ディレクトリを走査してキャラクターデータをロードする"""
        # 現在のスクリプトの絶対パスを取得
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Live2D関連フォルダの探索
        live2d_base_path = "../live2d_related"
        
        for char_folder in os.listdir(live2d_base_path):
            full_path = os.path.join(live2d_base_path, char_folder)
            
            # ディレクトリのみを対象とする
            if os.path.isdir(full_path):
                self.character_num += 1
                character = CharacterAttributes()
                character.character_folder_name = char_folder

                # キャラクター名の読み込み
                name_file_path = os.path.join(full_path, 'name.txt')
                if not os.path.exists(name_file_path):
                    raise FileNotFoundError(f"キャラクター '{char_folder}' の name.txt が見つかりません。")
                with open(name_file_path, 'r', encoding='utf-8') as f:
                    character.character_name = f.read().strip()

                # アイコン画像の取得 (最新のpngファイル)
                program_icon_paths = glob.glob(os.path.join(full_path, "*.png"))
                if program_icon_paths:
                    character.icon_path = max(program_icon_paths, key=os.path.getmtime)

                # Live2Dモデル設定の取得
                live2d_json_files = glob.glob(os.path.join(full_path, 'live2D_model', "*.model.json"))
                if not live2d_json_files:
                    raise FileNotFoundError(f"キャラクター '{character.character_name}' のLive2Dモデル定義ファイル(.model.json)が見つかりません。")
                latest_live2d_json = max(live2d_json_files, key=os.path.getmtime)
                
                # サーバーローカルパスからフロントエンド用相対URLへ変換
                character.live2d_json = f"/models/{character.character_folder_name}/live2D_model/{os.path.basename(latest_live2d_json)}"

                # キャラクター設定記述の読み込み
                desc_file_path = os.path.join(full_path, 'character_description.txt')
                if not os.path.exists(desc_file_path):
                    raise FileNotFoundError(f"キャラクター '{character.character_name}' のキャラクター設定ファイルが見つかりません。")
                with open(desc_file_path, 'r', encoding='utf-8') as f:
                    character.character_description = f.read()

                # --- 音声モデル関連パスの設定 ---
                ref_audio_base_dir = os.path.abspath(os.path.join(script_dir, "..", "reference_audio"))
                char_audio_dir = os.path.join(ref_audio_base_dir, char_folder)

                # GPTモデル (.ckpt)
                gpt_model_files = glob.glob(os.path.join(char_audio_dir, 'GPT-SoVITS_models', "*.ckpt"))
                if not gpt_model_files:
                    raise FileNotFoundError(f"キャラクター '{character.character_name}' のGPTモデルファイル(.ckpt)が見つかりません。")
                character.GPT_model_path = max(gpt_model_files, key=os.path.getmtime)

                # SoVITSモデル (.pth)
                sovits_model_files = glob.glob(os.path.join(char_audio_dir, 'GPT-SoVITS_models', "*.pth"))
                if not sovits_model_files:
                    raise FileNotFoundError(f"キャラクター '{character.character_name}' のSoVITSモデルファイル(.pth)が見つかりません。")
                character.sovits_model_path = max(sovits_model_files, key=os.path.getmtime)

                # 参照オーディオファイル (.wav / .mp3)
                ref_audio_wav = glob.glob(os.path.join(char_audio_dir, "*.wav"))
                ref_audio_mp3 = glob.glob(os.path.join(char_audio_dir, "*.mp3"))
                all_ref_audios = ref_audio_wav + ref_audio_mp3
                if not all_ref_audios:
                    raise FileNotFoundError(f"キャラクター '{character.character_name}' の推論用リファレンスオーディオファイル(.wav/.mp3)が見つかりません。")
                character.gptsovits_ref_audio = max(all_ref_audios, key=os.path.getmtime)

                # RVCモデルとインデックス
                character.rvc_model_dir_id = os.path.join(character.character_folder_name, "rvc_model")
                character.rvc_index_dir_id = os.path.join(character.character_folder_name, "rvc_model")
                
                logger.info(f"为角色 '{character.character_name}' 构造 RVC 模型目录 ID: {character.rvc_model_dir_id}")
                logger.info(f"为角色 '{character.character_name}' 构造 RVC 索引目录 ID: {character.rvc_index_dir_id}")

                # 参照テキストファイル
                # 特定キャラクター('sakiko')以外の処理
                if char_folder != 'sakiko':
                    ref_text_path = os.path.join(char_audio_dir, 'reference_text.txt')
                    if not os.path.exists(ref_text_path):
                        raise FileNotFoundError(f"キャラクター '{character.character_name}' のリファレンスオーディオテキストファイル(reference_text.txt)が見つかりません。")
                    character.gptsovits_ref_audio_text = ref_text_path

                # 参照オーディオの言語設定
                lang_file_path = os.path.join(char_audio_dir, 'reference_audio_language.txt')
                if not os.path.exists(lang_file_path):
                    raise FileNotFoundError(f"キャラクター '{character.character_name}' の言語設定ファイルが見つかりません。")
                
                try:
                    with open(lang_file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                # ファイル内の数値(1始まり)をインデックスに変換
                                character.gptsovits_ref_audio_lan = ref_audio_language_list[int(line) - 1]
                                break
                except Exception:
                    raise ValueError(f"キャラクター '{character.character_name}' の言語設定ファイルの読み込み中にエラーが発生しました。")

                # QTスタイル設定 (オプション)
                qt_style_path = os.path.join(char_audio_dir, 'QT_style.json')
                if os.path.exists(qt_style_path):
                    with open(qt_style_path, 'r', encoding="utf-8") as f:
                        character.qt_css = f.read()

                self.character_class_list.append(character)

if __name__ == "__main__":
    # テスト実行ブロック
    loader = GetCharacterAttributes()
    logger.info(f"Total Characters: {loader.character_num}")
    
    if len(loader.character_class_list) > 0:
        logger.info("--- Character 1 Attributes ---")
        loader.character_class_list[0].log_attributes()
    
    if len(loader.character_class_list) > 1:
        logger.info("--- Character 2 Attributes ---")
        loader.character_class_list[1].log_attributes()