"""番茄 TOP50 榜单抓取 CLI 脚本。

抓取 novelcatch.com 公开榜单 API，聚合 4 榜 TOP50，构建特征向量并落盘。

用法：
    cd /workspace/TameInk/backend
    .venv/bin/python scripts/fetch_fanqie_bestseller.py \
        [--out-dir ../skills/webnovel-studio/references/fanqie-examples]

落盘文件（写入 --out-dir，默认 ../skills/webnovel-studio/references/fanqie-examples）：
- fanqie_bestseller_snapshot_{YYYYMMDD}.json  原始 TOP50 entries
- fanqie_feature_vector.json                  聚合特征向量
- fanqie_feature_vector_latest.json           最新特征向量（覆盖）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.infrastructure.fanqie_bestseller_fetcher import FanqieBestsellerFetcher


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取番茄 TOP50 榜单并构建特征向量")
    parser.add_argument(
        "--out-dir",
        default=str(BACKEND_DIR.parent / "skills" / "webnovel-studio" / "references" / "fanqie-examples"),
        help="输出目录",
    )
    parser.add_argument("--base-url", default="https://novelcatch.com")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] out_dir={out_dir}")

    fetcher = FanqieBestsellerFetcher(base_url=args.base_url, timeout=args.timeout)
    print("[fetch] 抓取 4 个榜单 TOP50...")
    try:
        snapshots = fetcher.fetch_top50_all_lists()
    except RuntimeError as error:
        print(f"[fetch] FAILED: {error}")
        return 1

    total_entries = sum(len(s.entries) for s in snapshots)
    print(f"[fetch] 抓取完成：{len(snapshots)} 个榜单，共 {total_entries} 条（去重前）")
    for snapshot in snapshots:
        print(
            f"  - {snapshot.list_name}/{snapshot.gender}: "
            f"{snapshot.total} 条, scan_date={snapshot.scan_date}"
        )

    # 构建特征向量
    vector = fetcher.build_feature_vector(snapshots)
    print(f"[vector] 去重后 {vector.total_books} 本")
    print(f"[vector] scan_date={vector.scan_date}")
    print(f"[vector] top_genres={vector.top_genres}")
    print(f"[vector] dominant_hook_type={vector.dominant_hook_type}")
    print(f"[vector] word_count_stats={vector.word_count_stats.model_dump()}")
    print(f"[vector] hook_type_distribution={vector.hook_type_distribution}")

    # 落盘
    today = datetime.now().strftime("%Y%m%d")
    snapshot_path = out_dir / f"fanqie_bestseller_snapshot_{today}.json"
    vector_path = out_dir / "fanqie_feature_vector.json"
    latest_path = out_dir / "fanqie_feature_vector_latest.json"

    snapshot_payload = {
        "fetched_at": datetime.now().isoformat(),
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
    }
    snapshot_path.write_text(
        json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    vector_json = vector.model_dump(mode="json")
    vector_path.write_text(
        json.dumps(vector_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_path.write_text(
        json.dumps(vector_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[fetch] 落盘完成：")
    print(f"  - {snapshot_path}")
    print(f"  - {vector_path}")
    print(f"  - {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
