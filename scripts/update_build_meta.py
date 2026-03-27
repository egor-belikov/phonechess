#!/usr/bin/env python3
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "frontend" / "index.html"
BUILD_META = ROOT / "frontend" / "build-meta.json"


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def main() -> None:
    version = run(["git", "rev-parse", "--short", "HEAD"])
    deployed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    asset_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    BUILD_META.write_text(
        json.dumps(
            {"version": version, "deployed_at": deployed_at},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    html = INDEX_HTML.read_text(encoding="utf-8")
    html = re.sub(
        r'href="styles/main\.css\?v=[^"]+"',
        f'href="styles/main.css?v={asset_tag}"',
        html,
    )
    html = re.sub(
        r'src="app\.js\?v=[^"]+"',
        f'src="app.js?v={asset_tag}"',
        html,
    )
    html = re.sub(
        r'(<div id="build-info" class="build-info">)[^<]*(</div>)',
        r"\1"
        + f"Версия: {version} · Деплой: {deployed_at}"
        + r"\2",
        html,
    )
    INDEX_HTML.write_text(html, encoding="utf-8")

    print(f"version={version}")
    print(f"deployed_at={deployed_at}")
    print(f"asset_tag={asset_tag}")


if __name__ == "__main__":
    main()
