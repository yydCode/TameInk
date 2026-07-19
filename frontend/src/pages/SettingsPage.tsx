import { useEffect, useState } from "react";
import { KeyRound, PlugZap, Save } from "lucide-react";

import {
  getModelSettings,
  saveApiKey,
  saveModelSettings,
  testModelConnection,
} from "../api/client";

export function SettingsPage() {
  const [settings, setSettings] = useState({
    base_url: "",
    model: "",
    timeout: 30,
    disable_thinking: false,
  });
  const [hasKey, setHasKey] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState("未验证");
  const [latency, setLatency] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getModelSettings()
      .then((value) => {
        setSettings({
          base_url: value.base_url,
          model: value.model,
          timeout: value.timeout,
          disable_thinking: value.disable_thinking,
        });
        setHasKey(value.has_api_key);
      })
      .catch(() => undefined);
  }, []);
  async function save() {
    setError(null);
    try {
      const saved = await saveModelSettings(settings);
      setHasKey(saved.has_api_key);
      if (apiKey) {
        const key = await saveApiKey(apiKey);
        setHasKey(key.has_api_key);
        setApiKey("");
      }
      setStatus("已保存");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模型设置保存失败");
    }
  }
  async function connect() {
    setError(null);
    setStatus("正在验证");
    const started = performance.now();
    try {
      await testModelConnection();
      setLatency(Math.round(performance.now() - started));
      setStatus("连接正常");
    } catch (cause) {
      setStatus("连接失败");
      setError(cause instanceof Error ? cause.message : "模型连接失败");
    }
  }
  return (
    <section className="settings-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">全局配置</span>
          <h2>模型设置</h2>
          <p>
            一个 OpenAI-compatible 模型用于所有 Agent，密钥只保存在系统
            Keyring。
          </p>
        </div>
        <span className={`key-status ${hasKey ? "is-ready" : ""}`}>
          <KeyRound size={15} />
          {hasKey ? "密钥已保存" : "缺少密钥"}
        </span>
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      <div className="settings-grid">
        <label>
          Base URL
          <input
            value={settings.base_url}
            onChange={(event) =>
              setSettings({ ...settings, base_url: event.target.value })
            }
            placeholder="https://api.example.com/v1"
          />
        </label>
        <label>
          模型名
          <input
            value={settings.model}
            onChange={(event) =>
              setSettings({ ...settings, model: event.target.value })
            }
          />
        </label>
        <label>
          超时（秒）
          <input
            type="number"
            min="1"
            max="600"
            value={settings.timeout}
            onChange={(event) =>
              setSettings({ ...settings, timeout: Number(event.target.value) })
            }
          />
        </label>
        <label>
          API Key
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            autoComplete="new-password"
            placeholder={hasKey ? "留空保留现有密钥" : "输入 API Key"}
          />
        </label>
        <label className="toggle-field">
          <input
            type="checkbox"
            checked={settings.disable_thinking}
            onChange={(event) =>
              setSettings({
                ...settings,
                disable_thinking: event.target.checked,
              })
            }
          />
          <span>关闭模型推理模式</span>
        </label>
      </div>
      <div className="settings-actions">
        <button
          className="button button-secondary"
          type="button"
          onClick={save}
        >
          <Save size={15} />
          保存设置
        </button>
        <button
          className="button button-primary"
          type="button"
          onClick={connect}
        >
          <PlugZap size={15} />
          测试连接
        </button>
        <span>
          {status}
          {latency !== null ? ` · ${latency} ms` : ""}
        </span>
      </div>
    </section>
  );
}
