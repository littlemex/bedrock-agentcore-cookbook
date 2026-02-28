#!/usr/bin/env python3
"""
Phase 12: GDPR ユーザー記憶バッチ削除スクリプト

GDPR Right to Erasure（忘れられる権利）に基づき、
特定ユーザー（actor_id）の全記憶レコードをバッチ削除する。

処理フロー:
1. GDPR Processor ロールに AssumeRole
2. RetrieveMemoryRecords で対象ユーザーの記憶を全件取得（ページネーション対応）
3. BatchDeleteMemoryRecords で最大 100 件ずつバッチ削除
4. 削除後に RetrieveMemoryRecords で残存レコードが 0 件であることを検証
5. 削除結果を JSON 監査ログとして出力

使用例:
  python3 gdpr-delete-user-memories.py --actor-id tenant-a:user-001
  python3 gdpr-delete-user-memories.py --actor-id tenant-a:user-001 --dry-run
"""

import boto3
import json
import os
import sys
import argparse
import datetime
from botocore.exceptions import ClientError

# リージョン
REGION = "us-east-1"

# Config ファイル
CONFIG_FILE = "phase12-config.json"

# バッチ削除の最大件数（API 制限）
MAX_BATCH_SIZE = 100

# 監査レポートディレクトリ
AUDIT_REPORT_DIR = "./audit-reports"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run setup-gdpr-processor-role.py first.")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def assume_gdpr_processor_role(config):
    """GDPR Processor ロールに AssumeRole"""
    gdpr_processor = config.get("gdprProcessor", {})
    role_arn = gdpr_processor.get("roleArn")

    if not role_arn:
        print("[ERROR] GDPR Processor role ARN not found in config.")
        print("  Run setup-gdpr-processor-role.py first.")
        sys.exit(1)

    print(f"[INFO] Assuming GDPR Processor role: {role_arn}")

    sts = boto3.client("sts", region_name=REGION)
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="gdpr-erasure-session",
            ExternalId="gdpr-processor",
            DurationSeconds=3600
        )
        credentials = response["Credentials"]
        print(f"[OK] AssumeRole successful")
        print(f"  Session: gdpr-erasure-session")
        print(f"  Expiration: {credentials['Expiration']}")

        return boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=REGION
        )
    except ClientError as e:
        print(f"[ERROR] Failed to assume GDPR Processor role: {e}")
        sys.exit(1)


def retrieve_user_memories(client, memory_id, strategy_id, actor_id):
    """対象ユーザーの全記憶レコードを取得

    RetrieveMemoryRecords API を使用して actor_id に紐づく記憶を検索する。
    """
    print(f"[INFO] Retrieving memories for actor: {actor_id}")

    all_records = []
    next_token = None

    while True:
        kwargs = {
            "memoryId": memory_id,
            "memoryStrategyId": strategy_id,
            "namespace": actor_id.split(":")[0] if ":" in actor_id else actor_id,
            "actorId": actor_id
        }
        if next_token:
            kwargs["nextToken"] = next_token

        try:
            response = client.retrieve_memory_records(**kwargs)
        except ClientError as e:
            print(f"[ERROR] Failed to retrieve memories: {e}")
            break

        records = response.get("memoryRecords", [])
        all_records.extend(records)

        next_token = response.get("nextToken")
        if not next_token:
            break

    print(f"[OK] Retrieved {len(all_records)} memory records")
    return all_records


