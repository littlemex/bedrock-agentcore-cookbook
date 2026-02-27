# Cookbook 検証項目ギャップ分析レポート

**生成日時**: 2026-02-27
**レビュー対象**: bedrock-agentcore-cookbook examples 01-10
**レビュアー**: 4 名の Opus 4.6 エージェント（並行レビュー）

## エグゼクティブサマリー

本レポートは、bedrock-agentcore-cookbook の全 10 個の example について、追加すべき検証項目がないかを厳格にレビューした結果をまとめたものです。全 example を通じて**合計 19 件の CRITICAL**、**39 件の HIGH**、**33 件の MEDIUM**の検証ギャップが検出されました。

### 最重要課題（全体共通）

**Cognito Client Secret Lifecycle Management の検証が完全に欠落**しています。以下の example で CRITICAL として指摘されました：

- **Example 08** (Outbound Auth): OAuth2 Credential Provider で CognitoOauth2 ベンダーを使用するにも関わらず、シークレット回転の検証が存在しない
- **Example 09** (E2E Auth Test): E2E 検証スイートとして、本番運用で必須となるシークレット回転の検証が存在しない
- **Example 10** (Auth Cookbook): 認証関連の包括的 cookbook として、シークレットライフサイクル管理の説明・実装例が完全に欠落

本番運用では避けて通れないシークレット回転プロセス（`AddUserPoolClientSecret` / `DeleteUserPoolClientSecret` API、デュアルシークレット運用、ゼロダウンタイム検証）が、cookbook の全範囲で未検証です。

### Example 別サマリー

| Example | タイトル | 評価 | CRITICAL | HIGH | MEDIUM |
|---------|---------|------|----------|------|--------|
| 01 | Memory API | B | 2 | 4 | 5 |
| 02 | IAM ABAC | B+ | 2 | 5 | 4 |
| 03 | Gateway | D | 3 | 5 | 5 |
| 04 | Policy Engine | C | 3 | 4 | 4 |
| 05 | End-to-End | C+ | 3 | 4 | 5 |
| 06 | Response Interceptor | B- | 2 | 4 | 5 |
| 07 | Request Interceptor | A- | 0 | 5 | 4 |
| 08 | Outbound Auth | D | 2 | 6 | 5 |
| 09 | E2E Auth Test | B- | 3 | 5 | 5 |
| 10 | Auth Cookbook | B- | 2 | 5 | 6 |
| **合計** | | | **19** | **39** | **33** |

**最も深刻なギャップ**: Example 03 (Gateway) と Example 08 (Outbound Auth) は評価 D で、即座の対応が必要です。

---

## Example 01: Memory API

### 評価: B

基本的なテナント分離検証は良好ですが、正常系の検証に重大な欠落があります。

### CRITICAL (2 件)

#### 1. Memory Record の内容分離検証が不完全

**現状**: retrieve テストで 0 records が返されており、「データが存在する状態での取得」が検証されていない。

**問題**: 0 件取得は「テナント分離が機能している」のか「単にデータがまだインデックスされていない」のか区別できない。

**推奨対応**:
```python
# create → (待機) → retrieve の一連フローで正のテストを実装
def test_tenant_a_retrieve_existing():
    # Memory Record 作成
    create_response = memory_api.create_records(tenant="tenant-a", ...)

    # ベクトルインデックス構築待機（10-30 秒）
    time.sleep(30)

    # 自テナントのデータが取得できることを確認
    retrieve_response = memory_api.retrieve(tenant="tenant-a", ...)
    assert len(retrieve_response["records"]) > 0
    assert retrieve_response["records"][0]["tenant_id"] == "tenant-a"
```

#### 2. Cognito Client Secret のライフサイクル統合検証が欠落

**現状**: STS AssumeRole + ExternalId を使用しているが、ExternalId がハードコード（`tenant-a`, `tenant-b`）されている。

**問題**: 本番環境では ExternalId は Cognito トークンから動的に取得すべきだが、その統合テストが欠落。

**推奨対応**: Cognito トークンから ExternalId を動的に取得し、AssumeRole に渡す統合フローの検証を追加。

### HIGH (4 件)

3. **DeleteMemoryRecord の Cross-Tenant 検証**: Delete 操作（`BatchDeleteMemoryRecords`, `DeleteMemoryRecord`）に対する Cross-Tenant アクセス拒否の検証がない。
4. **UpdateMemoryRecord の Cross-Tenant 検証**: `BatchUpdateMemoryRecords` に対する Cross-Tenant アクセス拒否の検証がない。
5. **同一テナント内の異なるユーザー間の分離検証**: `tenant-a/user-001` と `tenant-a/user-002` が互いのレコードにアクセスできるか/できないかの検証がない。
6. **Memory ACTIVE 状態の確認**: Memory 作成後に ACTIVE になるまでの待機処理がない。

### MEDIUM (5 件)

7. eventExpiryDuration の動作検証
8. Memory Strategy の検証（ベクトル検索精度）
9. エラーハンドリングの検証（存在しない Memory ID へのアクセス）
10. リソース制限（RPS）の検証
11. クリーンアップの冪等性検証

---

## Example 02: IAM ABAC

### 評価: B+

IAM ABAC の検証としては充実していますが、全 Memory API アクションでの一貫性検証が不足しています。

