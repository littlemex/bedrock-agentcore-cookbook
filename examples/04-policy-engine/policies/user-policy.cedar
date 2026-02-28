// User ロール: 特定ツール（retrieve_doc, list_tools）のみ許可
// action in [...] で複数ツールを明示的に列挙する
// principal.hasTag/getTag で JWT クレームを検証する（AgentCore 構文、E2E 検証済み）（AgentCore 構文、E2E 検証済み）
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___retrieve_doc",
    AgentCore::Action::"mcp-target___list_tools"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:${ACCOUNT_ID}:gateway/e2e-phase3-gateway-sytqnigmll"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "user"
};
