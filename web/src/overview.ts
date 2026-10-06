export type ApiResult<T> =
  { ok: true; value: T } | { ok: false; error: string };
export type OverviewInput = {
  health: ApiResult<any>;
  providers: ApiResult<any[]>;
  defaultModel: ApiResult<any>;
  channels: ApiResult<any[]>;
  events: ApiResult<any[]>;
  mcp: ApiResult<any[]>;
  skills: ApiResult<any[]>;
  qqConfig: ApiResult<any>;
};

export function deriveOverview(input: OverviewInput) {
  const errors: string[] = [];
  const health = input.health.ok ? input.health.value : null;
  const providers = input.providers.ok ? input.providers.value : null;
  const channels = input.channels.ok ? input.channels.value : null;
  const events = input.events.ok ? input.events.value : null;
  const mcp = input.mcp.ok ? input.mcp.value : null;
  const skills = input.skills.ok ? input.skills.value : null;
  const qq = channels?.find((item) => item.channel === "qq");
  const qqConfigured =
    input.qqConfig.ok && Boolean(input.qqConfig.value?.endpoint);
  const enabledProviders =
    providers?.filter((item) => item.enabled && item.configured) ?? [];
  const enabledMcp = mcp?.filter((item) => item.enabled) ?? [];
  const enabledSkills = skills?.filter((item) => item.enabled) ?? [];
  const model = input.defaultModel.ok ? input.defaultModel.value : null;
  const failed =
    events?.filter((item) => item.status === "failed").length ?? null;
  const pending =
    events?.filter((item) => ["pending", "processing"].includes(item.status))
      .length ?? null;
  if (!health) errors.push("运行时状态不可用");
  if (!providers) errors.push("模型服务状态不可用");
  if (!input.defaultModel.ok) errors.push("默认模型状态不可用");
  if (!channels) errors.push("渠道状态不可用");
  if (!events) errors.push("渠道事件状态不可用");
  if (!mcp) errors.push("MCP 状态不可用");
  if (!skills) errors.push("Skills 状态不可用");
  const problems: string[] = [];
  if (health && (!health.started || health.degraded))
    problems.push(health.started ? "运行时降级" : "运行时未启动");
  if (providers && !enabledProviders.length) problems.push("未配置可用模型");
  if (
    model &&
    model.model &&
    providers &&
    !enabledProviders.some((item) => item.name === model.provider)
  )
    problems.push("默认模型 Provider 不可用");
  if (input.defaultModel.ok && !model?.model) problems.push("默认模型未配置");
  if (qqConfigured && (!qq || qq.status !== "connected"))
    problems.push("QQ 未连接");
  if (enabledMcp.some((item) => item.status !== "ready"))
    problems.push("启用的 MCP 异常");
  if (enabledSkills.some((item) => !item.available))
    problems.push("启用的 Skill 缺少依赖");
  if ((failed ?? 0) > 0) problems.push(`${failed} 条失败事件（最近 50 条）`);
  const complete = errors.length === 0;
  const label = !complete
    ? "检查不完整"
    : problems.length
      ? "需要检查"
      : "运行正常";
  return {
    health,
    providers,
    channels,
    events,
    mcp,
    skills,
    qq,
    qqConfigured,
    model,
    defaultModel: input.defaultModel.ok ? input.defaultModel.value : null,
    qqConfig: input.qqConfig,
    enabledProviders,
    enabledMcp,
    enabledSkills,
    failed,
    pending,
    problems,
    errors,
    complete,
    label,
  };
}
