"""
posted_log/YYYY-MM-DD.json による投稿済み記録の共通ヘルパー。

同じ枠(Threadsの時刻枠、Instagramの1日1回)を二重に投稿してしまうのを防ぐため、
投稿に成功した直後にこのファイルへ記録する。GitHub Actions側のワークフローが
このファイルの変更をリポジトリへcommit/pushすることで、次回以降の実行(delayed
retryや手動キャッチアップなど)が同じ内容を再投稿しないようにする。
"""
import json
import os

LOG_DIR = "posted_log"


def _log_path(date_str: str) -> str:
    return os.path.join(LOG_DIR, f"{date_str}.json")


def load(date_str: str) -> dict:
    path = _log_path(date_str)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def mark_posted(date_str: str, key: str, value: str) -> None:
    """該当キーを投稿済みとして記録し、posted_log/<date>.jsonに保存する。
    git commit/pushはワークフロー側のステップで行う(このファイル自体はローカルに書くだけ)。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    data = load(date_str)
    data[key] = value
    with open(_log_path(date_str), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
