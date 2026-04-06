"""Orchestrator - Command handler and workflow coordinator."""
import asyncio
import logging
from typing import Callable, Optional

from core.ai_provider import AIProvider
from core.config import Config
from core.state import AppState, ScanStatus
from core.vector_store import VectorStore
from modules.git_manager import GitManager
from modules.scanner import Scanner

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestrator that coordinates all modules."""

    def __init__(self, config: Config):
        self.config = config
        self.state = AppState()
        self.ai = AIProvider(config)
        self.vector_store = VectorStore(config)
        self.git_manager = GitManager(config)
        self.scanner = Scanner(config, self.state, self.ai, self.vector_store)
        self._on_message: Optional[Callable] = None

    async def initialize(self):
        """Initialize connections."""
        connected = await self.vector_store.connect()
        if not connected:
            logger.warning("Could not connect to Qdrant. Some features may be limited.")

    def set_message_handler(self, handler: Callable):
        """Set callback for sending messages to UI."""
        self._on_message = handler

    async def _send(self, content: str, msg_type: str = "info"):
        """Send a message to the UI."""
        self.state.add_message("system", content, msg_type)
        if self._on_message:
            await self._on_message(content, msg_type)

    async def handle_command(self, raw_input: str):
        """Parse and execute a command."""
        raw_input = raw_input.strip()
        if not raw_input:
            return

        if raw_input.startswith("/"):
            parts = raw_input.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            command_map = {
                "/help": self.cmd_help,
                "/setup": self.cmd_setup,
                "/priority": self.cmd_priority,
                "/scan": self.cmd_scan,
                "/ask": self.cmd_ask,
                "/cr": self.cmd_cr,
                "/stop": self.cmd_stop,
                "/status": self.cmd_status,
            }

            handler = command_map.get(command)
            if handler:
                self.state.add_message("user", raw_input, "command")
                await handler(args)
            else:
                await self._send(f"❌ Lệnh không hợp lệ: {command}. Gõ /help để xem danh sách.", "error")
        else:
            # Treat as a question
            self.state.add_message("user", raw_input, "question")
            await self.cmd_ask(raw_input)

    async def cmd_help(self, args: str = ""):
        """Show help message."""
        help_text = """**Danh sách lệnh:**
