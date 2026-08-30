#!/usr/bin/env python3
"""
GitHub Actions上で実行される、Threads指定時刻枠の自動投稿スクリプト。
リポジトリ内の threads_posts/YYYY-MM-DD.md (ローカルPCのtarot-threadsタスクが
毎朝pushしてくる想定)を読み取り、該当時刻枠のテキストをThreads APIで投稿する。

環境変数:
    THREADS_ACCESS_TOKEN, THREADS_USER_ID (=me でも可)

実行例:
    python scripts/post_threads_slot.py --time 09:00   # 指定枠のみ(手動実行向け)
    python scripts/post_threads_slot.py                # 巡回モード(スケジュール実行向け、2026-08-30後半確定)

巡回モード:
    GitHub Actionsのscheduleイベントは高負荷時にtickそのものが間引かれることがあり、
    枠ごとの単発cronだけでは「その回が丸ごと欠落」する事故が起きうる(2026-08-30、18:00枠・
    21:00枠が2回とも一度もトリガーされず欠落した実例あり)。そのため、--time省略時は
    「現在時刻までに到達している、まだposted_logに無い枠」を全部拾って古い順に投稿する。
    ワークフロー側を15分おき程度の巡回cronにしておけば、あるtickが間引かれても
    次の巡回が拾ってリトライしてくれる。
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

from posted_log import load as load_posted_log, mark_posted

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
    if not create_resp.ok:
        print(f"作成リクエスト失敗: {create_resp.status_code} {create_resp.text}", file=sys.stderr)
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]

    time.sleep(3)

    publish_resp = requests.post(
        f"{THREADS_API_BASE}/{user_id}/threads_publish",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    if not publish_resp.ok:
        print(f"公開リクエスト失敗: {publish_resp.status_code} {publish_resp.text}", file=sys.stderr)
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]


def find_time_slots(text: str) -> list[str]:
    """本文中の '## HH:MM — 見出し' 形式の時刻枠見出しを、出現順(=時系列順)で返す。"""
    return re.findall(r"^## (\d{2}:\d{2}) — .+$", text, re.MULTILINE)


def post_one_slot(md_text: str, today_jst: str, slot_time: str, access_token: str, user_id: str) -> None:
    body = extract_code_block_after_heading(md_text, rf"## {re.escape(slot_time)} — .+")
    post_id = post_text(body, access_token, user_id)
    print(f"Threads投稿完了({slot_time}枠): post_id={post_id}")
    mark_posted(today_jst, slot_time, post_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time", required=False, default=None, help="投稿枠(例: 09:00)。省略時は巡回モード")
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

    log = load_posted_log(today_jst)

    if args.time is not None:
        # 手動実行(workflow_dispatch)向け: 指定された枠のみ処理
        if args.time in log:
            print(f"{args.time}枠は投稿済みのためスキップします(post_id={log[args.time]})")
            sys.exit(0)
        try:
            post_one_slot(text, today_jst, args.time, access_token, user_id)
        except ValueError as e:
            print(f"該当時刻枠の投稿文が見つかりません: {e}")
            sys.exit(0)
        return

    # 巡回モード(スケジュール実行向け): 現在時刻までに到達していて、まだ
    # posted_logに無い枠を、古い順に全部拾って投稿する。
    now_hm = datetime.now(JST).strftime("%H:%M")
    due_slots = [t for t in find_time_slots(text) if t <= now_hm]
    pending_slots = [t for t in due_slots if t not in log]

    if not pending_slots:
        print(f"現在時刻({now_hm})までの枠は全て投稿済み、または該当枠なしです。何もしません。")
        return

    for slot_time in pending_slots:
        try:
            post_one_slot(text, today_jst, slot_time, access_token, user_id)
        except ValueError as e:
            print(f"{slot_time}枠: 投稿文が見つからずスキップします: {e}")
            continue
        # 連続投稿でのレート制限回避のため、次の枠との間に少し間隔を空ける
        if slot_time != pending_slots[-1]:
            time.sleep(10)


if __name__ == "__main__":
    main()