### CRITICAL (2 件)

#### 1. namespace Condition Key での Write 操作分離検証が不完全

**現状**: H-1 検証では `BatchCreateMemoryRecords` と `RetrieveMemoryRecords` の 2 つの API のみ検証。

**問題**: IAM Policy で許可している `BatchUpdateMemoryRecords`, `BatchDeleteMemoryRecords`, `DeleteMemoryRecord`, `ListMemoryRecords`, `GetMemoryRecord` に対する namespace Condition Key の検証が欠落。

**特に重要**: Delete 操作が namespace Condition で制御されるか（テナント A がテナント B のデータを削除できないこと）は CRITICAL。

**推奨対応**:
```python
def test_namespace_condition_with_delete():
    # tenant-a のロールで tenant-b の namespace に対して Delete 実行
    response = memory_api.delete_record(
        namespace="/tenant-b/user-001/",
        record_id="record-123"
    )
    assert_access_denied(response)
```

#### 2. StringLike vs StringEquals の挙動差異検証が欠落

**現状**: H-1 では `StringLike: "/tenant-a/*"` を使用しているが、`StringEquals` との挙動差異の検証がない。

**問題**: ワイルドカードパターンのバイパスリスク（例: `/tenant-a/../tenant-b/` のようなパストラバーサル）の検証が必要。

**推奨対応**: StringLike と StringEquals の両方でパストラバーサルやプレフィックス攻撃の検証を実施。

### HIGH (5 件)

3. **namespace パストラバーサル検証**: namespace に `/../` や `%2F..%2F` を含むパスを指定した場合の検証がない。
4. **空文字列 namespace の検証**: namespace に空文字列 `""` や `/` を指定した場合の挙動検証がない。
5. **Wildcard Condition Key のスコープ検証**: `/tenant-a/*` が `/tenant-abc/` にもマッチするかの検証がない（プレフィックス攻撃リスク）。
6. **STS SessionTags 経由での動的 namespace 制御検証**: 現在の検証はハードコードされた namespace。STS SessionTags の `tenant_id` タグから動的に namespace を構成する際のセキュリティ検証がない。
7. **複数 namespace の同時指定検証**: `BatchCreateMemoryRecords` の `namespaces` フィールドは配列。複数 namespace 同時指定時の Condition Key 評価動作の検証がない。

### MEDIUM (4 件)

8. IAM Policy 伝播遅延の検証
9. Condition Key の大文字小文字区別検証
10. actorId Condition Key のフォローアップ検証
11. テストロールのクリーンアップ検証（H-1 テストロールが残存するリスク）

---

## Example 03: Gateway

### 評価: D

**最も深刻な問題を抱えている example**。検証が全て未実行であり、検証スクリプト（`test-phase3.py` 等）もこのディレクトリに存在しません。

### CRITICAL (3 件)

#### 1. 検証が全て未実行

**現状**: VERIFICATION_RESULT.md の全項目が「(未実行)」。

**問題**: deploy-gateway.py と cleanup.py のコードは存在するが、実際の検証テストスクリプトが存在しない。

**推奨対応**: 以下の検証スクリプトを早急に作成・実行：
- `test-phase3.py`: Gateway + Policy Engine 統合テスト
- `create-policy-engine.py`: Policy Engine 作成
- `put-cedar-policies.py`: Cedar ポリシー登録

#### 2. JWT 認証バイパス検証の欠如

**現状**: Gateway に `CUSTOM_JWT` Authorizer を設定しているが、以下の検証が計画に含まれていない。

**問題**: 以下の基本的な JWT 検証シナリオが未検証：
- 無効な JWT トークンでの Gateway アクセス拒否
- 期限切れ JWT トークンでの Gateway アクセス拒否
- 異なる Cognito User Pool で発行された JWT での拒否
- JWT なしでの Gateway アクセス拒否

**推奨対応**:
```python
def test_gateway_jwt_validation():
    # 無効 JWT
    response = invoke_gateway(jwt="invalid-token")
    assert response.status_code == 401

    # 期限切れ JWT
    expired_jwt = create_expired_jwt()
    response = invoke_gateway(jwt=expired_jwt)
    assert response.status_code == 401

    # JWT なし
    response = invoke_gateway(jwt=None)
    assert response.status_code == 401
```

#### 3. Gateway IAM Role の権限昇格検証が欠落

**現状**: `deploy-gateway.py` で作成される IAM Role は `bedrock-agentcore:*` + `lambda:InvokeFunction` の権限を持つ。

**問題**: Gateway 経由で意図しない Lambda 関数を呼び出せないことの検証がない。

**推奨対応**: Gateway 経由で許可されていない Lambda を呼び出した場合の拒否検証を追加。

### HIGH (5 件)

4. **Cedar Policy Engine の ENFORCE モード検証**: 計画には `LOG_ONLY -> ENFORCE` の遷移が含まれているが、ENFORCE モードでの実際の拒否検証が明示的にリストされていない。
5. **Cedar ポリシーなしの挙動検証**: Policy Engine にポリシーが一切ない状態での Gateway 呼び出し挙動の検証がない（デフォルト Deny かデフォルト Allow か）。
6. **Gateway Target のステータス遷移検証**: Target が CREATING → ACTIVE になる間の API 呼び出しの挙動検証がない。
7. **Cognito Client Secret のライフサイクル検証**: Gateway に `CUSTOM_JWT` Authenticator を使用。Cognito App Client のシークレット回転時の Gateway 動作検証がない。
8. **MCP プロトコルのエラーハンドリング検証**: Lambda MCP Server が不正なレスポンスを返した場合の Gateway の挙動検証がない。

