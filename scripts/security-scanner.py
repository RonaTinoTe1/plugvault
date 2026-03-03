#!/usr/bin/env python3
"""
Security Scanner for PlugVault
Scans plugins for security issues using pattern matching and VirusTotal.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import vt
    VT_AVAILABLE = True
except ImportError:
    VT_AVAILABLE = False

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
NEW_PLUGINS_FILE = os.path.join(DATA_DIR, "new-plugins.json")
REPORTS_DIR = os.path.join(DATA_DIR, "security-reports")
CATALOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "catalog.json")

# VirusTotal rate limiting
VT_REQUESTS_PER_MINUTE = 4
VT_DELAY = 60 / VT_REQUESTS_PER_MINUTE

# Binary detection
MAX_TEXT_FILE_SIZE = 1 * 1024 * 1024  # 1MB

# File extensions where dangerous function patterns (eval/exec) should be checked
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".sh"}


@dataclass
class SecurityIssue:
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    category: str
    description: str
    file: str
    line: int | None = None
    match: str | None = None


@dataclass
class ScanResult:
    plugin_name: str
    plugin_slug: str
    github_url: str
    scan_date: str
    score: str = "SAFE"  # SAFE, CAUTION, DANGER
    issues: list[SecurityIssue] = field(default_factory=list)
    vt_result: dict = field(default_factory=dict)
    files_scanned: int = 0
    binaries_detected: int = 0


class SecurityScanner:
    # Credential patterns (scanned on ALL file types)
    CREDENTIAL_PATTERNS = [
        (r'(?i)(api[_-]?key|apikey|api[_-]?secret|secret[_-]?key)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "HIGH"),
        (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']{8,})["\']?', "HIGH"),
        (r'(?i)(token|auth[_-]?token|access[_-]?token)\s*[=:]\s*["\']?([a-zA-Z0-9_\-\.]{20,})["\']?', "HIGH"),
        (r'(?i)(sk-[a-zA-Z0-9]{20,})', "CRITICAL"),  # OpenAI keys
        (r'(?i)(xox[baprs]-[a-zA-Z0-9\-]{10,})', "CRITICAL"),  # Slack tokens
        (r'(?i)(ghp_[a-zA-Z0-9]{36})', "CRITICAL"),  # GitHub personal tokens
        (r'(?i)(gho_[a-zA-Z0-9]{36})', "CRITICAL"),  # GitHub OAuth tokens
        (r'(?i)(ghu_[a-zA-Z0-9]{36})', "CRITICAL"),  # GitHub user tokens
        (r'(?i)(ghs_[a-zA-Z0-9]{36})', "CRITICAL"),  # GitHub server tokens
        (r'(?i)(ghr_[a-zA-Z0-9]{36})', "CRITICAL"),  # GitHub refresh tokens
        (r'(?i)(AIza[a-zA-Z0-9_-]{35})', "CRITICAL"),  # Google API keys
        (r'(?i)(AKIA[a-zA-Z0-9]{16})', "CRITICAL"),  # AWS access keys
    ]

    # Dangerous function patterns (scanned only on CODE_EXTENSIONS)
    DANGEROUS_PATTERNS = [
        (r'\beval\s*\(', "MEDIUM"),
        (r'\bexec\s*\(', "MEDIUM"),
        (r'\bsubprocess\.[a-z]+\([^)]*shell\s*=\s*True', "HIGH"),
        (r'\bos\.system\s*\(', "HIGH"),
        (r'\bcompile\s*\([^)]+\)\s*[\s;]*\bexec\s*\(', "CRITICAL"),
        (r'\b__import__\s*\(\s*["\']', "MEDIUM"),
        (r'\bimportlib\.import_module\s*\(\s*["\']', "LOW"),
    ]

    # Suspicious URL patterns (scanned on ALL file types)
    SUSPICIOUS_URLS = [
        (r'https?://[a-z0-9\-]*\.pastebin\.com', "MEDIUM"),
        (r'https?://[a-z0-9\-]*\.ngrok\.io', "MEDIUM"),
        (r'https?://[a-z0-9\-]*\.ngrok-free\.app', "MEDIUM"),
        (r'https?://discord\.com/api/webhooks/', "HIGH"),
        (r'https?://discordapp\.com/api/webhooks/', "HIGH"),
        (r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/]', "HIGH"),
        (r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', "MEDIUM"),
    ]

    def __init__(self, vt_api_key: str | None = None):
        self.vt_api_key = vt_api_key
        self.vt_client = None
        self.last_vt_request = 0

        if vt_api_key and VT_AVAILABLE:
            try:
                self.vt_client = vt.Client(vt_api_key)
            except Exception as e:
                logger.warning("Could not initialize VirusTotal client: %s", e)

    def _slugify(self, name: str) -> str:
        """Convert name to URL-safe slug."""
        slug = re.sub(r'[^a-zA-Z0-9\-]', '-', name.lower())
        slug = re.sub(r'-+', '-', slug)
        return slug.strip('-')

    def _is_binary(self, file_path: Path) -> bool:
        """Check if a file is binary."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(8192)
                if b'\x00' in chunk:
                    return True
                # Check for common binary signatures
                if chunk.startswith(b'\x7fELF') or chunk.startswith(b'MZ'):
                    return True
                if chunk[:4] in [b'\x89PNG', b'GIF8', b'\xff\xd8\xff']:
                    return True
            return False
        except Exception:
            return False

    def _scan_file(self, file_path: Path, content: str | None = None) -> list[SecurityIssue]:
        """Scan a single file for security issues."""
        issues = []

        try:
            if content is None:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
        except Exception:
            return issues

        rel_path = str(file_path)
        ext = file_path.suffix.lower()
        is_code_file = ext in CODE_EXTENSIONS

        # Check credential patterns (all file types)
        for pattern, severity in self.CREDENTIAL_PATTERNS:
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count('\n') + 1
                issues.append(SecurityIssue(
                    severity=severity,
                    category="credential",
                    description="Potential credential/secret exposed",
                    file=rel_path,
                    line=line_num,
                    match=match.group(0)[:50] + "..." if len(match.group(0)) > 50 else match.group(0)
                ))

        # Check dangerous functions (code files only)
        if is_code_file:
            for pattern, severity in self.DANGEROUS_PATTERNS:
                for match in re.finditer(pattern, content, re.MULTILINE):
                    line_num = content[:match.start()].count('\n') + 1
                    issues.append(SecurityIssue(
                        severity=severity,
                        category="dangerous_function",
                        description="Potentially dangerous code pattern",
                        file=rel_path,
                        line=line_num,
                        match=match.group(0)
                    ))

        # Check suspicious URLs (all file types)
        for pattern, severity in self.SUSPICIOUS_URLS:
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count('\n') + 1
                issues.append(SecurityIssue(
                    severity=severity,
                    category="suspicious_url",
                    description="Suspicious URL detected",
                    file=rel_path,
                    line=line_num,
                    match=match.group(0)
                ))

        return issues

    def _vt_rate_limit(self):
        """Enforce VirusTotal rate limiting."""
        elapsed = time.time() - self.last_vt_request
        if elapsed < VT_DELAY:
            time.sleep(VT_DELAY - elapsed)

    def _check_vt_url(self, url: str) -> dict | None:
        """Check URL reputation with VirusTotal."""
        if not self.vt_client:
            return None

        self._vt_rate_limit()
        try:
            analysis = self.vt_client.get_object(f"/urls/{vt.url_id(url)}")
            self.last_vt_request = time.time()

            stats = analysis.last_analysis_stats if hasattr(analysis, 'last_analysis_stats') else {}
            return {
                "url": url,
                "harmless": stats.get("harmless", 0),
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "undetected": stats.get("undetected", 0),
                "reputation": getattr(analysis, 'reputation', 0),
            }
        except Exception as e:
            logger.warning("VT URL check error: %s", e)
            return None

    def _check_vt_file(self, file_path: Path) -> dict | None:
        """Check file with VirusTotal."""
        if not self.vt_client:
            return None

        if file_path.stat().st_size > 32 * 1024 * 1024:  # 32MB limit
            return {"error": "File too large for VT scan"}

        self._vt_rate_limit()
        try:
            with open(file_path, 'rb') as f:
                analysis = self.vt_client.scan_file(f, wait_for_completion=True)
            self.last_vt_request = time.time()

            stats = analysis.stats if hasattr(analysis, 'stats') else {}
            return {
                "file": str(file_path.name),
                "harmless": stats.get("harmless", 0),
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "undetected": stats.get("undetected", 0),
            }
        except Exception as e:
            logger.warning("VT file scan error: %s", e)
            return None

    def scan_repo(self, github_url: str, plugin_name: str) -> ScanResult:
        """Clone and scan a repository."""
        slug = self._slugify(plugin_name)
        result = ScanResult(
            plugin_name=plugin_name,
            plugin_slug=slug,
            github_url=github_url,
            scan_date=datetime.now(timezone.utc).isoformat(),
        )

        # Validate URL before cloning
        if not github_url.startswith("https://github.com/"):
            logger.warning("Skipping invalid GitHub URL: %s", github_url)
            result.issues.append(SecurityIssue(
                severity="MEDIUM",
                category="invalid_url",
                description=f"Invalid GitHub URL, skipping clone: {github_url}",
                file="",
            ))
            result.score = "CAUTION"
            return result

        # Create temp directory for cloning
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "repo"

            logger.info("  Cloning %s...", github_url)
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", github_url, str(repo_path)],
                    capture_output=True,
                    check=True,
                    timeout=120,
                )
            except subprocess.CalledProcessError as e:
                logger.warning("    Clone failed: %s", e.stderr.decode())
                result.issues.append(SecurityIssue(
                    severity="MEDIUM",
                    category="clone_failed",
                    description="Could not clone repository for scanning",
                    file="",
                ))
                result.score = "CAUTION"
                return result
            except subprocess.TimeoutExpired:
                logger.warning("    Clone timeout")
                result.score = "CAUTION"
                return result

            # Scan all files
            logger.info("  Scanning files...")
            binary_files = []

            for file_path in repo_path.rglob('*'):
                if not file_path.is_file():
                    continue

                # Skip symlinks to prevent traversal attacks
                if file_path.is_symlink():
                    continue

                # Skip hidden files and common non-code directories
                rel_path = file_path.relative_to(repo_path)
                if any(part.startswith('.') for part in rel_path.parts):
                    continue
                if any(part in ['node_modules', 'venv', '__pycache__', '.git'] for part in rel_path.parts):
                    continue

                result.files_scanned += 1

                # Check file size
                file_size = file_path.stat().st_size

                if self._is_binary(file_path):
                    result.binaries_detected += 1
                    if file_size > MAX_TEXT_FILE_SIZE:
                        binary_files.append(file_path)
                    continue

                # Skip very large text files
                if file_size > MAX_TEXT_FILE_SIZE:
                    continue

                # Scan the file
                issues = self._scan_file(file_path)
                result.issues.extend(issues)

            # Check VirusTotal for repo URL
            if self.vt_client:
                logger.info("  Checking VirusTotal...")
                result.vt_result["url_check"] = self._check_vt_url(github_url)

                # Scan binary files
                for bin_file in binary_files[:5]:  # Limit to 5 binary files
                    vt_result = self._check_vt_file(bin_file)
                    if vt_result:
                        result.vt_result.setdefault("binary_scans", []).append(vt_result)

        # Calculate final score
        result.score = self._calculate_score(result)

        return result

    def _calculate_score(self, result: ScanResult) -> str:
        """Calculate overall security score."""
        has_critical = any(i.severity == "CRITICAL" for i in result.issues)
        has_high = any(i.severity == "HIGH" for i in result.issues)
        has_medium = any(i.severity == "MEDIUM" for i in result.issues)

        # Check VT results
        vt_malicious = False
        if result.vt_result:
            url_check = result.vt_result.get("url_check", {})
            if url_check.get("malicious", 0) > 0 or url_check.get("suspicious", 0) > 2:
                vt_malicious = True

            for bin_scan in result.vt_result.get("binary_scans", []):
                if bin_scan.get("malicious", 0) > 0:
                    vt_malicious = True

        if has_critical or vt_malicious:
            return "DANGER"
        elif has_high:
            return "CAUTION"
        elif has_medium:
            return "CAUTION"
        return "SAFE"

    def result_to_dict(self, result: ScanResult) -> dict:
        """Convert ScanResult to dictionary."""
        return {
            "plugin": result.plugin_name,
            "plugin_slug": result.plugin_slug,
            "github_url": result.github_url,
            "scan_date": result.scan_date,
            "score": result.score,
            "files_scanned": result.files_scanned,
            "binaries_detected": result.binaries_detected,
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "description": i.description,
                    "file": i.file,
                    "line": i.line,
                    "match": i.match,
                }
                for i in result.issues
            ],
            "vt_result": result.vt_result,
        }

    def close(self):
        """Close VirusTotal client."""
        if self.vt_client:
            self.vt_client.close()


