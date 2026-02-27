#!/usr/bin/env python3
"""
Phase 12: GDPR 削除監査レポート生成

gdpr-delete-user-memories.py が出力した監査ログ（JSON）を集約し、
GDPR コンプライアンス向けの削除監査レポートを生成する。

機能:
- audit-reports/ 内の全削除ログを集約
- 削除サマリー（actor 別、日付別）の生成
- CloudTrail ログとの照合確認
- Markdown 形式の監査レポート出力

使用例:
  python3 gdpr-audit-report.py
  python3 gdpr-audit-report.py --output report.md
  python3 gdpr-audit-report.py --actor-id tenant-a:user-001
"""

import boto3
import json
import os
import sys
import argparse
import datetime
import glob
from botocore.exceptions import ClientError

# リージョン
REGION = "us-east-1"

# Config ファイル
CONFIG_FILE = "phase12-config.json"

# 監査レポートディレクトリ
AUDIT_REPORT_DIR = "./audit-reports"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[WARN] Config file not found: {CONFIG_FILE}")
        return {}

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def load_audit_logs(actor_id=None):
    """監査ログファイルを読み込み"""
    if not os.path.exists(AUDIT_REPORT_DIR):
        print(f"[WARN] Audit report directory not found: {AUDIT_REPORT_DIR}")
        return []

    pattern = os.path.join(AUDIT_REPORT_DIR, "gdpr-deletion-*.json")
    log_files = sorted(glob.glob(pattern))

    if not log_files:
        print("[INFO] No audit log files found")
        return []

    logs = []
    for filepath in log_files:
        try:
            with open(filepath, "r") as f:
                log = json.load(f)

            # actor_id フィルタ
            if actor_id and log.get("actorId") != actor_id:
                continue

            log["_filepath"] = filepath
            logs.append(log)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARN] Failed to load {filepath}: {e}")

    print(f"[OK] Loaded {len(logs)} audit log(s)")
    return logs


def lookup_cloudtrail_events(actor_id, start_time=None):
    """CloudTrail から BatchDeleteMemoryRecords イベントを検索"""
    try:
        ct_client = boto3.client("cloudtrail", region_name=REGION)

        if not start_time:
            start_time = datetime.datetime.utcnow() - datetime.timedelta(days=7)

        kwargs = {
            "LookupAttributes": [
                {
                    "AttributeKey": "EventName",
                    "AttributeValue": "BatchDeleteMemoryRecords"
                }
            ],
            "StartTime": start_time,
            "EndTime": datetime.datetime.utcnow()
        }

        events = []
        while True:
            response = ct_client.lookup_events(**kwargs)
            for event in response.get("Events", []):
                event_data = json.loads(event.get("CloudTrailEvent", "{}"))
                request_params = event_data.get("requestParameters", {})
                # actor_id に関連するイベントのみ
                if actor_id in json.dumps(request_params):
                    events.append({
                        "eventTime": event["EventTime"].isoformat()
                        if hasattr(event["EventTime"], "isoformat")
                        else str(event["EventTime"]),
                        "eventName": event["EventName"],
                        "userName": event.get("Username", "N/A"),
                        "sourceIP": event_data.get("sourceIPAddress", "N/A"),
                        "userAgent": event_data.get("userAgent", "N/A"),
                        "requestParameters": request_params
                    })

            next_token = response.get("NextToken")
            if not next_token:
                break
            kwargs["NextToken"] = next_token

        return events

    except ClientError as e:
        print(f"[WARN] CloudTrail lookup failed: {e}")
        return []