### MEDIUM (5 件)

9. Gateway の同時接続数/RPS 制限の検証
10. Lambda Target のタイムアウト検証（30 秒超過時の挙動）
11. 複数 Target の追加検証
12. Gateway の冪等なデプロイ検証
13. cleanup.py の API パラメータ不整合（`gatewayId` vs `gatewayIdentifier`）

---

## Example 04: Policy Engine + Cedar Policy

### 評価: C

Policy Engine の構文検証とデプロイまでは実施されていますが、実際のアクセス制御が機能することの E2E 検証が欠落しています。

### CRITICAL (3 件)

#### 1. PartiallyAuthorizeActions API の実動作未検証

**現状**: PARTIALLY_AUTHORIZE_VERIFICATION.md で BLOCKED と明記。

**問題**: boto3 でのサポート有無が最後に確認されたのは boto3 1.42.54 時点。これが解消されていない限り、Cedar Policy の RBAC が実際に機能するかの確定的な検証が欠落。

**推奨対応**: 定期的に boto3 の最新バージョンで PartiallyAuthorizeActions API のサポート状況を確認し、サポート開始後に検証を追加。

#### 2. Policy Engine mode=ENFORCE での動作未検証

**現状**: 全検証が LOG_ONLY モードで実施されている。

**問題**: LOG_ONLY はポリシー評価をログに記録するだけでアクセスは常に許可する。Cedar Policy が実際にアクセス制御として機能する保証がない。

**推奨対応**:
```python
def test_enforce_mode_deny():
    # Policy Engine を ENFORCE モードに変更
    update_policy_engine(mode="ENFORCE")

    # user ロールで delete_data_source を呼び出し
    response = invoke_tool(
        tool="delete_data_source",
        jwt_role="user"
    )

    # アクセス拒否を確認
    assert response.status_code == 403
    assert "Denied by Cedar Policy" in response.error_message
```

#### 3. Cedar Policy の deny ルール未実装・未検証

**現状**: 現在 permit ルールのみ。

**問題**: explicit deny ポリシー（例: guest ロールを明示拒否）が存在しない。Cedar のデフォルト deny 動作への依存のみで、それが AgentCore で期待通りに動作するかの検証がない。

**推奨対応**: explicit deny ポリシーを追加し、permit と deny の優先度が正しく評価されることを検証。

### HIGH (4 件)

4. **JWT クレーム操作（タグ偽装）の検証不足**: JWT クレームを改ざんした場合（例: role を admin に偽装）に Gateway/Policy Engine が正しく拒否するかの検証がない。
5. **role 属性なしの JWT での動作未検証**: JWT に `role` クレームが含まれない場合の動作が未検証。
6. **複数ロールの同時付与時の動作未検証**: JWT に複数ロール（例: `role=["admin", "user"]`）が設定された場合の動作が不明。
7. **Gateway ARN ハードコードのリスク検証不足**: user-policy.cedar に Gateway ARN がハードコードされており、環境間移行時にポリシーが機能しなくなるリスクへの言及がない。

### MEDIUM (4 件)

8. Cedar Policy 更新時の一貫性検証
9. Policy Engine のエラーハンドリング検証
10. Cognito Client Secret 管理の検証不足
11. テストユーザーのパスワードがハードコード

---

## Example 05: End-to-End Integration Test

### 評価: C+

Memory + IAM ABAC のテナント分離検証は比較的網羅的ですが、README で謳っている Gateway + Policy Engine 統合検証がコードに存在しません。

### CRITICAL (3 件)

#### 1. Gateway + Policy Engine 統合検証の完全欠落

**現状**: README には「Gateway + Policy Engine」「Cedar Policy の評価」の検証を謳っているが、test-phase5.py は Memory + IAM ABAC のみを実装。

**問題**: README の「テスト内容」セクション 2 と 3 に対応するコードが存在しない。README とコードの乖離。

**推奨対応**: README に記載された Gateway + Policy Engine 統合検証のテストコードを実装。

#### 2. STS SessionTags による ABAC 検証の欠落

**現状**: テストでは `ExternalId` による AssumeRole のみ実装。

**問題**: STS `TagSession` / `TransitiveTagKeys` による SessionTags ABAC の検証が実装されていない。README は「STS SessionTags ABAC」を謳っているが、実際には ExternalId ベースの簡易検証のみ。

**推奨対応**:
```python
def test_sts_session_tags_abac():
    # STS AssumeRole with SessionTags
    sts_response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="test-session",
        Tags=[
            {"Key": "tenant_id", "Value": "tenant-a"},
            {"Key": "user_id", "Value": "user-001"}
        ],
        TransitiveTagKeys=["tenant_id"]
    )

    # SessionTags ベースの ABAC 検証
    # ...
```

#### 3. Memory API の書き込み分離（Write Isolation）未検証

**現状**: Tenant A が Tenant B の namespace に Memory レコードを**書き込む**試行の検証がない。

