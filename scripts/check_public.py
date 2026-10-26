"""Fail if tracked repository files contain likely credentials or local runtime data."""

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [ROOT / part.decode("utf-8") for part in result.stdout.split(b"\0") if part]


def check_paths(paths: list[Path]) -> list[tuple[str, str]]:
    problems = []
    private_key_marker = re.compile(b"-----BEGIN " + b"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
    credential_patterns = [private_key_marker,
                           re.compile(b"gh[pousr]_" + b"[A-Za-z0-9]{20,}"),
                           re.compile(b"github_pat_" + b"[A-Za-z0-9_]{20,}"),
                           re.compile(b"sk-" + b"[A-Za-z0-9_-]{20,}"),
                           re.compile(b"AKIA" + b"[A-Z0-9]{16}"),
                           re.compile(b"https?://[^\\s/:@]+:[^\\s/@]+@")]
    local_path = re.compile(b"/Users/" + b"[^/\\s]+/" )
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        name = path.name.lower()
        parts = set(path.relative_to(ROOT).parts)
        if (name in {".env", "id_rsa", "id_ed25519"} or name.startswith(".env.") and name != ".env.example"
                or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log", ".key", ".pem", ".p12"}
                or parts & {"local-data", "secrets", ".venv"}):
            problems.append((relative, "local secret or runtime-data path"))
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in credential_patterns):
            problems.append((relative, "possible credential material"))
        elif local_path.search(data):
            problems.append((relative, "local absolute home path"))
    return problems


def main():
    problems = check_paths(tracked_files())
    if problems:
        for path, reason in problems:
            print(f"FAIL {path}: {reason}")
        raise SystemExit(1)
    print("Public-file check passed: no tracked credentials or local runtime data detected")


if __name__ == "__main__":
    main()
