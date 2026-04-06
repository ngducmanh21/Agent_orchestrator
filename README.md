# 🤖 Agent Orchestrator

Hệ thống AI Agent để indexing codebase, tạo knowledge base cho dự án legacy, và hỗ trợ BA/SA phân tích Change Request. Hỗ trợ chạy như **MCP Server** để tích hợp trực tiếp với VS Code (Cline/Cursor/Claude Code).

## 🎯 Tính năng

| Tab | Mô tả |
|-----|-------|
| **Repo Index** | Hiển thị file tree với priority tags (CORE/OTHER), trạng thái indexed |
| **AI Insights** | Giải thích chi tiết từng file trong dự án bằng AI |
| **BA & SA Plan (CR)** | Phân tích Change Request: BA đánh giá impact, SA break down technical tasks |
| **MCP Server** | Expose knowledge base + file operations cho VS Code coding agents |

## 🏗️ Kiến trúc

```
agent_orchestrator/
├── main.py                  # Entry point (--mcp flag for MCP mode)
├── core/
│   ├── config.py           # Configuration
│   ├── state.py            # Application state management
│   ├── ai_provider.py      # Claude AI integration
│   └── vector_store.py     # Qdrant vector database
├── mcp/
│   ├── __init__.py         # MCP package
│   ├── server.py           # MCP Server - tools for VS Code agents
│   └── server_lib.py       # MCP protocol library (JSON-RPC/stdio)
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

### 2. Chạy với Docker (Web UI + Qdrant)

```bash
docker-compose up --build
```

### 3. Mở trình duyệt

```
http://localhost:8080
```

### 4. Index codebase

Dùng Web UI: `/setup <repo_url>` → `/scan` → Knowledge base sẵn sàng.

## 📝 Các lệnh (Web UI)

| Lệnh | Mô tả |
|-------|--------|
| `/setup <url> [token]` | Clone/cấu hình GitHub repo |
| `/priority <folder1, folder2>` | Đặt priority folders cho scanning |
| `/scan` | Phân tích và index codebase vào Qdrant |
| `/ask <câu hỏi>` | Hỏi đáp trên codebase (semantic search) |
| `/cr <mô tả>` | Chạy luồng BA → SA phân tích Change Request |
| `/status` | Xem trạng thái hiện tại |
| `/stop` | Dừng tiến trình đang chạy |

---

## 🔌 MCP Server - VS Code Integration

Agent Orchestrator có thể chạy như một **MCP (Model Context Protocol) Server**, cho phép các coding agent trong VS Code (Cline, Cursor, Claude Code, v.v.) gọi trực tiếp vào knowledge base.

### Kiến trúc tổng quan

```
┌─────────────────────┐     stdio (JSON-RPC)     ┌──────────────────────┐
│   VS Code / Cline   │ ◄──────────────────────► │   MCP Server         │
│   Cursor / Claude    │                         │   (agent_orchestrator│
│   Code / Agent       │                         │    /mcp/server.py)   │
└─────────────────────┘                          └──────┬───────────────┘
                                                        │
                                           ┌────────────┼────────────────┐
                                           │            │                │
                                    ┌──────▼──┐  ┌──────▼──┐  ┌─────────▼──┐
                                    │  Claude │  │  Qdrant │  │ File System│
                                    │  API    │  │  Vector │  │ (repos)    │
                                    │         │  │  DB     │  │            │
                                    └─────────┘  └─────────┘  └────────────┘
```

### Cách chạy

#### Cách 1: Docker (Recommended) 🐳

Không cần cài Python/dependencies trên máy host. MCP client sẽ spawn Docker container:

```bash
# 1. Build image + start Qdrant
cd agent_orchestrator
docker compose up --build -d

# 2. MCP server sẽ được spawn tự động bởi VS Code qua script
#    (xem cấu hình bên dưới)
```

#### Cách 2: Native Python

```bash
cd agent_orchestrator
pip install -r requirements.txt
python main.py --mcp
```

### Cấu hình trong VS Code (Cline) - Docker

Thêm vào file `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "agent-orchestrator": {
      "command": "/absolute/path/to/agent_orchestrator/mcp/run_mcp_docker.sh",
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here",
        "ANTHROPIC_BASE_URL": "https://your-proxy-if-needed",
        "QDRANT_HOST": "localhost"
      }
    }
  }
}
```

### Cấu hình trong Cursor - Docker

Thêm vào `.cursor/mcp.json` trong project root:

```json
{
  "mcpServers": {
    "agent-orchestrator": {
      "command": "/absolute/path/to/agent_orchestrator/mcp/run_mcp_docker.sh",
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here",
        "QDRANT_HOST": "localhost"
      }
    }
  }
}
```

### Cấu hình Native (không Docker)

Nếu chạy native Python thay vì Docker:

```json
{
  "mcpServers": {
    "agent-orchestrator": {
      "command": "python",
      "args": ["/absolute/path/to/agent_orchestrator/main.py", "--mcp"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here",
        "QDRANT_HOST": "localhost",
        "QDRANT_PORT": "6333",
        "REPOS_DIR": "/absolute/path/to/agent_orchestrator/data/repos"
      }
    }
  }
}
```

### MCP Tools có sẵn

| Tool | Mô tả |
|------|--------|
| `list_projects` | Liệt kê các project đã index |
| `get_project_structure` | Xem cấu trúc thư mục project |
| `read_file` | Đọc nội dung file (hỗ trợ line range) |
| `write_file` | Tạo/ghi đè file |
| `edit_file` | Sửa file bằng search/replace blocks |
| `delete_file` | Xóa file hoặc thư mục |
| `search_codebase` | Semantic search trên Qdrant knowledge base |
| `grep_search` | Tìm kiếm regex trong codebase |
| `ask_about_code` | Hỏi AI về codebase (RAG: search + AI answer) |
| `list_files` | Liệt kê files với filter pattern |
| `run_command` | Chạy shell command trong project |
| `delete_project` | Xóa project khỏi knowledge base |

### Workflow thực tế

1. **Index codebase** qua Web UI: `/setup <repo_url>` → `/scan`
2. **Kết nối MCP** trong VS Code (Cline/Cursor) theo config ở trên
3. **Coding agent** trong VS Code giờ có thể:
   - `search_codebase` để tìm code liên quan
   - `ask_about_code` để hỏi AI về kiến trúc
   - `read_file` / `edit_file` / `write_file` để thao tác code
   - `grep_search` để tìm pattern
   - `run_command` để build/test

---

## 🔧 Tech Stack

- **Backend**: Python, FastAPI, WebSocket
- **AI**: Claude API (Anthropic)
- **Vector DB**: Qdrant (semantic search)
- **Embedding**: Sentence-Transformers (lightweight hash-based)
- **MCP**: Model Context Protocol (stdio JSON-RPC)
- **Frontend**: Vanilla HTML/CSS/JS (dark theme)
- **Infra**: Docker Compose

## 🎯 Use Cases

1. **Indexing Legacy Codebase**: Quét 100% codebase, lưu embeddings vào Qdrant, tạo knowledge base
2. **AI Code Insights**: AI giải thích chi tiết từng file - chức năng, dependencies, patterns
3. **BA/SA Analysis**: Tự động phân tích Change Request, đề xuất files cần sửa/tạo mới
4. **Semantic Search**: Hỏi đáp tự nhiên trên codebase qua vector search
