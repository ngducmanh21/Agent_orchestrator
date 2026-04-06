"""Git Repository Manager - Clone and manage repositories."""
import logging
import os
import re
from typing import Optional, Tuple

import git

from core.config import Config

logger = logging.getLogger(__name__)


class GitManager:
    """Manages git repository operations."""

    def __init__(self, config: Config):
        self.config = config

    def parse_github_url(self, url: str) -> Tuple[str, str]:
        """Parse GitHub URL to extract owner/repo name.
        
        Returns:
            Tuple of (clone_url, repo_name)
        """
        url = url.strip().rstrip("/")

        # Handle various URL formats
        patterns = [
            r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$",
            r"^([^/]+/[^/]+)$",  # owner/repo format
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                repo_path = match.group(1)
                repo_name = repo_path.split("/")[-1]
                if not url.startswith("http"):
                    clone_url = f"https://github.com/{repo_path}.git"
                else:
                    clone_url = url if url.endswith(".git") else f"{url}.git"
                return clone_url, repo_name

        raise ValueError(f"Invalid GitHub URL: {url}")

    def setup_repo(self, url: str, token: Optional[str] = None) -> Tuple[str, str]:
        """Clone or update a repository.
        
        Args:
            url: GitHub URL or owner/repo
            token: Optional GitHub token for private repos
            
        Returns:
            Tuple of (local_path, repo_name)
        """
        clone_url, repo_name = self.parse_github_url(url)

        # Insert token if provided
        if token:
            clone_url = clone_url.replace("https://", f"https://{token}@")

        local_path = os.path.join(self.config.repos_dir, repo_name)

        if os.path.exists(local_path):
            # Update existing repo
            try:
                repo = git.Repo(local_path)
                origin = repo.remotes.origin
                origin.pull()
                logger.info(f"Updated repository: {repo_name}")
            except Exception as e:
                logger.warning(f"Could not pull updates: {e}. Using existing copy.")
        else:
            # Clone new repo
            os.makedirs(self.config.repos_dir, exist_ok=True)
            try:
                git.Repo.clone_from(clone_url, local_path, depth=1)
                logger.info(f"Cloned repository: {repo_name}")
            except Exception as e:
                raise RuntimeError(f"Failed to clone repository: {e}")

        return local_path, repo_name

    def get_repo_info(self, local_path: str) -> dict:
        """Get basic repository information."""
        try:
            repo = git.Repo(local_path)
            return {
                "branch": repo.active_branch.name,
                "last_commit": str(repo.head.commit)[:8],
                "commit_message": repo.head.commit.message.strip()[:100],
                "author": str(repo.head.commit.author),
            }
        except Exception as e:
            return {"error": str(e)}