def load_plugins_to_scan() -> list[dict]:
    """Load plugins that need scanning."""
    plugins = []

    # Load from new-plugins.json
    if os.path.exists(NEW_PLUGINS_FILE):
        with open(NEW_PLUGINS_FILE, 'r') as f:
            data = json.load(f)
            plugins.extend(data.get('plugins', []))

    # Also check existing catalog for plugins without security scan
    if os.path.exists(CATALOG_FILE):
        with open(CATALOG_FILE, 'r') as f:
            catalog = json.load(f)
            for plugin in catalog.get('plugins', []):
                # Check if security report exists
                slug = plugin.get('slug', '')
                report_file = os.path.join(REPORTS_DIR, f"{slug}.json")
                if not os.path.exists(report_file) and (plugin.get('github_url') or plugin.get('github')):
                    plugins.append({
                        'name': plugin.get('name', ''),
                        'github_url': plugin.get('github_url') or plugin.get('github', ''),
                    })

    return plugins


def main():
    logger.info("=" * 60)
    logger.info("PlugVault Security Scanner")
    logger.info("=" * 60)

    # Get VirusTotal API key (optional)
    vt_api_key = os.environ.get("VT_API_KEY")
    if not vt_api_key:
        logger.info("VT_API_KEY not set. VirusTotal scanning disabled.")
    elif not VT_AVAILABLE:
        logger.info("vt-py not installed. VirusTotal scanning disabled.")
        vt_api_key = None

    # Ensure reports directory exists
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # Load plugins to scan
    plugins = load_plugins_to_scan()

    if not plugins:
        logger.info("No plugins to scan.")
        sys.exit(0)

    logger.info("Found %d plugins to scan.", len(plugins))

    # Initialize scanner
    scanner = SecurityScanner(vt_api_key)

    scanned = 0
    errors = 0

    try:
        for plugin in plugins:
            name = plugin.get('name', 'Unknown')
            github_url = plugin.get('github_url', plugin.get('github', ''))

            if not github_url:
                logger.warning("Skipping %s: No GitHub URL", name)
                continue

            logger.info("[%d/%d] Scanning: %s", scanned + 1, len(plugins), name)
            logger.info("  URL: %s", github_url)

            try:
                result = scanner.scan_repo(github_url, name)
                result_dict = scanner.result_to_dict(result)

                # Save report
                report_file = os.path.join(REPORTS_DIR, f"{result.plugin_slug}.json")
                with open(report_file, 'w') as f:
                    json.dump(result_dict, f, indent=2)

                logger.info("  Score: %s", result.score)
                logger.info("  Issues: %d", len(result.issues))
                logger.info("  Report: %s", report_file)

                scanned += 1

            except Exception as e:
                logger.error("Error scanning %s: %s", name, e)
                errors += 1

    finally:
        scanner.close()

    logger.info("=" * 60)
    logger.info("Security scan complete!")
    logger.info("  Scanned: %d", scanned)
    logger.info("  Errors: %d", errors)
    logger.info("  Reports: %s", REPORTS_DIR)
    logger.info("=" * 60)

    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
