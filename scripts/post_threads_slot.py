#!/usr/bin/env python3
"""
GitHub Actions上で実行される、Threads指定時刻枠の自動投稿スクリプト。
リポジトリ内の threads_posts/YYYY-MM-DD.md (ローカルPCのtarot-threadsタスクが
毎朝pushしてくる想定)を読み取り、該当時刻枠のテキストをThreads APIで投稿する。

環境変数:
    THREADS_ACCESS_TOKEN, THREADS_USER_ID (=me でも可)

実行例:
    python scripts/post_threads_slot.py --time 09:00
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

THREADS_API_BASE = "https://graph.threads.net/v1.0"
JST = timezone(timedelta(hours=9))


def extract_code_block_after_heading(text: str, heading_pattern: str) -> str:
    heading_match = re.search(heading_pattern, text)
    if not heading_match:
        raise ValueError(f"見出しが見つかりません: {heading_pattern}")
    rest = text[heading_match.end():]
    code_match = re.search(r"```\n(.*?)```", rest, re.DOTALL)
    if not code_match:
        raise ValueError(f"見出しの後にコードブロックが見つかりません: {heading_pattern}")
    return code_match.group(1).strip()


def post_text(text: str, access_token: str, user_id: str) -> str:
    params = {"text": text, "media_type": "TEXT", "access_token": access_token}
    create_resp = requests.post(f"{THREADS_API_BASE}/{user_id}/threads", params=params)
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]

    time.sleep(3)

    publish_resp = requests.post(
        f"{THREADS_API_BASE}/{user_id}/threads_publish",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time", required=True, help="投稿枠(例: 09:00)")
    args = parser.parse_args()

    access_token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID", "me")
    if not access_token:
        print("THREADS_ACCESS_TOKENが設定されていません", file=sys.stderr)
        sys.exit(1)

    today_jst = datetime.now(JST).strftime("%Y-%m-%d")
    md_path = os.path.join("threads_posts", f"{today_jst}.md")

    if not os.path.exists(md_path):
        print(f"投稿予定ファイルが見つかりません(まだ生成されていない可能性): {md_path}")
        sys.exit(0)  # エラー扱いにせず正常終了(その日はまだローカルで生成されていない)

    with open(md_path, encoding="utf-8") as f:
        text = f.read()

    try:
        body = extract_code_block_after_heading(text, rf"## {re.escape(args.time)} — .+")
    except ValueError as e:
        print(f"該当時刻枠の投稿文が見つかりません: {e}")
        sys.exit(0)

    post_id = post_text(body, access_token, user_id)
    print(f"Threads投稿完了({args.time}枠): post_id={post_id}")


if __name__ == "__main__":
    main()