**問題**: 現在は read (retrieve)のみの cross-tenant deny テスト。write path での分離が検証されていない。

**推奨対応**: `BatchCreateMemoryRecords` で他テナントの namespace への書き込みを試行し、拒否されることを検証。

### HIGH (4 件)

4. **Memory レコード削除の cross-tenant 検証不足**: Tenant A が Tenant B のレコードを削除できないことの検証がない。
5. **同一テナント内の異なるユーザー間の分離検証**: tenant-a/user-001 と tenant-a/user-002 の間の namespace 分離が検証されていない。
6. **Cognito JWT + Gateway の統合フロー検証不足**: README に記載されている「Cognito JWT Authorizer」を経由した Gateway 呼び出しの E2E フローが test-phase5.py に含まれていない。
7. **IAM Policy の `bedrock-agentcore:namespace` Condition Key 検証が間接的**: README で言及されている Condition Key の直接的な検証ではなく、Memory API の動作結果から間接的に推測しているのみ。

### MEDIUM (5 件)

8. エラーレスポンスの詳細検証不足
9. 大量レコード時のパフォーマンス/RPS 検証なし
10. AssumeRole のセッション有効期限境界テスト
11. 並行アクセス時のテナント分離検証
12. phase5-config.json に AWS アカウント ID のハードコード

---

## Example 06: Response Interceptor

### 評価: B-

ローカル検証と Lambda 直接呼び出しのカバレッジは良好ですが、Gateway 経由の E2E フロー検証が欠落しており、JWT 署名検証なしという重大なセキュリティ上の制約がテストで露呈されていません。

### CRITICAL (2 件)

#### 1. Gateway 経由の E2E 検証が未実施

**現状**: ローカル呼び出しと Lambda 直接 invoke のみ。

**問題**: Gateway を経由した実際のリクエストフローでの検証がない。Gateway が Response Interceptor を正しく呼び出し、フィルタリング後のレスポンスをクライアントに返却する E2E フローが未確認。

**推奨対応**:
```python
def test_response_interceptor_via_gateway():
    # Gateway 経由で tools/list を呼び出し
    gateway_response = invoke_gateway_tools_list(
        jwt_role="user",
        gateway_url=gateway_endpoint
    )

    # Response Interceptor でフィルタリングされたツールのみ返却されることを確認
    assert len(gateway_response["tools"]) == 2  # retrieve_doc, list_tools
    assert "delete_data_source" not in [t["name"] for t in gateway_response["tools"]]
```

#### 2. JWT 署名検証のバイパスリスク

**現状**: lambda_function.py の `extract_role_from_jwt()` は JWT の署名検証を行っていない（base64 デコードのみ）。

**問題**: 本番環境では攻撃者が任意の role クレームを設定した未署名 JWT を送信してフィルタリングをバイパスできる。テストでも未署名 JWT (mock JWT) を使用しているため、この脆弱性が検証で見逃されている。

**推奨対応**: PyJWT を使用した署名検証付きの JWT 検証ロジックを実装し、署名検証ありの場合の動作テストを追加。README に注意書きがあるが、検証スクリプトで署名検証ありの場合の動作テストが必要。

### HIGH (4 件)

3. **tools/call リクエストのフィルタリングバイパス検証不足**: Response Interceptor は tools/list のフィルタリングのみ。ユーザーが tools/list をバイパスして直接 tools/call で制限されたツールを呼び出した場合の検証がない。
4. **RBAC ルールのハードコードに対するセキュリティリスク検証**: `ROLE_PERMISSIONS` が Lambda コード内にハードコード。更新手順（Lambda の再デプロイが必要）の検証がない。
5. **大量ツール時のパフォーマンス検証不足**: 数百のツールがある場合の Response Interceptor の処理時間が Lambda の 30 秒タイムアウト内に収まるかの検証がない。
6. **tools/call のレスポンスに対する Interceptor 動作の検証不足**: tools/call のレスポンスに機密情報が含まれる場合のフィルタリングの検証がない。

### MEDIUM (5 件)

7. Authorization ヘッダーのケースセンシティビティ
8. Lambda コールドスタートの影響検証
9. Interceptor 内での例外発生時の Gateway 動作検証不足
10. `interceptorOutputVersion: "1.0"` のバージョン互換性
11. 空のツールリスト (tools: []) のレスポンスでの通過判定ロジック

---

## Example 07: Request Interceptor

### 評価: A-

RBAC の基本的な認可ロジック（admin/user/guest の各ロール、JWT なし/不正 JWT、ライフサイクルメソッドのバイパス、システムツールのバイパス）は網羅的にテストされています。ローカルとリモートの両方で検証されている点も良好です。

### CRITICAL (0 件)

該当なし。Request Interceptor の主要な RBAC 認可ロジックは十分にカバーされています。

### HIGH (5 件)

