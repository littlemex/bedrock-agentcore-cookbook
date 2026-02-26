// Chapter 13: Private Sharing 用 Cedar ポリシー
//
// [CRITICAL] 設計前提の検証結果（2026-02-24）:
// E2E検証により、Gateway処理順序は Interceptor → Cedar と判明。
// Interceptor が Allow してもCedarがdeny-by-defaultで拒否するため、
// 以下の 2 つの運用方式を検討すること:
//
// 代替案 A（最推奨）: Cedar を LOG_ONLY モードで運用
//   - 以下のポリシーは監査ログ用のみ
//   - 全認可判定は Request Interceptor が担当
//
// 代替案 B（推奨）: Cedar Set 型属性 + ENFORCE モード
//   - ポリシー 3 を追加し、Private Sharing も Cedar で判定
//   - AgentCore Policy Engine の Set 型サポートは E2E 未検証

// ポリシー 1: 所有者は自リソースにフルアクセス可能
permit (
  principal is AgentCore::OAuthUser,
  action,
  resource is AgentCore::Gateway
)
when {
  principal.hasTag("tenant_id") &&
  resource has "owner_tenant" &&
  principal.getTag("tenant_id") == resource.owner_tenant
};

// ポリシー 2: Public リソースは全テナントがアクセス可能
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"agents/invoke",
    AgentCore::Action::"tools/call"
  ],
  resource is AgentCore::Gateway
)
when {
  resource has "sharing_mode" &&
  resource.sharing_mode == "public"
};

// ポリシー 3（代替案 B のみ）: Private Sharing -- Set 型属性による共有先検証
// [WARNING] AgentCore Policy Engine の Set 型サポートは E2E 未検証
// Set.contains() は完全一致のメンバーシップテストであり、
// String.contains() の部分文字列マッチとは異なる
//
// permit (
//   principal is AgentCore::OAuthUser,
//   action in [
//     AgentCore::Action::"agents/invoke",
//     AgentCore::Action::"tools/call"
//   ],
//   resource is AgentCore::Gateway
// )
// when {
//   principal.hasTag("tenant_id") &&
//   resource has "shared_with_tenants" &&
//   resource.shared_with_tenants.contains(principal.getTag("tenant_id"))
// };
