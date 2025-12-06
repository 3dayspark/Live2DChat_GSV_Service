# AI/Live2D Character Chat Application

## プロジェクト構成について (Project Structure)

本リポジトリは、「AI/Live2D キャラクターチャットアプリケーション」**における**メインバックエンド（LLM制御・GPT-SoVITS音声合成）を担当するプロジェクトです。

システム全体は以下の3つのリポジトリで構成されています：

*   Backend (Main): 本リポジトリ (LLM & GPT-SoVITS)
    *   役割: LLMとの対話生成、感情分析、GPT-SoVITSによる音声合成、全体オーケストレーション
*   [Frontend: Live2D & Vue.js](https://gitee.com/thdayspk/Live2DChat_Vue)
    *   役割: Live2Dモデルの描画、チャットUI、リップシンク制御
*   [Microservice: RVC Service](https://gitee.com/thdayspk/Live2DChat_RVC_Service)
    *   役割: 外部TTS音声の声質変換 (RVC) を行う独立したマイクロサービス



## 概要 (Overview)
LLM（大規模言語モデル）とLive2D、そして最新の音声合成技術（GPT-SoVITS, RVC）を統合した、リアルタイム・ウェブ対話アプリケーションです。

単なるチャットボットではなく、「感情表現」と「音声の即時性」に焦点を当て、ユーザー入力に対するテキスト生成、感情分析、音声合成、そしてLive2Dモデルの表情・口パク（リップシンク）同期を低遅延で実現しています。

## デモ機能 (Key Features)

*   **マルチモーダルな対話体験:** テキスト、音声、視覚（Live2Dモーション）が同期した没入感のある体験を提供。
*   **高度な音声合成パイプライン:**
    *   **GPT-SoVITS:** 少量のデータで高品質なキャラクター学習・推論。
    *   **RVC (Retrieval-based Voice Conversion):** 外部TTS（Azure, Gemini, EdgeTTS）の出力音声をキャラクターの声質へリアルタイム変換。
*   **感情認識と表現:** 入力/出力テキストから感情（喜び、怒り、悲しみ等）を推論し、Live2Dモデルの表情とモーションを自動制御。
*   **デュアルキャラクターモード:** 2体のAIキャラクター同士が会話する様子を観察できる自律対話モードを実装。
*   **レスポンシブUI:** PCおよびモバイル端末（タッチ操作）に最適化されたVue.jsフロントエンド。

## 技術スタック (Tech Stack)

### Backend (Python / FastAPI)
*   **Framework:** FastAPI (Asynchronous I/O)
*   **LLM Integration:** Gemini API, ModelScope (OpenAI Compatible)
*   **Audio Synthesis:** GPT-SoVITS, RVC (Retrieval-based Voice Conversion), EdgeTTS, AzureTTS
*   **ML/NLP:** PyTorch, Transformers (BERT/Hubert based Emotion Detection)
*   **Architecture:** Microservices approach (Main API + Isolated RVC Service)

### Frontend (TypeScript / Vue 3)
*   **Framework:** Vue 3 (Composition API), Vite
*   **Rendering:** PixiJS, pixi-live2d-display (Live2D Cubism SDK integration)
*   **Audio:** Web Audio API (Real-time frequency analysis for lip-sync)

## システムアーキテクチャ (System Architecture)

本プロジェクトは、スケーラビリティと応答速度を確保するために、推論処理を適切に分離した設計を採用しています。

<img src="./assets/architecture.png" alt="Architecture Diagram" width="800">


## 技術的なこだわり (Technical Highlights)

### 1. 推論プロセスの非同期化と排他制御 (Backend)
GPT-SoVITSなどの重い推論処理がWebサーバーのイベントループをブロックしないよう、`multiprocessing` モジュールを使用した独自のプロセスマネージャー (`GPTSovitsProcessManager`) を実装しました。
*   **Multiprocessing & Queues:** 推論を別プロセスで実行し、キューを通じてデータをやり取りすることで、APIの応答性を維持。
*   **Locking Mechanism:** 複数のリクエストが同時に来た際のモデル切り替えや推論の競合を防ぐため、スレッドロックによる排他制御を実装。

### 2. ハイブリッド音声合成パイプライン (Backend)
シナリオに応じて最適な音声合成方式を選択できる柔軟な設計にしました。
*   **GPT-SoVITS:** 感情表現が重要な場面で使用。
*   **TTS + RVC:** 長文や高速な応答が必要な場面で、EdgeTTSやAzureTTSで生成した音声をRVCでキャラクターの声に変換し、低遅延と品質を両立。

### 3. フロントエンドでのリアルタイム・リップシンク (Frontend)
サーバーサイドでリップシンクデータを生成するのではなく、フロントエンドの `Web Audio API` (`AnalyserNode`) を使用して音声の周波数データをリアルタイム解析。
*   音量レベルに応じてLive2Dの `PARAM_MOUTH_OPEN_Y` パラメータを動的に制御し、自然な口の動きを実現。これによりサーバー負荷と通信量を削減しました。

### 4. 感情駆動のモーション制御
BERTベースの感情分析モデル (`emotion_detect.py`) により、テキストから7種類の感情（happiness, sadness, anger, etc.）を分類。フロントエンド側で感情ラベルを受け取り、Live2Dの適切なモーション・表情ファイルへマッピングして再生します。

## ディレクトリ構成 (Directory Structure)

```text
.
├── Live2DChat_GSV_LLM_Service/
│   └── GPT_SoVITS/             # Main Backend Source Code
│       ├── fastapi_main.py     # Entry point, API Routes
│       ├── audio_api_service.py # Audio synthesis logic router
│       ├── text_api_service.py # LLM integration logic
│       ├── gptsovits_process_manager.py # Multiprocessing manager for inference
│       ├── api_character_loader.py # Character configuration loader
│       ├── emotion_detect.py   # Emotion classification model
│       ├── inference_webui.py  # GPT-SoVITS inference logic
│       └── ...                 # Other configs and models
├── Live2DChat_Vue/        # Vue.js Frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatInterface.vue # Chat UI & Logic
│   │   │   └── Live2DCanvas.vue  # Live2D rendering & Motion control
│   │   └── api/                  # Axios API wrappers
│   └── ...
└── Live2DChat_RVC_Service/          # RVC Microservice
    └── rvc_api_service.py      # Independent API for RVC Voice Conversion
```

## 今後の展望 (Future Improvements)

*   **WebSocket化:** 現在のポーリング/HTTPリクエストベースからWebSocketへ移行し、ストリーミング音声再生による更なる低遅延化。
*   **記憶の長期保存:** Vector Database (RAG) を導入し、過去の会話内容に基づいたより深い文脈理解。
*   **Docker化:** マイクロサービス構成（Main API, RVC Service, Frontend）のコンテナオーケストレーション。


## セットアップと実行に関する注意 (Note on Setup & Execution)

本リポジトリはポートフォリオとして公開しており、ソースコードの閲覧を主目的としています。
以下の理由により、`git clone` 直後の動作は保証しておりません。

1.  **著作権保護:** 商用または著作権のあるLive2Dモデルデータ、および特定の音声素材はリポジトリに含まれていません。
2.  **ファイルサイズ制限:** GPT-SoVITSやRVCの学習済みモデル（重みファイル）などの大容量バイナリファイルは `.gitignore` により除外されています。


### 必要なファイル構成 (Missing Files Structure)
ローカルで実行する場合、以下を含む（ただしこれらに限定されない）適切なモデルファイルや素材を配置する必要があります：

*   `Chat_backend/GPT_SoVITS/pretrained_models/` ... GPT-SoVITSモデル
*   `Chat_backend/reference_audio/` ... 参照音声ファイル
*   `pixi-live2d-display/public/models/` ... Live2Dモデルデータ