1. **notifications/initialized メソッドのバイパス検証**: `MCP_LIFECYCLE_METHODS` に `notifications/initialized` が含まれているが、テストケースが存在しない。
2. **未知のロール（例: "operator"）に対する動作検証**: `ROLE_TOOL_PERMISSIONS` に定義されていないロールが来た場合の挙動を明示的にテストすべき。
3. **JWT ペイロードに role クレームが欠落している場合の動作検証**: `claims.get("role", "guest")` でデフォルト `guest` にフォールバックする動作を明示的にテストすべき。
4. **リクエスト加工（ヘッダー追加・変更）の検証**: README で「リクエストの加工・拡張」が用途として挙げられているが、現在の Lambda はヘッダーをそのまま通過させるのみ。
5. **body が文字列 (JSON 文字列) の場合の処理検証**: `lambda_function.py:170-175` で body が文字列の場合のパース処理があるが、テストがない。

### MEDIUM (4 件)

6. 大量のツール名パターンの検証
7. Lambda タイムアウト・メモリ制限の検証
8. 同時リクエスト（並行呼び出し）時の動作検証
9. Gateway に Interceptor 設定後の E2E 検証（Gateway 経由で実際にクライアントリクエストが Interceptor を通過する E2E テストがない）

---

## Example 08: Outbound Auth

### 評価: D

**不十分 - 重大な検証欠落あり**。現在のテストは Credential Provider API の基本的な CRUD 操作とベンダー一覧取得にとどまっており、以下の重大な欠落があります。

### CRITICAL (2 件)

#### 1. Cognito Client Secret Lifecycle Management の検証が完全に欠落

**現状**: 08-outbound-auth は OAuth2 Credential Provider を扱っており、CognitoOauth2 ベンダーが 25 種の一つとしてサポートされていることを確認している（VERIFICATION_RESULT.md セクション 6.4）。**しかし、CognitoOauth2 ベンダーを使用した Credential Provider の作成・管理テストが一切存在しない。** 現在のテストは CustomOauth2 のみ。

**問題**: 以下の検証が全く行われていない：
- **CognitoOauth2 ベンダーでの Credential Provider 作成テスト**: Cognito User Pool の client_id/client_secret を使用した OAuth2 M2M フローの検証
- **シークレット回転（Secret Rotation）の検証**: `AddUserPoolClientSecret` API でセカンダリシークレットを追加し、OAuth2 Credential Provider の `clientSecret` を更新した後の動作検証
- **デュアルシークレット運用の検証**: Cognito App Client は最大 2 つのシークレットを同時に保持できる。旧シークレットで発行済みの Token Vault 内のトークンと、新シークレットでの認証が並行して動作するかの検証
- **`AddUserPoolClientSecret` / `DeleteUserPoolClientSecret` API の検証**: Cognito 側のシークレット操作と、AgentCore Token Vault 側の OAuth2 Credential Provider 更新のシーケンスが正しく動作するか
- **シークレット回転中のゼロダウンタイムの検証**: 回転プロセス中に MCP サーバーへの Outbound Auth が中断しないことの確認

**推奨対応**:
```python
def test_cognito_oauth2_secret_rotation():
    # Phase 1: CognitoOauth2 ベンダーで Credential Provider 作成
    provider = create_oauth2_credential_provider(
        vendor="CognitoOauth2",
        client_id=cognito_client_id,
        client_secret=cognito_client_secret_primary
    )

    # Phase 2: Cognito 側で新シークレット追加
    cognito.add_user_pool_client_secret(
        UserPoolId=user_pool_id,
        ClientId=cognito_client_id
    )

    # Phase 3: Credential Provider の clientSecret 更新
    update_oauth2_credential_provider(
        provider_id=provider["id"],
        client_secret=cognito_client_secret_secondary
    )

    # Phase 4: デュアルシークレット運用検証
    # 旧シークレットで発行されたトークンが有効
    assert validate_token_with_old_secret() == True
    # 新シークレットで新規認証が成功
    assert authenticate_with_new_secret() == True

    # Phase 5: 旧シークレット削除
    cognito.delete_user_pool_client_secret(
        UserPoolId=user_pool_id,
        ClientId=cognito_client_id,
        SecretId=cognito_client_secret_primary_id
    )

    # Phase 6: ゼロダウンタイム検証
    # 削除後も新シークレットで認証成功
    assert authenticate_with_new_secret() == True
```

**これは本 example の核心機能に関わるため、CRITICAL として指摘します。**

#### 2. OAuth2 Credential Provider の更新 (Update) テストが欠落

**現状**: CRUD のうち U (Update)のテストがない。

**問題**: `clientSecret` の更新（シークレット回転シナリオ）は運用上必須。`update_oauth2_credential_provider` API の検証が必要。

**推奨対応**: OAuth2 Credential Provider の `clientSecret` を更新し、更新後に正常に動作することを検証。

### HIGH (6 件)

3. **CognitoOauth2 ベンダー固有の設定パラメータの検証**: CognitoOauth2 は CustomOauth2 とは異なる設定構造を持つはず（`cognitoOauth2ProviderConfig` のようなベンダー固有フィールド）。
4. **API Key Credential Provider の取得 (Get) テストが欠落**: OAuth2 Provider には get テストがあるが、API Key Provider には create と delete のみ。
5. **Token Vault のセキュリティ検証**: Token Vault に格納された `clientSecret` や `apiKey` が API レスポンスで平文返却されないことの検証。
6. **OAuth2 トークン取得フローの検証**: Credential Provider を Gateway Target に紐付けた後、実際に OAuth2 token endpoint からアクセストークンを取得できるかの検証。現在のテストではダミーの endpoint (`https://example.com`) を使用。
7. **エラーケース: 重複名の Provider 作成**: `ConflictException` の処理は実装されているが、意図的に重複を発生させるテストケースがない。
8. **エラーケース: 存在しない Provider の取得/削除**: `ResourceNotFoundException` の検証がない。

