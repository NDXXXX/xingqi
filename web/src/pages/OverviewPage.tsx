import { deriveOverview } from "../overview";
import { StateCard } from "../components/StateCard";
import { stamp } from "../format";
import type { Page } from "../types";

type Props = {
  overview: ReturnType<typeof deriveOverview> | null;
  overviewLoading: boolean;
  refreshOverview: () => Promise<void>;
  navigate: (target: Page) => Promise<void>;
};

export function OverviewPage({ overview, overviewLoading, refreshOverview, navigate }: Props) {
  const renderOverviewBody = () => {
    const data = overview;
    if (overviewLoading && !data)
      return (
        <div className="page-content">
          <StateCard title="正在读取运行状态…" />
        </div>
      );
    if (!data)
      return (
        <div className="page-content">
          <StateCard
            title="运行状态不可用"
            action={
              <button className="quiet" onClick={() => void refreshOverview()}>
                重试
              </button>
            }
          />
        </div>
      );
    const statusClass = data.complete
      ? data.problems.length
        ? "warn"
        : "good"
      : "warn";
    const healthRows = [
      {
        name: "星栖运行时",
        detail: data.health ? "Web、Agent 与后台任务" : "接口读取失败",
        status: data.health
          ? data.health.started
            ? data.health.degraded
              ? "降级"
              : "运行中"
            : "未启动"
          : "未知",
        good: Boolean(data.health?.started && !data.health?.degraded),
        neutral: !data.health,
      },
      {
        name: "QQ / OneBot",
        detail:
          data.qq?.last_error ||
          data.qq?.ws_url ||
          (data.qqConfigured ? "已配置，等待连接" : "未配置或状态接口失败"),
        status: data.qq
          ? data.qq.status
          : !data.channels || !data.qqConfig.ok
            ? "未知"
            : data.qqConfigured
              ? "未连接"
              : "未配置",
        good: data.qq?.status === "connected",
        neutral:
          !data.qq &&
          Boolean(data.channels) &&
          data.qqConfig.ok &&
          !data.qqConfigured,
      },
      {
        name: "MCP",
        detail: !data.mcp
          ? "接口读取失败"
          : data.enabledMcp.length
            ? `${data.enabledMcp.filter((item) => item.status === "ready").length}/${data.enabledMcp.length} 个启用服务就绪`
            : "未启用（可选）",
        status: !data.mcp
          ? "未知"
          : data.enabledMcp.length
            ? data.enabledMcp.every((item) => item.status === "ready")
              ? "正常"
              : "需要检查"
            : "未启用",
        good: Boolean(
          data.mcp &&
          (!data.enabledMcp.length ||
            data.enabledMcp.every((item) => item.status === "ready")),
        ),
        neutral: Boolean(data.mcp && !data.enabledMcp.length),
      },
      {
        name: "Skills",
        detail: !data.skills
          ? "接口读取失败"
          : data.enabledSkills.length
            ? `${data.enabledSkills.filter((item) => item.available).length}/${data.enabledSkills.length} 个启用项可用`
            : "未启用（可选）",
        status: !data.skills
          ? "未知"
          : data.enabledSkills.some((item) => !item.available)
            ? "缺少依赖"
            : "正常",
        good: Boolean(
          data.skills && !data.enabledSkills.some((item) => !item.available),
        ),
        neutral: Boolean(data.skills && !data.enabledSkills.length),
      },
      {
        name: "记忆任务",
        detail: data.health
          ? `${data.health.memory_jobs?.completed ?? 0} 项已完成`
          : "运行时状态未知",
        status: data.health?.started
          ? "后台运行"
          : data.health
            ? "停止"
            : "未知",
        good: Boolean(data.health?.started),
        neutral: !data.health,
      },
    ];
    const runtimeText = data.health
      ? data.health.started
        ? data.health.degraded
          ? "部分降级"
          : "运行中"
        : "未启动"
      : "未知";
    const modelText = data.model?.model
      ? `${data.model.provider} · ${data.model.model}`
      : data.defaultModel
        ? "未配置"
        : "接口不可用";
    return (
      <div className="page-content">
        <div className="dashboard-top">
          <div className="dashboard-side">
            <article className="identity-card panel">
              <img className="identity-mark" src="/favicon.png" alt="" />
              <div>
                <strong>星栖</strong>
                <small>Personal Agent</small>
              </div>
              <span className={`status-pill ${statusClass}`}>
                {overviewLoading ? "刷新中" : data.label}
              </span>
            </article>
            <article className="system-card panel">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">SYSTEM</span>
                  <h2>系统信息</h2>
                </div>
              </div>
              <div className="system-lines">
                <div>
                  <span>运行状态</span>
                  <strong>{runtimeText}</strong>
                </div>
                <div>
                  <span>默认模型</span>
                  <strong title={modelText}>{modelText}</strong>
                </div>
                <div>
                  <span>QQ 主人</span>
                  <strong>
                    {data.qqConfig.ok
                      ? data.qqConfig.value?.owner_user_id || "未设置"
                      : "接口不可用"}
                  </strong>
                </div>
                <div>
                  <span>运行方式</span>
                  <strong>本机 · 单用户</strong>
                </div>
              </div>
            </article>
          </div>
          <article className="health-panel panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">SERVICE HEALTH</span>
                <h2>服务状态</h2>
              </div>
              <button
                className="text-button"
                onClick={() => void navigate("diagnostics")}
              >
                打开诊断 →
              </button>
            </div>
            <div className="health-list">
              {healthRows.map((row) => (
                <div className="health-row" key={row.name}>
                  <span
                    className={`health-indicator ${row.good ? "good" : row.neutral ? "neutral" : "warn"}`}
                  ></span>
                  <div className="health-copy">
                    <strong>{row.name}</strong>
                    <small>{row.detail}</small>
                  </div>
                  <span className="health-state">{row.status}</span>
                </div>
              ))}
            </div>
            {data.errors.length > 0 && (
              <p className="overview-warning">
                检查不完整：{data.errors.join("、")}
              </p>
            )}
            <div className="health-footnote">
              渠道事件统计仅覆盖最近 50 条记录，不代表完整队列。
            </div>
          </article>
        </div>
        <div className="counter-strip">
          <article className="counter-card counter-main">
            <strong>
              {data.providers ? data.enabledProviders.length : "未知"}
            </strong>
            <span>可用模型服务</span>
          </article>
          <article className="counter-card">
            <strong>
              {data.channels
                ? data.qq
                  ? data.qq.status === "connected"
                    ? "已连接"
                    : data.qq.status
                  : "未配置"
                : "未知"}
            </strong>
            <span>QQ 渠道</span>
          </article>
          <article className="counter-card">
            <strong>
              {data.mcp
                ? `${data.enabledMcp.filter((item) => item.status === "ready").length}/${data.enabledMcp.length}`
                : "未知"}
            </strong>
            <span>启用 MCP</span>
          </article>
          <article className="counter-card">
            <strong>
              {data.skills
                ? `${data.enabledSkills.filter((item) => item.available).length}/${data.enabledSkills.length}`
                : "未知"}
            </strong>
            <span>启用 Skills</span>
          </article>
          <article className="counter-card">
            <strong>{data.pending === null ? "未知" : data.pending}</strong>
            <span>待处理 · 最近 50 条</span>
          </article>
        </div>
        <article className="activity-panel panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">RECENT ACTIVITY</span>
              <h2>最近运行</h2>
            </div>
            <button
              className="text-button"
              onClick={() => void navigate("diagnostics")}
            >
              查看全部 →
            </button>
          </div>
          <div className="activity-layout">
            <div className="activity-callout">
              <span className="quote-mark">“</span>
              <p>
                {data.events
                  ? data.failed
                    ? `最近 50 条记录中有 ${data.failed} 条失败。`
                    : data.pending
                      ? `${data.pending} 条事件尚在处理中。`
                      : "最近 50 条渠道事件均已处理。"
                  : "事件状态不可用"}
              </p>
              <small>星栖 · 本地运行概览</small>
            </div>
            <div className="simple-list">
              {data.events ? (
                data.events.slice(0, 5).map((item, index) => (
                  <div className="list-row" key={item.id || index}>
                    <span className={`status-dot ${item.status}`}></span>
                    <span className="row-main">{item.status}</span>
                    <small>{stamp(item.received_at)}</small>
                  </div>
                ))
              ) : (
                <p className="muted">读取失败，无法展示渠道事件</p>
              )}
              {data.events?.length === 0 && (
                <p className="muted">暂无渠道事件</p>
              )}
            </div>
          </div>
        </article>
      </div>
    );
  };

  return renderOverviewBody();
}
