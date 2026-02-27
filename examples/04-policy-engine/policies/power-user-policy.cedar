// Power-user ロール: 特定の複数ツールへのアクセスを許可
// Admin と User の中間的なロールとして設計
// action in [...] で許可する複数ツールを列挙する
// principal.hasTag/getTag で JWT クレームを検証する（AgentCore 構文、E2E 検証済み）
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___read_file",
    AgentCore::Action::"mcp-target___list_directory",
    AgentCore::Action::"mcp-target___brave_web_search"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:776010787911:gateway/e2e-phase3-gateway-sytqnigmll"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "power-user"
};

// Power-user ロール: delete_file を明示的に拒否
// forbid ルールは permit より優先される
forbid (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___delete_file"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:776010787911:gateway/e2e-phase3-gateway-sytqnigmll"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "power-user"
};