def batch_delete_memories(client, memory_id, strategy_id, records, dry_run=False):
    """記憶レコードをバッチ削除

    BatchDeleteMemoryRecords API で最大 100 件ずつ削除する。
    """
    if not records:
        print("[INFO] No records to delete")
        return {"deleted": 0, "failed": 0, "batches": []}

    total_records = len(records)
    total_deleted = 0
    total_failed = 0
    batch_results = []

    # MAX_BATCH_SIZE 件ずつバッチ処理
    for batch_start in range(0, total_records, MAX_BATCH_SIZE):
        batch_end = min(batch_start + MAX_BATCH_SIZE, total_records)
        batch = records[batch_start:batch_end]
        batch_num = (batch_start // MAX_BATCH_SIZE) + 1
        total_batches = (total_records + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE

        print(f"\n[BATCH {batch_num}/{total_batches}] "
              f"Deleting records {batch_start + 1}-{batch_end} of {total_records}")

        record_ids = [r.get("memoryRecordId", r.get("id", "")) for r in batch]
        record_ids = [rid for rid in record_ids if rid]

        if not record_ids:
            print(f"  [WARN] No valid record IDs in batch")
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would delete {len(record_ids)} records")
            for rid in record_ids:
                print(f"    - {rid}")
            batch_results.append({
                "batchNumber": batch_num,
                "recordCount": len(record_ids),
                "status": "dry-run",
                "recordIds": record_ids
            })
            total_deleted += len(record_ids)
            continue

        try:
            response = client.batch_delete_memory_records(
                memoryId=memory_id,
                memoryStrategyId=strategy_id,
                memoryRecordIds=record_ids
            )

            # 成功/失敗の集計
            deleted_count = len(record_ids)
            failed_records = response.get("failedRecords", [])
            failed_count = len(failed_records)
            success_count = deleted_count - failed_count

            total_deleted += success_count
            total_failed += failed_count

            batch_result = {
                "batchNumber": batch_num,
                "recordCount": deleted_count,
                "successCount": success_count,
                "failedCount": failed_count,
                "status": "completed",
                "recordIds": record_ids
            }

            if failed_records:
                batch_result["failedRecords"] = failed_records
                print(f"  [WARN] {failed_count} records failed to delete")
                for fr in failed_records:
                    print(f"    - {fr.get('memoryRecordId', 'unknown')}: "
                          f"{fr.get('errorMessage', 'unknown error')}")

            batch_results.append(batch_result)
            print(f"  [OK] Deleted {success_count}/{deleted_count} records")

        except ClientError as e:
            print(f"  [ERROR] Batch delete failed: {e}")
            batch_results.append({
                "batchNumber": batch_num,
                "recordCount": len(record_ids),
                "status": "error",
                "error": str(e),
                "recordIds": record_ids
            })
            total_failed += len(record_ids)

    return {
        "deleted": total_deleted,
        "failed": total_failed,
        "batches": batch_results
    }


def verify_deletion(client, memory_id, strategy_id, actor_id):
    """削除後に残存レコードが 0 件であることを検証

    RetrieveMemoryRecords API でページネーションを行い、
    対象 actor_id のレコードが完全に削除されたことを確認する。
    """
    print(f"[INFO] Verifying deletion completeness for actor: {actor_id}")

    remaining_records = []
    next_token = None

    while True:
        kwargs = {
            "memoryId": memory_id,
            "memoryStrategyId": strategy_id,
            "namespace": actor_id.split(":")[0] if ":" in actor_id else actor_id,
            "actorId": actor_id
        }
        if next_token:
            kwargs["nextToken"] = next_token

        try:
            response = client.retrieve_memory_records(**kwargs)
        except ClientError as e:
            print(f"[ERROR] Verification query failed: {e}")
            return {"verified": False, "error": str(e), "remainingCount": -1}

        records = response.get("memoryRecords", [])
        remaining_records.extend(records)

        next_token = response.get("nextToken")
        if not next_token:
            break

    remaining_count = len(remaining_records)

    if remaining_count == 0:
        print("[OK] Deletion verified: 0 records remaining")
        return {"verified": True, "remainingCount": 0}
    else:
        print(f"[WARNING] Deletion incomplete: {remaining_count} records still remaining")
        remaining_ids = [
            r.get("memoryRecordId", r.get("id", "unknown"))
            for r in remaining_records
        ]
        for rid in remaining_ids[:10]:
            print(f"  - {rid}")
        if remaining_count > 10:
            print(f"  ... and {remaining_count - 10} more")
        return {
            "verified": False,
            "remainingCount": remaining_count,
            "remainingRecordIds": remaining_ids
        }


def save_audit_log(actor_id, records, delete_result, dry_run=False,
                   verification_result=None):
    """削除監査ログを JSON ファイルとして保存"""
    os.makedirs(AUDIT_REPORT_DIR, exist_ok=True)

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_actor_id = actor_id.replace(":", "_").replace("/", "_")
    filename = f"gdpr-deletion-{safe_actor_id}-{timestamp}.json"
    filepath = os.path.join(AUDIT_REPORT_DIR, filename)

    audit_log = {
        "gdprAction": "right-to-erasure",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "actorId": actor_id,
        "dryRun": dry_run,
        "summary": {
            "totalRecordsFound": len(records),
            "totalDeleted": delete_result["deleted"],
            "totalFailed": delete_result["failed"]
        },
        "verification": verification_result if verification_result else {
            "verified": None,
            "remainingCount": None,
            "note": "Verification skipped (dry-run or no records)"
        },
        "batches": delete_result["batches"],
        "records": [
            {
                "memoryRecordId": r.get("memoryRecordId", r.get("id", "")),
                "content": r.get("content", {}).get("text", "")[:50] + "..."
                if r.get("content", {}).get("text", "")
                else "[no content]"
            }
            for r in records
        ]
    }

    with open(filepath, "w") as f:
        json.dump(audit_log, f, indent=2, ensure_ascii=False)

    print(f"[OK] Audit log saved: {os.path.abspath(filepath)}")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Phase 12: GDPR ユーザー記憶バッチ削除"
    )
    parser.add_argument(
        "--actor-id",
        required=True,
        help="削除対象のユーザー ID（例: tenant-a:user-001）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除せずに対象レコードの確認のみ"
    )
    parser.add_argument(
        "--skip-assume-role",
        action="store_true",
        help="AssumeRole をスキップ（現在の認証情報を使用）"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 12: GDPR User Memory Deletion")
    print("=" * 60)

    if args.dry_run:
        print("[INFO] DRY-RUN MODE - No records will be deleted")

    # Config 読み込み
    config = load_config()
    memory_id = config.get("memory", {}).get("memoryId")
    strategy_id = config.get("memory", {}).get("strategyId")

    if not memory_id or not strategy_id:
        print("[ERROR] Memory ID or Strategy ID not found in config.")
        sys.exit(1)

    print(f"[INFO] Memory ID: {memory_id}")
    print(f"[INFO] Strategy ID: {strategy_id}")
    print(f"[INFO] Target Actor: {args.actor_id}")

    # GDPR Processor ロールに AssumeRole
    if args.skip_assume_role:
        print("[INFO] Skipping AssumeRole (using current credentials)")
        session = boto3.Session(region_name=REGION)
    else:
        session = assume_gdpr_processor_role(config)

    # Memory API クライアント作成
    client = session.client("bedrock-agentcore", region_name=REGION)

    # Step 1: 対象ユーザーの記憶を取得
    print(f"\n[STEP 1] Retrieving memories for: {args.actor_id}")
    records = retrieve_user_memories(client, memory_id, strategy_id, args.actor_id)

    if not records:
        print("[INFO] No memory records found for this actor.")
        print("[OK] Nothing to delete. GDPR erasure request fulfilled (no data).")

        # 空の場合でも監査ログを残す
        save_audit_log(args.actor_id, records, {"deleted": 0, "failed": 0, "batches": []}, args.dry_run)
        return

    # 対象レコードの概要を表示
    print(f"\n[INFO] Found {len(records)} memory records:")
    for i, record in enumerate(records[:5]):
        rid = record.get("memoryRecordId", record.get("id", "N/A"))
        content = record.get("content", {}).get("text", "")
        preview = content[:80] + "..." if len(content) > 80 else content
        print(f"  [{i + 1}] {rid}: {preview}")
    if len(records) > 5:
        print(f"  ... and {len(records) - 5} more records")

    # Step 2: バッチ削除実行
    print(f"\n[STEP 2] {'[DRY-RUN] ' if args.dry_run else ''}Deleting memory records...")
    delete_result = batch_delete_memories(
        client, memory_id, strategy_id, records, dry_run=args.dry_run
    )

    # Step 3: 削除後検証
    verification_result = None
    if not args.dry_run and delete_result["deleted"] > 0:
        print(f"\n[STEP 3] Verifying deletion completeness...")
        verification_result = verify_deletion(
            client, memory_id, strategy_id, args.actor_id
        )
    elif args.dry_run:
        print(f"\n[STEP 3] Skipping verification (dry-run mode)")
    else:
        print(f"\n[STEP 3] Skipping verification (no records deleted)")

    # Step 4: 監査ログ保存
    print(f"\n[STEP 4] Saving audit log...")
    audit_filepath = save_audit_log(
        args.actor_id, records, delete_result, args.dry_run,
        verification_result=verification_result
    )

    # 結果サマリー
    print("\n" + "=" * 60)
    if args.dry_run:
        print("[OK] GDPR Erasure Dry-Run Complete")
    else:
        print("[OK] GDPR Erasure Complete")
    print("=" * 60)
    print(f"\n  Actor ID:        {args.actor_id}")
    print(f"  Records found:   {len(records)}")
    print(f"  Records deleted: {delete_result['deleted']}")
    print(f"  Records failed:  {delete_result['failed']}")
    if verification_result:
        verified_status = "PASS" if verification_result["verified"] else "FAIL"
        print(f"  Verification:    {verified_status} "
              f"(remaining: {verification_result['remainingCount']})")
    print(f"  Audit log:       {audit_filepath}")

    if delete_result["failed"] > 0:
        print(f"\n[WARNING] {delete_result['failed']} records failed to delete.")
        print("  Review the audit log and retry if necessary.")
        sys.exit(1)

    if verification_result and not verification_result["verified"]:
        print(f"\n[WARNING] Deletion verification failed: "
              f"{verification_result['remainingCount']} records still remaining.")
        print("  Retry the deletion or investigate the remaining records.")
        sys.exit(1)

    print(f"\nNext steps:")
    print(f"  1. Run: python3 gdpr-generate-deletion-certificate.py "
          f"--audit-log {audit_filepath}")
    print(f"  2. Run: python3 gdpr-audit-report.py")
    print(f"  3. Verify CloudTrail logs for deletion events")


if __name__ == "__main__":
    main()
