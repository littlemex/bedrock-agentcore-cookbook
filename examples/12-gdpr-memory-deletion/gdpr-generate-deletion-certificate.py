#!/usr/bin/env python3
"""
Phase 12: GDPR 削除証明書生成

GDPR Right to Erasure（忘れられる権利）に基づく削除操作の完了証明書を
JSON 形式で生成する。

削除証明書には以下の情報が含まれる:
- 削除操作の日時
- 対象 actor_id
- 削除されたレコード件数
- 削除後の検証結果
- 監査ログファイルへの参照

使用例:
  python3 gdpr-generate-deletion-certificate.py --audit-log audit-reports/gdpr-deletion-tenant_a_user-001-20260227T120000Z.json
  python3 gdpr-generate-deletion-certificate.py --actor-id tenant-a:user-001
"""

import json
import os
import sys
import argparse
import datetime
import hashlib
import glob

# 監査レポートディレクトリ
AUDIT_REPORT_DIR = "./audit-reports"

# 証明書ディレクトリ
CERTIFICATE_DIR = "./audit-reports/certificates"


def load_audit_log(filepath):
    """監査ログファイルを読み込み"""
    if not os.path.exists(filepath):
        print(f"[ERROR] Audit log not found: {filepath}")
        sys.exit(1)

    with open(filepath, "r") as f:
        return json.load(f)


def find_latest_audit_log(actor_id):
    """指定 actor_id の最新監査ログを検索"""
    safe_actor_id = actor_id.replace(":", "_").replace("/", "_")
    pattern = os.path.join(AUDIT_REPORT_DIR, f"gdpr-deletion-{safe_actor_id}-*.json")
    log_files = sorted(glob.glob(pattern))

    if not log_files:
        print(f"[ERROR] No audit logs found for actor: {actor_id}")
        print(f"  Pattern: {pattern}")
        sys.exit(1)

    latest = log_files[-1]
    print(f"[INFO] Using latest audit log: {latest}")
    return latest