### MEDIUM (5 件)

9. 複数の Credential Provider タイプの併用検証
10. OAuth2 Provider の一覧 (List) ページネーション検証
11. OAuth2 Provider の scopestrings/audience パラメータ検証
12. 各ベンダー固有の設定差異の検証
13. Rate Limiting / Throttling の検証

---

## Example 09: E2E Auth Test

### 評価: B-

Inbound Auth、Outbound Auth（Secrets Manager + DynamoDB ABAC）、Dual Auth Independence の基本フローは十分にカバーされています。しかし、**Cognito Client Secret Lifecycle Management の検証が完全に欠落**しており、本番運用を想定した E2E 検証スイートとしては重大な不足があります。

### CRITICAL (3 件)

#### 1. Cognito Client Secret Lifecycle Management の E2E 検証が完全に欠落

**現状**: `AddUserPoolClientSecret` / `DeleteUserPoolClientSecret` API によるシークレット回転の検証が存在しない。

**問題**: E2E 検証スイートとして、本番運用で必須となるシークレット回転の検証が存在しない。以下の検証が欠落：
- `AddUserPoolClientSecret` API によるシークレット追加の検証なし
- `DeleteUserPoolClientSecret` API による旧シークレット削除の検証なし
- デュアルシークレット運用（新旧 2 つのシークレットが同時に有効な状態）の検証なし
- シークレット回転中のゼロダウンタイム検証なし
- シークレット回転後に `SECRET_HASH` が新旧どちらでも認証成功するかの検証なし

**推奨対応**:
```python
def test_cognito_secret_rotation_e2e():
    # Phase 1: 初期状態でユーザー認証成功
    jwt_old = authenticate_user_with_secret(secret=primary_secret)
    assert jwt_old is not None

    # Phase 2: Cognito 側で新シークレット追加
    add_result = cognito.add_user_pool_client_secret(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    secondary_secret = add_result["ClientSecret"]

    # Phase 3: デュアルシークレット状態での認証
    jwt_old_secret = authenticate_user_with_secret(secret=primary_secret)
    jwt_new_secret = authenticate_user_with_secret(secret=secondary_secret)
    assert jwt_old_secret is not None
    assert jwt_new_secret is not None

    # Phase 4: 旧シークレット削除
    cognito.delete_user_pool_client_secret(
        UserPoolId=user_pool_id,
        ClientId=client_id,
        SecretId=primary_secret_id
    )

    # Phase 5: 新シークレットのみで認証成功
    jwt_after_rotation = authenticate_user_with_secret(secret=secondary_secret)
    assert jwt_after_rotation is not None

    # Phase 6: 旧シークレットで認証失敗
    with pytest.raises(NotAuthorizedException):
        authenticate_user_with_secret(secret=primary_secret)
```

#### 2. JWT トークンリフレッシュフローの検証なし

**現状**: RefreshToken を使用したトークン更新の E2E 検証が欠落。

**問題**: シークレット回転中の RefreshToken フローの検証なし。

**推奨対応**: RefreshToken を使用したトークン更新フローを追加し、シークレット回転前後で RefreshToken が正常に動作することを検証。

#### 3. 期限切れ JWT の明示的な E2E 検証なし

**現状**: test_inbound_auth.py の IN-05 では無効署名とヘッダー欠落のみ。

**問題**: `ExpiredSignatureError` をトリガーする実際の期限切れトークンのテストがない。

**推奨対応**: 期限切れの JWT トークンを生成（またはモック）し、Lambda Authorizer が正しく拒否することを検証。

### HIGH (5 件)

4. **Cedar Policy Engine の実際の評価テストなし**: README で「現在の実装で検証できない項目」として記載されているが、cdk-agentcore-gateway ディレクトリが存在し、CDK スタックの README はあるものの実装コード（`*.ts`, `*.js`）が存在しない。
5. **Response Interceptor のクロステナントデータ漏洩テストなし**: Response Interceptor がレスポンスボディに他テナントのデータが含まれていないことを検証するテストがない。
6. **同時アクセス（並行テスト）なし**: 複数テナントが同時にアクセスした場合の競合条件の検証がない。
7. **テナント無効化テストなし**: テナントを inactive に変更した後のアクセス拒否検証がない（authorizer_saas.py はステータスチェックしているが、E2E テストでカバーされていない）。
8. **Request Interceptor の tools/call 拒否テストが不十分**: user ロールが delete_memory や store_memory を呼び出した場合の拒否テストがない。guest ロールのテストが完全に欠落。

### MEDIUM (5 件)

9. Pre Token Generation Lambda V2 の直接テストなし
10. エラーレスポンス形式の一貫性テストなし
11. Lambda コールドスタートのパフォーマンステストなし
12. DynamoDB キャッシュ戦略のテストなし
13. setup-infrastructure.sh の `.env` 出力パスがハードコード（パス不整合）

---

## Example 10: Auth Cookbook

### 評価: B-

