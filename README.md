<div align="center">
  <a href="#jp">🇯🇵 日本語</a> | <a href="#en">🇺🇸 English</a>
</div>

<span id="jp"></span>

# AI/Live2D Character Chat Application

## プロジェクト構成について (Project Structure)

本リポジトリは、「AI/Live2D キャラクターチャットアプリケーション」**における**メインバックエンド（LLM制御・GPT-SoVITS音声合成）を担当するプロジェクトです。

システム全体は以下の3つのリポジトリで構成されています：

*   **Backend (Main): 本リポジトリ (LLM & GPT-SoVITS)**
    *   役割: LLMとの対話生成、感情分析、GPT-SoVITSによる音声合成、全体オーケストレーション
*   [Frontend: Live2D & Vue.js](https://github.com/3dayspark/Live2DChat_Vue)
    *   役割: Live2Dモデルの描画、チャットUI、リップシンク制御
*   [Microservice: RVC Service](https://github.com/3dayspark/Live2DChat_RVC_Service)
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

## 今後の展望: 大規模並行処理に向けたアーキテクチャの進化 (Future Roadmap: Scaling Architecture)

現在の `multiprocessing` ベースの設計は単一ノードでの効率性を重視していますが、将来的なリクエスト増大に対応するため、以下の段階的なクラウドネイティブ移行を計画しています。

### 1. サービスの完全な疎結合化 (Service Decoupling)
*   **現状:** テキスト処理（Gateway）と音声推論（Worker）が同一Pod内で稼働。
*   **計画:** これらを独立したマイクロサービスとして分離します。
    *   **Gateway Service (CPU-bound):** 軽量なHTTPリクエスト処理とLLM通信を担当。CPU負荷に応じて安価に水平スケール可能にします。
    *   **Inference Service (GPU-bound):** GPT-SoVITSなどの重い処理を担当。GPUリソースに特化して管理します。

### 2. Redisによる非同期メッセージキューの導入 (Redis Message Queue)
*   **現状:** Python標準の `multiprocessing.Queue` を使用（単一サーバー内での通信）。
*   **計画:** プロセス間通信を **Redis** を介した非同期メッセージングに置き換えます。これにより、複数の推論ノード間での負荷分散が可能になり、障害時の再試行（Retries）や永続化も容易になります。

### 3. Kubernetesでのモデル常駐化と「冷間始動」の解決 (Zero Cold Start Strategy)
単純なロードバランシングでは、リクエストごとに異なるキャラクターモデルのロード/アンロードが発生し、レスポンスが遅延する課題があります。これを解決するために以下を導入します。
*   **キャラクター別専用キュー (Character-Specific Queues):**
    *   GatewayはキャラクターIDに基づき、`queue:sakiko`, `queue:anon` といった特定のRedisリストへタスクを振り分けます。
*   **Workerの専任化:**
    *   特定のWorker Podは特定のキューのみを監視（Subscribe）し、モデルをメモリに常駐させます。これにより、**モデル切り替えコストをゼロ**にし、即応性を最大化します。

### 4. FinOps視点でのコスト最適化 (Cost Optimization)
*   **Spot Instanceの活用:** 
    *   常時稼働させるベースラインのノードにはオンデマンドインスタンスを使用し、バースト的なトラフィックに対しては、安価な **Spot Instances**（AWS/GCP）で自動スケール（KEDA利用）する構成へ移行します。
*   **GPU Sharing:**
    *   NVIDIA Time-Slicing等を活用し、単一のGPUノード内で複数の推論Podを稼働させることで、ハードウェアリソースの利用効率を最大化します。

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

---

<span id="en"></span>

# AI/Live2D Character Chat Application

## Project Structure

This repository is the **Main Backend (LLM Control & GPT-SoVITS Audio Synthesis)** for the "AI/Live2D Character Chat Application".

The entire system consists of the following three repositories:

*   **Backend (Main): This Repository (LLM & GPT-SoVITS)**
    *   Role: Dialogue generation with LLM, Emotion analysis, Audio synthesis via GPT-SoVITS, and Overall orchestration.
*   [Frontend: Live2D & Vue.js](https://github.com/3dayspark/Live2DChat_Vue)
    *   Role: Rendering Live2D models, Chat UI, and Lip-sync control.
*   [Microservice: RVC Service](https://github.com/3dayspark/Live2DChat_RVC_Service)
    *   Role: An independent microservice for Real-time Voice Conversion (RVC) using external TTS audio.

## Overview
A real-time web dialogue application integrating Large Language Models (LLM), Live2D, and state-of-the-art speech synthesis technologies (GPT-SoVITS, RVC).

More than just a chatbot, this project focuses on **"Emotional Expression"** and **"Audio Immediacy."** It realizes low-latency text generation, emotion analysis, speech synthesis, and synchronized Live2D facial expressions/lip-syncing in response to user input.

## Key Features

*   **Multimodal Dialogue Experience:** Provides an immersive experience where Text, Audio, and Visuals (Live2D motion) are synchronized.
*   **Advanced Audio Synthesis Pipeline:**
    *   **GPT-SoVITS:** High-quality character training and inference with small datasets.
    *   **RVC (Retrieval-based Voice Conversion):** Real-time conversion of output audio from external TTS (Azure, Gemini, EdgeTTS) into the target character's voice.
*   **Emotion Recognition & Expression:** Infers emotions (Joy, Anger, Sorrow, etc.) from input/output text to automatically control Live2D facial expressions and motions.
*   **Dual Character Mode:** Implements an autonomous dialogue mode where users can observe two AI characters talking to each other.
*   **Responsive UI:** A Vue.js frontend optimized for both PC and mobile devices (touch operations).

## Tech Stack

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

## System Architecture

This project adopts a decoupled design to ensure scalability and response speed.

<img src="./assets/architecture.png" alt="Architecture Diagram" width="800">

## Technical Highlights

### 1. Asynchronous Inference & Exclusive Control (Backend)
To prevent heavy inference processes like GPT-SoVITS from blocking the web server's event loop, I implemented a custom process manager (`GPTSovitsProcessManager`) using the `multiprocessing` module.
*   **Multiprocessing & Queues:** Maintains API responsiveness by executing inference in separate processes and exchanging data via queues.
*   **Locking Mechanism:** Implements exclusive control using thread locks to prevent model switching conflicts or inference race conditions when multiple requests arrive simultaneously.

### 2. Hybrid Audio Synthesis Pipeline (Backend)
Designed flexibly to select the optimal speech synthesis method depending on the scenario.
*   **GPT-SoVITS:** Used when emotional expression is critical.
*   **TTS + RVC:** Used for long texts or when high-speed response is required. It converts audio generated by EdgeTTS or AzureTTS into the character's voice using RVC, balancing low latency and quality.

### 3. Real-time Frontend Lip-sync (Frontend)
Instead of generating lip-sync data on the server side, the frontend uses the `Web Audio API` (`AnalyserNode`) to analyze audio frequency data in real-time.
*   Dynamically controls the Live2D `PARAM_MOUTH_OPEN_Y` parameter based on volume levels to achieve natural mouth movements. This reduces server load and data traffic.

### 4. Emotion-Driven Motion Control
A BERT-based emotion analysis model (`emotion_detect.py`) classifies text into 7 types of emotions (happiness, sadness, anger, etc.). The frontend receives the emotion label and maps it to the appropriate Live2D motion/expression files for playback.

## Directory Structure

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

## Future Roadmap: Scaling Architecture

While the current `multiprocessing`-based design prioritizes efficiency on a single node, I plan a phased migration to cloud-native architecture to handle future increases in requests.

### 1. Service Decoupling
*   **Current:** Text processing (Gateway) and Audio Inference (Worker) run within the same Pod.
*   **Plan:** Separate these into independent microservices.
    *   **Gateway Service (CPU-bound):** Handles lightweight HTTP requests and LLM communication. Can be horizontally scaled cheaply based on CPU load.
    *   **Inference Service (GPU-bound):** Handles heavy processing like GPT-SoVITS. Managed with a focus on GPU resources.

### 2. Redis Message Queue Implementation
*   **Current:** Uses Python's standard `multiprocessing.Queue` (communication within a single server).
*   **Plan:** Replace inter-process communication with asynchronous messaging via **Redis**. This enables load balancing across multiple inference nodes and facilitates retries and persistence during failures.

### 3. Kubernetes Model Residency & Zero Cold Start Strategy
Simple load balancing causes delays due to loading/unloading different character models for each request. To solve this:
*   **Character-Specific Queues:**
    *   The Gateway distributes tasks to specific Redis lists like `queue:sakiko`, `queue:anon` based on Character ID.
*   **Worker Specialization:**
    *   Specific Worker Pods subscribe only to specific queues and keep the model resident in memory. This achieves **zero model switching cost** and maximizes responsiveness.

### 4. Cost Optimization (FinOps)
*   **Spot Instances:**
    *   Use On-Demand instances for baseline nodes that run constantly, and migrate to a configuration that auto-scales (using KEDA) with cheaper **Spot Instances** (AWS/GCP) for burst traffic.
*   **GPU Sharing:**
    *   Utilize NVIDIA Time-Slicing to run multiple inference Pods within a single GPU node, maximizing hardware resource efficiency.

## Note on Setup & Execution

This repository is published as a portfolio, primarily for the purpose of viewing source code.
Operation immediately after `git clone` is not guaranteed for the following reasons:

1.  **Copyright Protection:** Commercial or copyrighted Live2D model data and specific audio assets are not included in the repository.
2.  **File Size Limits:** Large binary files such as pre-trained models (weights) for GPT-SoVITS and RVC are excluded via `.gitignore`.

### Missing Files Structure
To run locally, you need to place appropriate model files and assets including (but not limited to) the following:

*   `Chat_backend/GPT_SoVITS/pretrained_models/` ... GPT-SoVITS models
*   `Chat_backend/reference_audio/` ... Reference audio files
*   `pixi-live2d-display/public/models/` ... Live2D model data