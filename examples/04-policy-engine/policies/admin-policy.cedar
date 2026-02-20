// Admin ロール: 全ツールへのアクセスを許可
// principal.hasTag/getTag で JWT クレームを検証する
permit (
  principal is AgentCore::OAuthUser,
  action,
  resource is AgentCore::Gateway
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "admin"
};
