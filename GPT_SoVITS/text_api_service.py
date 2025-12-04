

import json
import requests
import re
import os
import logging
from typing import List, Dict, Optional
from fastapi import HTTPException
from openai import OpenAI

# キャラクター設定クラスのインポート
from api_character_loader import CharacterAttributes

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleTextGenerator:
    """テキスト生成ロジックを管理するクラス (Gemini / ModelScope)"""

    def __init__(self, character_list: List[CharacterAttributes], gemini_keys: List[str], modelscope_keys: List[str]):
        """
        初期化処理
        :param character_list: キャラクター設定のリスト
        :param gemini_keys: Gemini APIキーのリスト
        :param modelscope_keys: ModelScope APIキーのリスト
        """
        self.character_list = character_list
        
        # APIキーの保存
        self.GEMINI_KEYS = gemini_keys
        self.MODELSCOPE_KEYS = modelscope_keys
        
        # キーローテーション用のインデックス
        self.gemini_key_index = 0
        self.modelscope_key_index = 0
        
        # --- Gemini 初期化 ---
        # キーリストが空の場合でもインデックスエラーを防ぐためのデフォルト値設定
        current_gemini_key = self.GEMINI_KEYS[0] if self.GEMINI_KEYS else ""
        self.headers = {
            "Content-Type": "application/json", 
            "X-goog-api-key": current_gemini_key
        }
        
        # --- ModelScope 初期化 ---
        current_ms_key = self.MODELSCOPE_KEYS[0] if self.MODELSCOPE_KEYS else "ms-default-token"
        self.client = OpenAI(
            base_url='https://api-inference.modelscope.cn/v1',
            api_key=current_ms_key,
        )
        self.modelscope_model_choice = "Qwen/Qwen3-Next-80B-A3B-Instruct"
        
        # --- 状態管理 ---
        self.all_character_msg = []
        self._load_history_from_json()

    def _load_history_from_json(self):
        """JSONファイルから会話履歴を読み込む"""
        for character in self.character_list:
            self.all_character_msg.append([])

        history_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reference_audio", "history_messages_dp.json"))
        if os.path.exists(history_file) and os.path.getsize(history_file) != 0:
            with open(history_file, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            for index, character in enumerate(self.character_list):
                for data in json_data:
                    if data['character'] == character.character_name:
                        cleaned_history = []
                        for msg in data['history']:
                            temp_msg = msg.copy()
                            cleaned_history.append(temp_msg)
                        self.all_character_msg[index] = cleaned_history    

    def save_history_to_json(self):
        """現在の会話履歴をJSONファイルに保存する"""
        final_data_dp = []
        for index, char_msg in enumerate(self.all_character_msg):
            char_name = self.character_list[index].character_name
            final_data_dp.append({'character': char_name, 'history': char_msg})

        history_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reference_audio", "history_messages_dp.json"))
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(final_data_dp, f, ensure_ascii=False, indent=4)

    def _update_api_key_in_headers(self, service_type: str):
        """
        サービスタイプに応じてヘッダーまたはクライアントのAPIキーを更新する
        :param service_type: 'gemini' または 'modelscope'
        """
        if service_type == "gemini" and self.GEMINI_KEYS:
            self.headers["X-goog-api-key"] = self.GEMINI_KEYS[self.gemini_key_index]
        elif service_type == "modelscope" and self.MODELSCOPE_KEYS:
            self.client.api_key = self.MODELSCOPE_KEYS[self.modelscope_key_index]

    def _rotate_api_key(self, service_type: str):
        """
        APIキーをローテーション（次のキーに切り替え）する
        :param service_type: 'gemini' または 'modelscope'
        """
        if service_type == "gemini":
            if self.GEMINI_KEYS:
                self.gemini_key_index = (self.gemini_key_index + 1) % len(self.GEMINI_KEYS)
                self._update_api_key_in_headers("gemini")
                logger.info(f"Gemini API Key rotated to index: {self.gemini_key_index}")
        elif service_type == "modelscope":
            if self.MODELSCOPE_KEYS:
                self.modelscope_key_index = (self.modelscope_key_index + 1) % len(self.MODELSCOPE_KEYS)
                self._update_api_key_in_headers("modelscope")
                logger.info(f"ModelScope API Key rotated to index: {self.modelscope_key_index}")

    def trim_list_to_64kb(self, data_list):
        """
        データリストのサイズを64KB以下にトリミングする
        (Vercel等のサーバーレス関数のペイロード制限対策)
        """
        MAX_SIZE = 64 * 1024 
        while len(json.dumps(data_list, ensure_ascii=False).encode('utf-8')) > MAX_SIZE:
            if len(data_list) > 1:
                del data_list[1]
            else:
                break
        return data_list

    async def generate_text_response_for_api(self,
                                            user_message: str,
                                            character_index: int,
                                            chat_history: List[Dict],
                                            language_choice: str,
                                            sakiko_state: bool,
                                            use_modelscope: bool,  # 呼び出し元でModelScopeを使用するか決定
                                            is_dual_character_mode: bool = False, 
                                            secondary_character_index: Optional[int] = None): 
        """
        APIを使用してテキスト応答を生成する
        """
        if not (0 <= character_index < len(self.character_list)):
            raise ValueError(f"Invalid character index: {character_index}")

        actual_speaker_index = character_index 
        
        # 2人のキャラクターモードの場合の発話者判定ロジック
        if is_dual_character_mode and secondary_character_index is not None and \
           user_message.strip().startswith('（') and '说道：' in user_message and \
           actual_speaker_index == character_index: 
            actual_speaker_index = secondary_character_index
        
        current_speaker_char = self.character_list[actual_speaker_index]
        char_name = current_speaker_char.character_name
        character_description = current_speaker_char.character_description

        # プロンプトの構築
        if use_modelscope:
            llm_base_role_prompt = f"现在你是角色 {char_name}。请根据你的设定：''''''{character_description}'''''，并结合之前的对话内容，回复用户。回复内容不要超过五句话，点到为止即可。如果有除了用户的其他角色发言，可以考虑顺便回复一下其他角色,而不是只回复用户。如要进行旁白式叙述，请放在括号内，不要直接作为台词说出来。不要总是重复同一角色说过的话。不要搞混角色和对应的发言。"
        else:
            llm_base_role_prompt = f"现在你是角色 {char_name}。请根据你的设定：''''''{character_description}'''''，并结合之前的对话内容，以第一人称回复用户。"

        llm_instruction_for_this_turn = ""
        if actual_speaker_index == character_index: 
            llm_instruction_for_this_turn = f"用户说：{user_message}"
        elif actual_speaker_index == secondary_character_index: 
            llm_instruction_for_this_turn = "请你根据之前的对话，以第一人称生成一段回复。" if not use_modelscope else "请你根据之前的对话，生成一段回复。"
        
        final_llm_prompt = f"{llm_base_role_prompt} {llm_instruction_for_this_turn}"

        # 言語設定に基づくプロンプト追加
        if language_choice == '日英混合':
            final_llm_prompt += '（本句话你的回答请务必用日语，并且请将额外的中文翻译内容放到“[翻译]”这一标记格式之后(不要加其他符号！不要把“翻译”二字改为其他语言！)，并以“[翻译结束]”作为翻译的结束标志（不要漏掉结束标志！不要把“翻译结束”四字改为其他语言！）如果生成内容超过三句，就拆成多段原文+翻译。不要重复输出翻译文本！也不要仿照聊天记录在对话加入“（XXX说道）”的字样！请务必严格遵守这一格式回答！！）'
        elif language_choice == '粤英混合':
            final_llm_prompt += '（本句话你的回答请务必用粤语，并且请将额外的中文翻译内容放到“[翻译]”这一标记格式之后(不要加其他符号！不要把“翻译”二字改为其他语言！)，并以“[翻译结束]”作为翻译的结束标志（不要漏掉结束标志！不要把“翻译结束”四字改为其他语言！）如果生成内容超过三句，就拆成多段原文+翻译。不要重复输出翻译文本！也不要仿照聊天记录在对话加入“（XXX说道）”的字样！请务必严格遵守这一格式回答！！）'
        else:
            final_llm_prompt += '（本句话你的回答请务必全部用中文，一定不要有日语假名或粤语！）'

        # キャラクター特有の状態（祥子）の処理
        if char_name == '祥子':
            if sakiko_state:
                final_llm_prompt += '（本句话用黑祥语气回答!）'
            else:
                final_llm_prompt += '（本句话用白祥语气回答!）'
        
        messages_for_llm = []
        for msg in chat_history:
            if msg["sender"] == "user":
                messages_for_llm.append({"role": "user", "content": msg["text"]})
            elif msg["sender"] == "ai":
                messages_for_llm.append({"role": "assistant", "content": msg["text"]})
        
        messages_for_llm.append({"role": "user", "content": final_llm_prompt})
        messages_for_llm = self.trim_list_to_64kb(messages_for_llm)

        
        # === 分岐: ModelScope 呼び出しロジック ===
        if use_modelscope:
            # ModelScopeのキーのみローテーション
            self._rotate_api_key("modelscope")

            openai_messages = []
            for msg in messages_for_llm:
                openai_messages.append({"role": msg["role"], "content": msg["content"]})

            try:
                response_stream = self.client.chat.completions.create(
                    model=self.modelscope_model_choice,
                    messages=openai_messages,
                    stream=True,
                    temperature=0.7,
                    top_p=0.95,
                    max_tokens=2048
                )

                full_response_content = ""
                for chunk in response_stream:
                    if chunk.choices[0].delta.content is not None:
                        full_response_content += chunk.choices[0].delta.content
                
                if not full_response_content:
                    logger.warning("Warning: ModelScope API response generated no content.")
                    return ("（AI响应未生成内容）", actual_speaker_index)

                return (full_response_content, actual_speaker_index)
                
            except Exception as e:
                logger.error(f"ModelScope API call failed: {e}")
                if "status code 401" in str(e):
                    raise HTTPException(status_code=401, detail="ModelScope APIキー認証エラー。正当性を確認してください。")
                elif "status code 429" in str(e):
                    raise HTTPException(status_code=429, detail="リクエスト頻度制限（Rate Limit）を超過しました。")
                else:
                    raise HTTPException(status_code=500, detail=f"ModelScope API呼び出し中に不明なエラーが発生しました: {e}")

        # === 分岐: Gemini 呼び出しロジック ===
        else:
            # Geminiのキーのみローテーション
            self._rotate_api_key("gemini")
            
            contents = []
            for msg in messages_for_llm:
                if msg["role"] == "user":
                    contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
                elif msg["role"] == "assistant":
                    contents.append({"role": "model", "parts": [{"text": msg["content"]}]})
            
            data = {
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.7,
                    "topP": 0.95,
                    "topK": 40,
                    "maxOutputTokens": 2048
                }
            }
            
            try:
                proxy_url = "https://geminiapi.asynchronousblocking.asia/v1beta/models/gemini-2.5-flash:generateContent"
                
                response = requests.post(proxy_url, headers=self.headers, json=data)
                response.raise_for_status() # ステータスコードが200以外の場合例外を送出
                
                response_json = response.json()
                
                if "candidates" in response_json and response_json["candidates"]:
                    candidate = response_json["candidates"][0]
                    if "finishReason" in candidate and candidate["finishReason"] == "MAX_TOKENS":
                        logger.warning("Warning: Gemini API response truncated due to MAX_TOKENS.")
                        return ("（AI响应因达到最大Token限制而未生成内容）", actual_speaker_index)
                    
                    if "content" in candidate and "parts" in candidate["content"]:
                        response_content = candidate["content"]["parts"][0]["text"]
                        return (response_content, actual_speaker_index)
                    else:
                        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンス形式エラー。内容：{response_json}")
                else:
                    raise HTTPException(status_code=500, detail=f"Gemini APIレスポンス形式エラー。内容：{response_json}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Gemini request error: {e}")

                if e.response is not None:
                    status_code = e.response.status_code
                    if status_code == 401:
                        raise HTTPException(status_code=401, detail="Gemini APIキー認証エラー。")
                    elif status_code == 429:
                        raise HTTPException(status_code=429, detail="リクエスト頻度制限（Rate Limit）を超過しました。")
                    elif status_code >= 500:
                        raise HTTPException(status_code=503, detail="Gemini/Proxy サーバーエラー。")
                    else:
                        raise HTTPException(status_code=status_code, detail=f"APIリクエスト失敗: {e}")
                else:
                    # e.response が None の場合（ネットワークエラー/DNSエラー等）
                    raise HTTPException(status_code=503, detail="Geminiプロキシサーバーに接続できません（ネットワークエラー/タイムアウト）。")