def generate_report(logs, cloudtrail_events, config):
    """Markdown 形式の監査レポートを生成"""
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = []
    lines.append("# GDPR Memory Deletion Audit Report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")

    # 設定情報
    lines.append("## Configuration")
    lines.append("")
    memory_id = config.get("memory", {}).get("memoryId", "N/A")
    memory_arn = config.get("memory", {}).get("memoryArn", "N/A")
    gdpr_role = config.get("gdprProcessor", {}).get("roleArn", "N/A")
    lines.append(f"- Memory ID: `{memory_id}`")
    lines.append(f"- Memory ARN: `{memory_arn}`")
    lines.append(f"- GDPR Processor Role: `{gdpr_role}`")
    lines.append(f"- Region: `{config.get('region', REGION)}`")
    lines.append("")

    # サマリー
    lines.append("## Deletion Summary")
    lines.append("")

    if not logs:
        lines.append("No deletion logs found.")
        lines.append("")
    else:
        # 全体統計
        total_found = sum(log.get("summary", {}).get("totalRecordsFound", 0) for log in logs)
        total_deleted = sum(log.get("summary", {}).get("totalDeleted", 0) for log in logs)
        total_failed = sum(log.get("summary", {}).get("totalFailed", 0) for log in logs)
        dry_run_count = sum(1 for log in logs if log.get("dryRun", False))

        lines.append(f"- Total erasure requests: {len(logs)}")
        lines.append(f"- Total records found: {total_found}")
        lines.append(f"- Total records deleted: {total_deleted}")
        lines.append(f"- Total records failed: {total_failed}")
        lines.append(f"- Dry-run requests: {dry_run_count}")
        lines.append("")

        # Actor 別サマリー
        actor_summary = {}
        for log in logs:
            actor = log.get("actorId", "unknown")
            if actor not in actor_summary:
                actor_summary[actor] = {
                    "requests": 0,
                    "found": 0,
                    "deleted": 0,
                    "failed": 0,
                    "lastTimestamp": ""
                }
            actor_summary[actor]["requests"] += 1
            actor_summary[actor]["found"] += log.get("summary", {}).get("totalRecordsFound", 0)
            actor_summary[actor]["deleted"] += log.get("summary", {}).get("totalDeleted", 0)
            actor_summary[actor]["failed"] += log.get("summary", {}).get("totalFailed", 0)
            ts = log.get("timestamp", "")
            if ts > actor_summary[actor]["lastTimestamp"]:
                actor_summary[actor]["lastTimestamp"] = ts

        lines.append("### Per-Actor Summary")
        lines.append("")
        lines.append("| Actor ID | Requests | Found | Deleted | Failed | Last Request |")
        lines.append("|----------|----------|-------|---------|--------|-------------|")
        for actor, stats in sorted(actor_summary.items()):
            lines.append(
                f"| `{actor}` | {stats['requests']} | {stats['found']} | "
                f"{stats['deleted']} | {stats['failed']} | {stats['lastTimestamp'][:19]} |"
            )
        lines.append("")

    # 個別リクエスト詳細
    lines.append("## Deletion Request Details")
    lines.append("")

    for i, log in enumerate(logs):
        lines.append(f"### Request {i + 1}: {log.get('actorId', 'unknown')}")
        lines.append("")
        lines.append(f"- Timestamp: `{log.get('timestamp', 'N/A')}`")
        lines.append(f"- Actor ID: `{log.get('actorId', 'N/A')}`")
        lines.append(f"- Dry Run: {'Yes' if log.get('dryRun') else 'No'}")
        lines.append(f"- Records Found: {log.get('summary', {}).get('totalRecordsFound', 0)}")
        lines.append(f"- Records Deleted: {log.get('summary', {}).get('totalDeleted', 0)}")
        lines.append(f"- Records Failed: {log.get('summary', {}).get('totalFailed', 0)}")
        lines.append(f"- Audit Log File: `{log.get('_filepath', 'N/A')}`")
        lines.append("")

        # バッチ詳細
        batches = log.get("batches", [])
        if batches:
            lines.append("Batch details:")
            lines.append("")
            for batch in batches:
                status = batch.get("status", "unknown")
                lines.append(
                    f"- Batch {batch.get('batchNumber', '?')}: "
                    f"{batch.get('recordCount', 0)} records, status={status}"
                )
            lines.append("")

    # CloudTrail 検証
    lines.append("## CloudTrail Verification")
    lines.append("")

    if cloudtrail_events:
        lines.append(f"Found {len(cloudtrail_events)} related CloudTrail events:")
        lines.append("")
        lines.append("| Time | Event | User | Source IP |")
        lines.append("|------|-------|------|-----------|")
        for event in cloudtrail_events:
            lines.append(
                f"| {event['eventTime'][:19]} | {event['eventName']} | "
                f"{event['userName']} | {event['sourceIP']} |"
            )
        lines.append("")
    else:
        lines.append("No CloudTrail events found for the specified period.")
        lines.append("")
        lines.append("Possible reasons:")
        lines.append("- CloudTrail is not enabled for this region")
        lines.append("- Events have not yet been delivered (delay up to 15 minutes)")
        lines.append("- No actual deletion was performed (dry-run only)")
        lines.append("")

    # コンプライアンスチェックリスト
    lines.append("## GDPR Compliance Checklist")
    lines.append("")
    lines.append("- [ ] Data subject's erasure request received and documented")
    lines.append("- [ ] Identity of data subject verified")
    lines.append("- [ ] All memory records for the data subject identified")
    lines.append("- [ ] Deletion executed using GDPR Processor role (least privilege)")
    lines.append("- [ ] Deletion confirmed via audit log")
    lines.append("- [ ] CloudTrail events verified")
    lines.append("- [ ] Data subject notified of completion")
    lines.append("- [ ] Erasure completed within 30-day GDPR deadline")
    lines.append("")

    # 注記
    lines.append("## Notes")
    lines.append("")
    lines.append("- This report covers Memory API records only.")
    lines.append("  Additional data stores (S3, DynamoDB, etc.) may also contain personal data.")
    lines.append("- CloudTrail events may take up to 15 minutes to appear.")
    lines.append("- Retain this audit report for compliance documentation (recommended: 3 years).")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Phase 12: GDPR 削除監査レポート生成"
    )
    parser.add_argument(
        "--actor-id",
        help="特定のユーザーに限定してレポート生成"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="レポート出力先ファイル（デフォルト: audit-reports/gdpr-audit-report-<timestamp>.md）"
    )
    parser.add_argument(
        "--skip-cloudtrail",
        action="store_true",
        help="CloudTrail ログの検索をスキップ"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 12: GDPR Deletion Audit Report")
    print("=" * 60)

    # Config 読み込み
    config = load_config()

    # 監査ログ読み込み
    print("\n[STEP 1] Loading audit logs...")
    logs = load_audit_logs(actor_id=args.actor_id)

    # CloudTrail イベント検索
    cloudtrail_events = []
    if not args.skip_cloudtrail:
        print("\n[STEP 2] Looking up CloudTrail events...")
        if args.actor_id:
            cloudtrail_events = lookup_cloudtrail_events(args.actor_id)
        else:
            # 全 actor について検索
            actors = set(log.get("actorId", "") for log in logs if log.get("actorId"))
            for actor in actors:
                events = lookup_cloudtrail_events(actor)
                cloudtrail_events.extend(events)
        print(f"[OK] Found {len(cloudtrail_events)} CloudTrail events")
    else:
        print("\n[STEP 2] Skipping CloudTrail lookup")

    # レポート生成
    print("\n[STEP 3] Generating audit report...")
    report = generate_report(logs, cloudtrail_events, config)

    # レポート出力
    os.makedirs(AUDIT_REPORT_DIR, exist_ok=True)

    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        output_path = os.path.join(
            AUDIT_REPORT_DIR, f"gdpr-audit-report-{timestamp}.md"
        )

    with open(output_path, "w") as f:
        f.write(report)

    print(f"[OK] Audit report saved: {os.path.abspath(output_path)}")

    # レポートのサマリーを表示
    print("\n" + "=" * 60)
    print("[OK] Audit Report Generation Complete")
    print("=" * 60)
    print(f"\n  Report: {output_path}")
    print(f"  Logs processed: {len(logs)}")
    print(f"  CloudTrail events: {len(cloudtrail_events)}")

    if args.actor_id:
        print(f"  Filtered by actor: {args.actor_id}")


if __name__ == "__main__":
    main()