def compute_audit_log_hash(filepath):
    """監査ログファイルの SHA-256 ハッシュを計算"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_certificate(audit_log, audit_log_path):
    """削除証明書を生成"""
    summary = audit_log.get("summary", {})
    verification = audit_log.get("verification", {})

    # 削除が成功しているか判定
    total_found = summary.get("totalRecordsFound", 0)
    total_deleted = summary.get("totalDeleted", 0)
    total_failed = summary.get("totalFailed", 0)
    is_dry_run = audit_log.get("dryRun", False)

    if is_dry_run:
        status = "dry-run"
        status_description = "Dry-run mode: no records were actually deleted"
    elif total_failed > 0:
        status = "partial"
        status_description = (
            f"Partial deletion: {total_deleted} deleted, "
            f"{total_failed} failed out of {total_found} records"
        )
    elif verification.get("verified") is True:
        status = "complete"
        status_description = (
            f"Complete erasure verified: all {total_deleted} records "
            f"deleted and verified"
        )
    elif verification.get("verified") is False:
        status = "unverified"
        remaining = verification.get("remainingCount", "unknown")
        status_description = (
            f"Deletion executed but verification failed: "
            f"{remaining} records still remaining"
        )
    else:
        status = "complete-unverified"
        status_description = (
            f"Deletion executed: {total_deleted} records deleted "
            f"(post-deletion verification not performed)"
        )

    # 監査ログのハッシュ
    audit_log_hash = compute_audit_log_hash(audit_log_path)

    certificate = {
        "certificateType": "gdpr-erasure-completion",
        "certificateVersion": "1.0",
        "generatedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "erasureRequest": {
            "actorId": audit_log.get("actorId", "unknown"),
            "gdprAction": audit_log.get("gdprAction", "right-to-erasure"),
            "executedAt": audit_log.get("timestamp", "unknown"),
            "dryRun": is_dry_run
        },
        "erasureResult": {
            "status": status,
            "statusDescription": status_description,
            "totalRecordsFound": total_found,
            "totalRecordsDeleted": total_deleted,
            "totalRecordsFailed": total_failed,
            "batchCount": len(audit_log.get("batches", []))
        },
        "verification": {
            "postDeletionCheck": verification.get("verified"),
            "remainingRecords": verification.get("remainingCount"),
            "note": verification.get("note") if verification.get("note") else None
        },
        "auditTrail": {
            "auditLogFile": os.path.abspath(audit_log_path),
            "auditLogSha256": audit_log_hash,
            "cloudTrailNote": (
                "Verify BatchDeleteMemoryRecords events in AWS CloudTrail "
                "for independent confirmation"
            )
        },
        "compliance": {
            "regulation": "GDPR Article 17 - Right to erasure",
            "dataCategory": "AgentCore Memory records (semantic memory)",
            "retentionAdvice": (
                "Retain this certificate for a minimum of 3 years "
                "for compliance documentation"
            ),
            "additionalDataStores": (
                "This certificate covers Memory API records only. "
                "Verify deletion in other data stores (S3, DynamoDB, etc.) "
                "and Reflection data (Level 2) in vector stores separately."
            )
        }
    }

    # None 値を除去
    if certificate["verification"]["note"] is None:
        del certificate["verification"]["note"]

    return certificate


def save_certificate(certificate, actor_id):
    """削除証明書を JSON ファイルとして保存"""
    os.makedirs(CERTIFICATE_DIR, exist_ok=True)

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_actor_id = actor_id.replace(":", "_").replace("/", "_")
    filename = f"gdpr-certificate-{safe_actor_id}-{timestamp}.json"
    filepath = os.path.join(CERTIFICATE_DIR, filename)

    with open(filepath, "w") as f:
        json.dump(certificate, f, indent=2, ensure_ascii=False)

    print(f"[OK] Deletion certificate saved: {os.path.abspath(filepath)}")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Phase 12: GDPR 削除証明書生成"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--audit-log",
        help="監査ログファイルのパス"
    )
    group.add_argument(
        "--actor-id",
        help="対象ユーザー ID（最新の監査ログを自動検索）"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 12: GDPR Deletion Certificate Generator")
    print("=" * 60)

    # 監査ログの特定
    if args.audit_log:
        audit_log_path = args.audit_log
    else:
        audit_log_path = find_latest_audit_log(args.actor_id)

    # 監査ログ読み込み
    print(f"\n[STEP 1] Loading audit log: {audit_log_path}")
    audit_log = load_audit_log(audit_log_path)
    actor_id = audit_log.get("actorId", "unknown")
    print(f"[OK] Audit log loaded for actor: {actor_id}")

    # 証明書生成
    print(f"\n[STEP 2] Generating deletion certificate...")
    certificate = generate_certificate(audit_log, audit_log_path)
    print(f"[OK] Certificate generated (status: {certificate['erasureResult']['status']})")

    # 証明書保存
    print(f"\n[STEP 3] Saving certificate...")
    cert_filepath = save_certificate(certificate, actor_id)

    # サマリー表示
    print("\n" + "=" * 60)
    print("[OK] GDPR Deletion Certificate Generated")
    print("=" * 60)
    result = certificate["erasureResult"]
    print(f"\n  Actor ID:         {actor_id}")
    print(f"  Status:           {result['status']}")
    print(f"  Records found:    {result['totalRecordsFound']}")
    print(f"  Records deleted:  {result['totalRecordsDeleted']}")
    print(f"  Records failed:   {result['totalRecordsFailed']}")
    verification = certificate["verification"]
    if verification["postDeletionCheck"] is not None:
        verified_label = "PASS" if verification["postDeletionCheck"] else "FAIL"
        print(f"  Verification:     {verified_label}")
    print(f"  Certificate:      {cert_filepath}")
    print(f"  Audit log hash:   {certificate['auditTrail']['auditLogSha256'][:16]}...")


if __name__ == "__main__":
    main()
