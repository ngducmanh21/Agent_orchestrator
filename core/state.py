"""State management for the Agent Orchestrator."""
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, List


class ScanStatus(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    INDEXING = "indexing"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class FileInfo:
    """Information about a scanned file."""
    path: str
    relative_path: str
    extension: str
    size_bytes: int
    priority_tag: str = "OTHER"  # CORE, PRIORITY, OTHER
    indexed: bool = False
    insight: str = ""  # AI-generated explanation
    last_indexed: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class RepoState:
    """State of a repository."""
    url: str = ""
    name: str = ""
    local_path: str = ""
    is_setup: bool = False
    priority_folders: List[str] = field(default_factory=list)
    files: Dict[str, FileInfo] = field(default_factory=dict)
    total_files: int = 0
    indexed_files: int = 0
    scan_status: ScanStatus = ScanStatus.IDLE
    scan_progress: float = 0.0
    current_file: str = ""
    estimated_cost: float = 0.0
    error_message: str = ""
    cr_results: Dict = field(default_factory=dict)

    def to_dict(self):
        d = {
            "url": self.url,
            "name": self.name,
            "local_path": self.local_path,
            "is_setup": self.is_setup,
            "priority_folders": self.priority_folders,
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "scan_status": self.scan_status.value,
            "scan_progress": self.scan_progress,
            "current_file": self.current_file,
            "estimated_cost": self.estimated_cost,
            "error_message": self.error_message,
            "files": {k: v.to_dict() for k, v in self.files.items()},
            "cr_results": self.cr_results,
        }
        return d


class AppState:
    """Global application state."""

    def __init__(self):
        self.repo: RepoState = RepoState()
        self.stop_requested: bool = False
        self.messages: List[Dict] = []  # Chat history
        self._listeners: List = []

    def add_message(self, role: str, content: str, msg_type: str = "info"):
        """Add a message to chat history."""
        msg = {
            "role": role,
            "content": content,
            "type": msg_type,
            "timestamp": time.time(),
        }
        self.messages.append(msg)
        return msg

    def reset(self):
        """Reset state for new session."""
        self.repo = RepoState()
        self.stop_requested = False
        self.messages = []

    def get_status_dict(self) -> dict:
        """Get current status as dictionary for WebSocket updates."""
        return {
            "repo": self.repo.to_dict(),
            "stop_requested": self.stop_requested,
            "message_count": len(self.messages),
        }