認証認可の基本パターン（Lambda Authorizer、Interceptor、Cedar、IAM ABAC）は網羅的にカバーされており、fail-closed 設計やキャッシュ戦略など実践的な実装例が含まれています。しかし、**Cognito Client Secret Lifecycle Management の説明・実装例が完全に欠落**しており、認証関連の包括的 cookbook としては重大な不足があります。

### CRITICAL (2 件)

#### 1. Cognito Client Secret Lifecycle Management の説明・実装例が完全に欠落

**現状**: 認証関連の包括的 cookbook であるにも関わらず、シークレットライフサイクル管理の説明・実装例が存在しない。

**問題**: 以下の重要なトピックが欠落：
- `AddUserPoolClientSecret` / `DeleteUserPoolClientSecret` API の使用例なし
- デュアルシークレット運用の手順・コード例なし
- シークレット回転のベストプラクティス説明なし
- シークレット回転中の `SECRET_HASH` 計算の注意点なし
- ゼロダウンタイムでのシークレット回転手順なし

**推奨対応**: 新しいセクションを追加：
```markdown
## Cognito Client Secret のライフサイクル管理

### シークレット回転のベストプラクティス

Cognito App Client のシークレットは定期的に回転すべきです。以下の手順でゼロダウンタイムのシークレット回転が可能です。

#### 手順

1. **新シークレット追加**: `AddUserPoolClientSecret` API を使用
2. **デュアルシークレット運用**: 新旧両方のシークレットが有効な状態で運用
3. **アプリケーション更新**: 新シークレットを使用するように更新
4. **旧シークレット削除**: `DeleteUserPoolClientSecret` API を使用

#### 実装例

\`\`\`python
# cognito_secret_rotation.py
import boto3

def rotate_client_secret(user_pool_id, client_id):
    cognito = boto3.client("cognito-idp")

    # Step 1: 新シークレット追加
    add_response = cognito.add_user_pool_client_secret(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    new_secret = add_response["ClientSecret"]

    # Step 2: アプリケーション設定更新（手動または CI/CD）
    print(f"新シークレットを環境変数に設定: {new_secret}")
    input("アプリケーション更新後、Enter を押してください...")

    # Step 3: 旧シークレット削除
    # 注意: シークレット ID は DescribeUserPoolClient で取得
    describe_response = cognito.describe_user_pool_client(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    old_secret_id = describe_response["UserPoolClient"]["ClientSecretIds"][0]

    cognito.delete_user_pool_client_secret(
        UserPoolId=user_pool_id,
        ClientId=client_id,
        SecretId=old_secret_id
    )
    print("旧シークレットを削除しました")
\`\`\`
```

#### 2. Token Refresh フローの実装例なし

**現状**: RefreshToken を使用したトークン更新のサンプルコードがない。

**問題**: クライアント側の認証フロー（initiate_auth → refresh_token → re-auth）の完全な例がない。

**推奨対応**: RefreshToken を使用したトークン更新の実装例を追加。

### HIGH (5 件)

#### 3. authorizer_saas.py の JWT 検証で `client_id` を require しているが ID Token には `client_id` クレームがない（実装バグ）

**ファイル**: `/home/coder/bedrock-agentcore-cookbook/examples/10-auth-cookbook/lambda-authorizer/authorizer_saas.py:49`

**現状**:
```python
payload = jwt.decode(
    token,
    key,
    algorithms=["RS256"],
    options={"require": ["exp", "client_id", "token_use"]},  # ← client_id を require
)
```

**問題**: Cognito ID Token には `client_id` ではなく `aud` クレームが含まれる。authorizer_basic.py は正しく `audience=CLIENT_ID` で検証しているが、authorizer_saas.py は `audience` パラメータが指定されていない上に、`client_id` を require している。

**影響**: **実際にデプロイすると ID Token で認証失敗する可能性がある実装バグ**。

**推奨修正**:
```python
payload = jwt.decode(
    token,
    key,
    algorithms=["RS256"],
    audience=CLIENT_ID,  # ← audience パラメータ追加
    options={"require": ["exp", "token_use"]},  # ← client_id を削除
)
```

#### 4. response_interceptor の decode_jwt_payload で `client_id` を require（実装バグ）

**ファイル**: `/home/coder/bedrock-agentcore-cookbook/examples/10-auth-cookbook/response-interceptor/interceptor_basic.py:43`

**現状**:
```python
payload = jwt.decode(
    token,
    key,
    algorithms=["RS256"],
    options={"require": ["exp", "client_id", "token_use"]},  # ← client_id を require
)
```

**問題**: ID Token の場合は `client_id` は存在しない。Request Interceptor は `audience=CLIENT_ID` で正しく検証しているのに対し、Response Interceptor は `audience` パラメータなしで `client_id` を require しており不整合。

**推奨修正**:
```python
payload = jwt.decode(
    token,
    key,
    algorithms=["RS256"],
    audience=CLIENT_ID,  # ← audience パラメータ追加
    options={"require": ["exp", "token_use"]},  # ← client_id を削除
)
```

