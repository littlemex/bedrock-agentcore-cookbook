// Chapter 12: SaaSマルチテナント用Cedarポリシー

// Tenant-A Admin: 全ツール許可
permit (
  principal is AgentCore::OAuthUser,
  action,
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/gw-001"
)
when {
  principal.hasTag("tenant_id") &&
  principal.getTag("tenant_id") == "tenant-a" &&
  principal.hasTag("role") &&
  principal.getTag("role") == "admin"
};

// Tenant-A User: retrieve_docのみ
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"rag-server___retrieve_doc",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/gw-001"
)
when {
  principal.hasTag("tenant_id") &&
  principal.getTag("tenant_id") == "tenant-a" &&
  principal.hasTag("role") &&
  principal.getTag("role") == "user"
};

// 明示的なクロステナント拒否（Defense in Depth）
forbid (
  principal is AgentCore::OAuthUser,
  action,
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/gw-001"
)
when {
  !(principal.hasTag("tenant_id")) ||
  principal.getTag("tenant_id") != "tenant-a"
};
