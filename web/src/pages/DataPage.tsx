import { useState } from "react";
import { StateCard } from "../components/StateCard";
import { errorText } from "../api";

export function DataPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function downloadBackup() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/data/backup", {
        method: "POST",
        headers: { "X-Zhiyu-Request": "1" },
      });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `备份失败：${response.status}`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "xingqi-backup.zip"; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="page-content data-page">
    <article className="panel">
      <span className="eyebrow">BACKUP</span>
      <h2>备份本机数据</h2>
      <p>备份包含数据库、Markdown 记忆和角色头像。API Key、Token、Keychain 内容、日志、缓存和本机 Skill 文件不会写入备份；恢复后需要重新配置密钥并重新安装本机 Skill。</p>
      <button className="primary" disabled={busy} onClick={() => void downloadBackup()}>{busy ? "正在生成…" : "下载数据备份"}</button>
    </article>
    <article className="panel">
      <span className="eyebrow">RESTORE</span>
      <h2>恢复到新数据目录</h2>
      <p>恢复不会覆盖当前数据。请在终端运行以下命令，并选择一个尚不存在的目标目录：</p>
      <pre><code>zhiyu data restore /path/to/xingqi-backup.zip --target /path/to/xingqi-restored</code></pre>
      <p>完成后，通过环境变量启动恢复的数据目录：</p>
      <pre><code>ZHIYU_DATA_DIR=/path/to/xingqi-restored zhiyu serve</code></pre>
      <p>Windows PowerShell：</p>
      <pre><code>$env:ZHIYU_DATA_DIR="C:\path\to\xingqi-restored"; zhiyu serve</code></pre>
      <p className="muted">旧版数据库会在启动时按现有迁移流程升级。跨设备恢复后，请重新配置模型和 QQ 密钥。</p>
    </article>
    {error && <StateCard title="备份失败" description={error} />}
  </section>;
}