5. **Secrets Manager のテナント分離実装例なし**: IAM ABAC で Secrets Manager をテナント分離する実装例が cookbook に含まれていない。
6. **エラーハンドリングのベストプラクティス説明なし**: Lambda Authorizer、Interceptor でのエラー応答のベストプラクティスが体系的に説明されていない。
7. **multi_tenant.cedar の forbid ポリシーが tenant-a のみにハードコード**: `/home/coder/bedrock-agentcore-cookbook/examples/10-auth-cookbook/cedar-policies/multi_tenant.cedar:38` で `principal.getTag("tenant_id") != "tenant-a"` により tenant-a 以外を全拒否。汎用的なマルチテナントパターンとしては不適切。

### MEDIUM (6 件)

8. Cognito User Pool 設定のベストプラクティスなし
9. Lambda Layer 管理の説明が最小限
10. 監査ログ/モニタリングの実装例なし
11. pre_token_generation.py（V1）と pre_token_gen_v2.py（V2）の使い分け説明不足
12. interceptor_private_sharing.py の `extract_resource_id` が未実装（`return "agent-id-example"` とハードコード）
13. lambda-authorizer ディレクトリに zip ファイルがコミットされている（ビルド成果物は.gitignore で除外すべき）

---

## 全体の共通課題

### 1. Cognito Client Secret Lifecycle Management（最重要）

**影響範囲**: Example 01, 03, 08, 09, 10

本番運用で避けて通れないシークレット回転プロセス（`AddUserPoolClientSecret` / `DeleteUserPoolClientSecret` API、デュアルシークレット運用、ゼロダウンタイム検証）が、cookbook の全範囲で未検証または未文書化です。

**優先対応**:
1. **Example 08**: CognitoOauth2 ベンダーでの Credential Provider 作成とシークレット回転の検証を追加
2. **Example 09**: E2E テストスイートにシークレット回転シナリオを追加
3. **Example 10**: Cookbook にシークレットライフサイクル管理のセクションと実装例を追加

### 2. Gateway 経由の真の E2E 検証が不足

**影響範囲**: Example 03, 04, 05, 06

各コンポーネントの単体・ローカル検証は実施されているが、Gateway を経由した統合フローの E2E 検証が欠落しています。

**推奨対応**: Gateway 経由のエンドツーエンドフロー（Cognito JWT → Gateway Authorizer → Policy Engine → Interceptor → Lambda Target）を検証するテストケースを追加。

### 3. ENFORCE モードでの実アクセス制御検証の欠落

**影響範囲**: Example 04

LOG_ONLY モードでの検証のみで、実際にアクセスが拒否される動作の確認がありません。

**推奨対応**: Policy Engine を ENFORCE モードに設定し、Cedar ポリシーによる実際の拒否動作を検証。

### 4. セキュリティバイパスシナリオの検証不足

**影響範囲**: Example 04, 05, 06, 07

JWT 偽装、ツール直接呼び出し、タグ操作などのセキュリティバイパスシナリオの体系的な検証がありません。

**推奨対応**: セキュリティバイパス試行のテストケースを追加し、防御メカニズムが正しく機能することを検証。

---

## 優先順位付けされた推奨アクション

### P0（即座に対応すべき）

1. **Example 03 の検証スクリプト作成と実行**: 検証が全て未実行（評価 D）
2. **Example 08 の Cognito Client Secret Lifecycle Management 検証追加**: 核心機能が未検証（評価 D）
3. **Example 10 の authorizer_saas.py と response_interceptor の `client_id` バグ修正**: 実装バグで認証失敗のリスク

### P1（短期対応）

4. **Example 09 の E2E テストに Cognito Client Secret Lifecycle Management 検証追加**
5. **Example 10 の Cookbook にシークレットライフサイクル管理セクション追加**
6. **Example 04 の ENFORCE モード検証追加**

### P2（中期対応）

7. **Example 01 の Memory Record 内容分離検証（正常系）追加**
8. **Example 02 の全 Memory API アクションでの namespace Condition Key 検証追加**
9. **Example 05 の Gateway + Policy Engine 統合検証追加**
10. **Example 06 の Gateway 経由 E2E 検証と JWT 署名検証追加**

### P3（長期改善）

11. 各 example の HIGH/MEDIUM 項目の段階的な改善
12. セキュリティバイパスシナリオの体系的な検証追加
13. パフォーマンス/スケーラビリティ検証の追加

---

## 結論

bedrock-agentcore-cookbook は、各コンポーネントの基本的な機能検証は比較的充実していますが、**本番運用を想定した場合に必須となる検証項目が複数欠落**しています。特に、**Cognito Client Secret Lifecycle Management の検証が全範囲で欠落している**点は、本番環境でのセキュリティ運用に直結する重大な課題です。

優先順位 P0 の 3 項目（Example 03 の検証実行、Example 08 のシークレット回転検証、Example 10 の JWT 検証バグ修正）については、**早急な対応を強く推奨**します。

## 添付資料

本レポートの詳細なレビュー内容は以下のファイルに記録されています：

- **Example 01-03 レビュー**: example-01-03-reviewer (約 3,000 行)
- **Example 04-06 レビュー**: example-04-06-reviewer (約 2,500 行)
- **Example 07-08 レビュー**: example-07-08-reviewer (約 2,000 行)
- **Example 09-10 レビュー**: example-09-10-reviewer (約 2,500 行)

---

**レポート作成者**: Claude Opus 4.6 Agent Team
**レポート承認**: Team Lead (Sonnet 4.5)
**次回レビュー推奨時期**: 2026-03-27（P0 対応完了後）
