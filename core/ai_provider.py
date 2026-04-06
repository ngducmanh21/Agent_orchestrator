"""AI Provider - Interface with Claude API for code analysis."""
import hashlib
import logging
from typing import List, Optional

import anthropic
import httpx

from core.config import Config

logger = logging.getLogger(__name__)


class AIProvider:
    """Handles all AI interactions using Claude API."""

    def __init__(self, config: Config):
        self.config = config
        self.client = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        if config.anthropic_api_key:
            kwargs = {"api_key": config.anthropic_api_key}
            if config.anthropic_base_url:
                kwargs["base_url"] = config.anthropic_base_url
            self.client = anthropic.Anthropic(**kwargs)

    @property
    def is_available(self) -> bool:
        return self.client is not None

    @property
    def estimated_cost(self) -> float:
        """Estimate cost based on token usage (Claude Sonnet pricing)."""
        input_cost = (self.total_input_tokens / 1_000_000) * 3.0
        output_cost = (self.total_output_tokens / 1_000_000) * 15.0
        return round(input_cost + output_cost, 4)

    async def analyze_file(self, file_path: str, content: str, repo_name: str) -> str:
        """Generate AI insight for a single file."""
        if not self.is_available:
            return "⚠️ AI not configured. Set ANTHROPIC_API_KEY."

        prompt = f"""Bạn là một Senior Software Engineer đang phân tích codebase của dự án "{repo_name}".

Hãy giải thích file sau một cách ngắn gọn nhưng đầy đủ:

**File:** `{file_path}`

```
{content[:8000]}
```

Hãy trả lời bằng tiếng Việt với format:
## 📄 {file_path}

**Mục đích:** (1-2 câu mô tả chức năng chính)

**Chi tiết:**
- Các class/function chính và vai trò
- Dependencies và mối quan hệ với file khác
- Patterns được sử dụng (nếu có)

**Đánh giá:** (CORE/IMPORTANT/UTILITY/CONFIG)
"""

        try:
            response = self.client.messages.create(
                model=self.config.ai_model,
                max_tokens=self.config.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error analyzing file {file_path}: {e}")
            return f"❌ Error analyzing file: {str(e)}"

    async def ask_codebase(self, question: str, context_files: List[dict]) -> str:
        """Answer a question about the codebase using relevant context."""
        if not self.is_available:
            return "⚠️ AI not configured. Set ANTHROPIC_API_KEY."

        context = "\n\n".join([
            f"### File: `{f['path']}`\n```\n{f['content'][:4000]}\n```"
            for f in context_files[:10]
        ])

        prompt = f"""Bạn là một AI assistant chuyên phân tích codebase. Dựa trên context từ các file dưới đây, hãy trả lời câu hỏi.

## Context Files:
{context}

## Câu hỏi:
{question}

Hãy trả lời bằng tiếng Việt, chi tiết và chính xác. Reference đến file cụ thể khi cần."""

        try:
            response = self.client.messages.create(
                model=self.config.ai_model,
                max_tokens=self.config.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error asking codebase: {e}")
            return f"❌ Error: {str(e)}"

    async def analyze_cr(self, cr_description: str, codebase_summary: str, file_list: str) -> dict:
        """Analyze a Change Request - BA impact analysis + SA technical breakdown."""
        if not self.is_available:
            return {"ba": "⚠️ AI not configured.", "sa": "⚠️ AI not configured."}

        # Step 1: BA Analysis
        ba_prompt = f"""Bạn là một **Business Analyst** đang phân tích Change Request cho dự án.

## Mô tả Change Request:
{cr_description}

## Tổng quan Codebase:
{codebase_summary}

## Danh sách file hiện tại:
{file_list}

Hãy tạo **Impact Analysis** bằng tiếng Việt với format:

# 1. Business Analyst (Impact Analysis)

## Tóm tắt yêu cầu
(Diễn giải lại CR bằng ngôn ngữ business)

## Phạm vi ảnh hưởng
- Các module/component bị ảnh hưởng
- Các user flow thay đổi
- Rủi ro tiềm ẩn

## Đề xuất cho bước tiếp theo
- Những điểm cần làm rõ
- Gợi ý cho SA
"""

        # Step 2: SA Analysis
        sa_prompt = f"""Bạn là một **Solution Architect** đang thiết kế Technical Breakdown cho Change Request.

## Mô tả Change Request:
{cr_description}

## Tổng quan Codebase:
{codebase_summary}

## Danh sách file hiện tại:
{file_list}

Hãy tạo **Technical Breakdown** bằng tiếng Việt với format:

# 2. Solution Architect (Technical Breakdown)

## 1. DANH SÁCH FILE CẦN SỬA ĐỔI / TẠO MỚI

### Backend:
**Sửa đổi:**
- `path/to/file`: Mô tả thay đổi

**Tạo mới:**
- `path/to/new/file`: Mục đích

### Frontend:
**Sửa đổi:**
- `path/to/file`: Mô tả thay đổi

**Tạo mới:**
- `path/to/new/file`: Mục đích

## 2. TECHNICAL DESIGN
- Architecture changes
- API contracts
- Data model changes

## 3. IMPLEMENTATION PLAN
- Task breakdown với thứ tự ưu tiên
- Estimated effort cho mỗi task
- Dependencies giữa các task

## 4. TESTING STRATEGY
- Unit tests cần viết
- Integration test scenarios
"""

        try:
            # Run BA analysis
            ba_response = self.client.messages.create(
                model=self.config.ai_model,
                max_tokens=self.config.max_tokens,
                messages=[{"role": "user", "content": ba_prompt}],
            )
            self.total_input_tokens += ba_response.usage.input_tokens
            self.total_output_tokens += ba_response.usage.output_tokens

            # Run SA analysis
            sa_response = self.client.messages.create(
                model=self.config.ai_model,
                max_tokens=self.config.max_tokens,
                messages=[{"role": "user", "content": sa_prompt}],
            )
            self.total_input_tokens += sa_response.usage.input_tokens
            self.total_output_tokens += sa_response.usage.output_tokens

            return {
                "ba": ba_response.content[0].text,
                "sa": sa_response.content[0].text,
            }
        except Exception as e:
            logger.error(f"Error analyzing CR: {e}")
            return {"ba": f"❌ Error: {str(e)}", "sa": f"❌ Error: {str(e)}"}

    def get_simple_embedding(self, text: str) -> List[float]:
        """Generate a simple hash-based embedding for text.
        
        For production, replace with a proper embedding model (e.g., Voyage AI).
        This uses a deterministic hash-based approach for demo purposes.
        """
        import struct

        # Create a deterministic embedding from text hash
        text_bytes = text.encode('utf-8')
        embedding = []
        for i in range(self.config.embedding_dim):
            h = hashlib.md5(text_bytes + struct.pack('i', i)).digest()
            val = struct.unpack('f', h[:4])[0]
            # Normalize to [-1, 1]
            val = (val % 2.0) - 1.0
            embedding.append(val)

        # Normalize the vector
        norm = sum(v * v for v in embedding) ** 0.5
        if norm > 0:
            embedding = [v / norm for v in embedding]

        return embedding
