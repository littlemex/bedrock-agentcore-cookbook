// Chapter 5: ロール別アクセス制御の基本パターン

// ポリシー 1: Memory Admin（全Memory操作許可）
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___search_memory",
    AgentCore::Action::"mcp-target___store_memory",
    AgentCore::Action::"mcp-target___delete_memory"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:${ACCOUNT_ID}:gateway/gw-001"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "admin"
};

// ポリシー 2: Memory User（検索のみ許可）
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"mcp-target___search_memory",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:${ACCOUNT_ID}:gateway/gw-001"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "user"
};

// ポリシー 3: テナント + ロールの二重条件
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___search_memory",
    AgentCore::Action::"mcp-target___store_memory"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:${ACCOUNT_ID}:gateway/gw-001"
)
when {
  principal.hasTag("tenant_id") &&
  principal.getTag("tenant_id") == "tenant-a" &&
  principal.hasTag("role") &&
  (principal.getTag("role") == "admin" || principal.getTag("role") == "user")
};
