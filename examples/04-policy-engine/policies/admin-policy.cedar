// Admin ロール: 全ツールへのアクセスを許可
// principal.hasTag/getTag で JWT クレームを検証する（AgentCore 構文、E2E 検証済み）（AgentCore 構文、E2E 検証済み）
permit (
  principal is AgentCore::OAuthUser,
  action,
  resource is AgentCore::Gateway
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "admin"
};
