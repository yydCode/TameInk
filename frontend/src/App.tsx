import { useEffect, useState } from "react";

import { getHealth } from "./api/client";

type BackendStatus = "checking" | "online" | "offline";

const statusLabels: Record<BackendStatus, string> = {
  checking: "正在连接",
  online: "后端在线",
  offline: "后端离线",
};

function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();

    getHealth({ signal: controller.signal }).then(
      () => {
        if (!controller.signal.aborted) setBackendStatus("online");
      },
      () => {
        if (!controller.signal.aborted) setBackendStatus("offline");
      },
    );

    return () => {
      controller.abort();
    };
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <h1>Tame Ink</h1>
        <div className={`status status--${backendStatus}`} role="status">
          <span className="status__indicator" aria-hidden="true" />
          {statusLabels[backendStatus]}
        </div>
      </header>
      <main className="workspace-shell" aria-label="写作工作区">
        <aside className="sidebar" aria-label="项目导航">
          <span>项目</span>
        </aside>
        <section className="empty-workspace">
          <h2>写作工作区</h2>
          <p>尚未打开项目</p>
        </section>
      </main>
    </div>
  );
}

export default App;
