#!/usr/bin/env python3
"""
GitHub Actions上で実行される、「今日のカード」Instagram自動投稿スクリプト。
リポジトリ内の today_card/YYYY-MM-DD.png と threads_posts/YYYY-MM-DD.md
(ローカルPCのtarot-threadsタスクが前夜にpushしてくる想定)を読み取り、
Instagram Graph APIで実際に投稿する。

環境変数:
    IG_ACCESS_TOKEN, IG_BUSINESS_ACCOUNT_ID

実行例:
    python scripts/post_instagram_today.py
"""
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

from posted_log import load as load_posted_log, mark_posted

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
JST = timezone(timedelta(hours=9))
GITHUB_USER = "mithuru4790-beep"
REPO_NAME = "suiko-tarot-images"
BRANCH = "master"


def extract_code_block_after_heading(text: str, heading_pattern: str) -> str:
    heading_match = re.search(heading_pattern, text)
    if not heading_match:
        raise ValueError(f"見出しが見つかりません: {heading_pattern}")
    rest = text[heading_match.end():]
    code_match = re.search(r"```\n(.*?)```", rest, re.DOTALL)
    if not code_match:
        raise ValueError(f"見出しの後にコードブロックが見つかりません: {heading_pattern}")
    return code_match.group(1).strip()


def post_image(image_url: str, caption: str, access_token: str, ig_id: str) -> str:
    create_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_id}/media",
        params={"image_url": image_url, "caption": caption, "access_token": access_token},
    )
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]

    for _ in range(10):
        status_resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
        )
        if status_resp.json().get("status_code") == "FINISHED":
            break
        time.sleep(2)

    publish_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_id}/media_publish",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]


def main():
    access_token = os.environ.get("IG_ACCESS_TOKEN")
    ig_id = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    if not access_token or not ig_id:
        print("IG_ACCESS_TOKENまたはIG_BUSINESS_ACCOUNT_IDが設定されていません", file=sys.stderr)
        sys.exit(1)

    today_jst = datetime.now(JST).strftime("%Y-%m-%d")
    image_path = os.path.join("today_card", f"{today_jst}.png")
    md_path = os.path.join("threads_posts", f"{today_jst}.md")

    if not os.path.exists(image_path) or not os.path.exists(md_path):
        print(f"今日分のファイルがまだありません(image={image_path}, md={md_path})")
        sys.exit(0)  # エラー扱いにせず正常終了

    # 二重投稿防止: 大幅な遅延実行や手動キャッチアップで同じ日に2回走っても
    # 再投稿しないよう、先にposted_logを確認する
    log = load_posted_log(today_jst)
    if "instagram" in log:
        print(f"本日分は投稿済みのためスキップします(media_id={log['instagram']})")
        sys.exit(0)

    with open(md_path, encoding="utf-8") as f:
        text = f.read()

    try:
        caption = extract_code_block_after_heading(text, r"## Instagram用キャプション.*")
    except ValueError as e:
        print(f"Instagramキャプションが見つかりません: {e}")
        sys.exit(0)

    image_url = (
        f"https://raw.githubusercontent.com/{GITHUB_USER}/{REPO_NAME}/{BRANCH}/{image_path}"
    )

    media_id = post_image(image_url, caption, access_token, ig_id)
    print(f"Instagram投稿完了: media_id={media_id}")
    mark_posted(today_jst, "instagram", media_id)


if __name__ == "__main__":
    main()
