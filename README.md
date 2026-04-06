# 🤖 Agent Orchestrator

Hệ thống AI Agent để indexing codebase, tạo knowledge base cho dự án legacy, và hỗ trợ BA/SA phân tích Change Request.

## 🎯 Tính năng

| Tab | Mô tả |
|-----|-------|
| **Repo Index** | Hiển thị file tree với priority tags (CORE/OTHER), trạng thái indexed |
| **AI Insights** | Giải thích chi tiết từng file trong dự án bằng AI |
| **BA & SA Plan (CR)** | Phân tích Change Request: BA đánh giá impact, SA break down technical tasks |

## 🏗️ Kiến trúc

```
agent_orchestrator/
├── main.py                  # Entry point
├── core/
│   ├── config.py           # Configuration
│   ├── state.py            # Application state management
│   ├── ai_provider.py      # Claude AI integration
│   └── vector_store.py     # Qdrant vector database
├── modules/
│   ├── git_manager.py      # Git repository management
│   ├── scanner.py          # Codebase scanning & indexing
│   └── orchestrator.py     # Command handler & workflow
├── web/
│   ├── server.py           # FastAPI + WebSocket server
│   └── templates/
│       └── index.html      # Web UI (3 tabs)
├── docker-compose.yml       # Docker setup (App + Qdrant)
├── Dockerfile
└── requirements.txt
```

## 🚀 Quick Start

### 1. Cấu hình

```bash
cp .env.example .env
# Sửa ANTHROPIC_API_KEY trong .env
```

### 2. Chạy với Docker

```bash
docker-compose up --build
```

### 3. Mở trình duyệt

```
http://localhost:8080
```

## 📝 Các lệnh

| Lệnh | Mô tả |
|-------|--------|
| `/setup <url> [token]` | Clone/cấu hình GitHub repo |
| `/priority <folder1, folder2>` | Đặt priority folders cho scanning |
| `/scan` | Phân tích và index codebase vào Qdrant |
| `/ask <câu hỏi>` | Hỏi đáp trên codebase (semantic search) |
| `/cr <mô tả>` | Chạy luồng BA → SA phân tích Change Request |
| `/status` | Xem trạng thái hiện tại |
| `/stop` | Dừng tiến trình đang chạy |

## 🔧 Tech Stack

- **Backend**: Python, FastAPI, WebSocket
- **AI**: Claude API (Anthropic)
- **Vector DB**: Qdrant (semantic search)
- **Embedding**: Sentence-Transformers (lightweight hash-based)
- **Frontend**: Vanilla HTML/CSS/JS (dark theme)
- **Infra**: Docker Compose

## 🎯 Use Cases

1. **Indexing Legacy Codebase**: Quét 100% codebase, lưu embeddings vào Qdrant, tạo knowledge base
2. **AI Code Insights**: AI giải thích chi tiết từng file - chức năng, dependencies, patterns
3. **BA/SA Analysis**: Tự động phân tích Change Request, đề xuất files cần sửa/tạo mới
4. **Semantic Search**: Hỏi đáp tự nhiên trên codebase qua vector search