- `/setup <url_github> [token]` : Cấu hình Repo
- `/priority <folder1, folder2>` : Xác định core logic cho CR
- `/scan` : Phân tích và Index Codebase vào Qdrant
- `/ask <câu hỏi>` : Hỏi đáp trên codebase (semantic search)
- `/cr <Mô tả JIRA>` : Chạy luồng BA -> SA break down task
- `/status` : Xem trạng thái hiện tại
- `/stop` : Dừng tiến trình"""
        await self._send(help_text, "help")

    async def cmd_setup(self, args: str = ""):
        """Setup a repository."""
        if not args:
            await self._send("❌ Thiếu URL. Ví dụ: `/setup https://github.com/user/repo`", "error")
            return

        parts = args.split()
        url = parts[0]
        token = parts[1] if len(parts) > 1 else None

        try:
            await self._send(f"🔄 Đang clone repository...", "progress")
            local_path, repo_name = self.git_manager.setup_repo(url, token)

            self.state.repo.url = url
            self.state.repo.name = repo_name
            self.state.repo.local_path = local_path
            self.state.repo.is_setup = True
            self.state.repo.priority_folders = list(self.config.priority_folders)

            repo_info = self.git_manager.get_repo_info(local_path)

            await self._send(
                f"✅ Đã setup repo: **{repo_name}**\n"
                f"   Branch: {repo_info.get('branch', 'N/A')}\n"
                f"   Last commit: {repo_info.get('commit_message', 'N/A')}",
                "success",
            )
        except Exception as e:
            await self._send(f"❌ Lỗi setup: {str(e)}", "error")

    async def cmd_priority(self, args: str = ""):
        """Set priority folders."""
        if not args:
            current = ", ".join(self.state.repo.priority_folders or self.config.priority_folders)
            await self._send(f"📂 Priority hiện tại: [{current}]", "info")
            return

        folders = [f.strip() for f in args.split(",")]
        self.state.repo.priority_folders = folders
        await self._send(
            f"✅ Đã cập nhật priority folders: [{', '.join(folders)}]",
            "success",
        )

    async def cmd_scan(self, args: str = ""):
        """Scan and index the codebase."""
        if not self.state.repo.is_setup:
            await self._send("❌ Chưa setup repo. Dùng `/setup <url>` trước.", "error")
            return

        if not self.vector_store.is_connected:
            await self._send("❌ Không kết nối được Qdrant. Kiểm tra service.", "error")
            return

        priority = ", ".join(self.state.repo.priority_folders or self.config.priority_folders)

        async def on_progress(event: str, data: dict):
            if event == "scan_start":
                await self._send(
                    f"⚡ Đã lấy {data['total']} files. "
                    f"Ưu tiên các thư mục: [{priority}]. Bắt đầu Indexing...",
                    "progress",
                )
            elif event == "file_indexed":
                if data["current"] % 5 == 0 or data["current"] == data["total"]:
                    await self._send(
                        f"🔄 Reading [{data['current']}/{data['total']}]: "
                        f"{self.state.repo.name}/{data['file']}",
                        "progress",
                    )
            elif event == "scan_complete":
                await self._send(
                    f"✅ Hoàn tất indexing! {data['indexed']}/{data['total']} files "
                    f"đã được lưu vào Qdrant.\n"
                    f"💰 Est. Cost: ${self.ai.estimated_cost:.4f}",
                    "success",
                )

        try:
            await self.scanner.scan_and_index(on_progress=on_progress)
        except Exception as e:
            await self._send(f"❌ Lỗi scanning: {str(e)}", "error")

    async def cmd_ask(self, args: str = ""):
        """Ask a question about the codebase."""
        if not args:
            await self._send("❌ Thiếu câu hỏi. Ví dụ: `/ask Cấu trúc dự án như thế nào?`", "error")
            return

        if not self.state.repo.is_setup:
            await self._send("❌ Chưa setup repo. Dùng `/setup <url>` trước.", "error")
            return

        await self._send(f"🔍 Đang tìm kiếm context liên quan...", "progress")

        # Search relevant files from Qdrant
        relevant_files = await self.scanner.search_relevant_files(args, limit=10)

        if not relevant_files:
            await self._send("⚠️ Không tìm thấy file liên quan. Hãy `/scan` trước.", "warning")
            return

        await self._send(
            f"📚 Tìm thấy {len(relevant_files)} files liên quan. Đang phân tích...",
            "progress",
        )

        # Ask AI with context
        answer = await self.ai.ask_codebase(args, relevant_files)
        self.state.repo.estimated_cost = self.ai.estimated_cost

        await self._send(answer, "answer")
        await self._send(f"💰 Est. Cost: ${self.ai.estimated_cost:.4f}", "info")

    async def cmd_cr(self, args: str = ""):
        """Analyze a Change Request - BA + SA flow."""
        if not args:
            await self._send(
                "❌ Thiếu mô tả CR. Ví dụ: `/cr Tích hợp API thanh toán VNPay`",
                "error",
            )
            return

        if not self.state.repo.is_setup:
            await self._send("❌ Chưa setup repo. Dùng `/setup <url>` trước.", "error")
            return

        await self._send("✅ Bắt đầu tiến trình phân tích Change Request...", "progress")

        # Build codebase summary
        file_list = "\n".join([
            f"- `{f.relative_path}` ({f.priority_tag})"
            for f in self.state.repo.files.values()
        ][:50])

        codebase_summary = (
            f"Repo: {self.state.repo.name}\n"
            f"Total files: {self.state.repo.total_files}\n"
            f"Indexed: {self.state.repo.indexed_files}\n"
        )

        # Step 1: BA Analysis
        await self._send("⚡ [BA] Đang đánh giá tác động của CR lên hệ thống...", "progress")
        await asyncio.sleep(0.5)

        result = await self.ai.analyze_cr(args, codebase_summary, file_list)

        await self._send("✅ [BA] Đã hoàn thành bản Impact Analysis.", "success")

        # Step 2: SA Analysis
        await self._send("⚡ [SA] Đang Break-down requirements thành Technical Tasks...", "progress")
        await asyncio.sleep(0.5)

        await self._send("✅ [SA] Đã thiết kế xong Technical Breakdown Plan.", "success")

        # Store results
        self.state.repo.cr_results = {
            "description": args,
            "ba": result["ba"],
            "sa": result["sa"],
        }
        self.state.repo.estimated_cost = self.ai.estimated_cost

        await self._send(
            "🎉 Hoàn tất! Hãy xem kết quả chi tiết ở Panel bên phải (Tab BA & SA Plan).\n"
            f"💰 Est. Cost: ${self.ai.estimated_cost:.4f}",
            "success",
        )

    async def cmd_stop(self, args: str = ""):
        """Stop current operation."""
        self.state.stop_requested = True
        await self._send("🛑 Đang dừng tiến trình...", "warning")

    async def cmd_status(self, args: str = ""):
        """Show current status."""
        repo = self.state.repo
        if not repo.is_setup:
            await self._send("ℹ️ Chưa setup repo nào.", "info")
            return

        info = self.vector_store and await self.vector_store.get_collection_info()
        qdrant_status = f"Qdrant: {info['points_count']} vectors" if info else "Qdrant: disconnected"

        status = (
            f"**📊 Status:**\n"
            f"   Repo: {repo.name} ({repo.url})\n"
            f"   Files: {repo.indexed_files}/{repo.total_files}\n"
            f"   Status: {repo.scan_status.value}\n"
            f"   {qdrant_status}\n"
            f"   Priority: [{', '.join(repo.priority_folders)}]\n"
            f"   💰 Est. Cost: ${self.ai.estimated_cost:.4f}"
        )
        await self._send(status, "info")
