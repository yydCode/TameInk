import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/layout/AppShell";
import { EmptyPage } from "./pages/EmptyPage";
import { HomePage } from "./pages/HomePage";

const ChapterPage = lazy(() =>
  import("./pages/ChapterPage").then((module) => ({
    default: module.ChapterPage,
  })),
);
const BatchPlanningPage = lazy(() =>
  import("./pages/BatchPlanningPage").then((module) => ({
    default: module.BatchPlanningPage,
  })),
);
const CompletionPage = lazy(() =>
  import("./pages/CompletionPage").then((module) => ({
    default: module.CompletionPage,
  })),
);
const CommercialPage = lazy(() =>
  import("./pages/CommercialPage").then((module) => ({
    default: module.CommercialPage,
  })),
);
const MaterialLibraryPage = lazy(() =>
  import("./pages/MaterialLibraryPage").then((module) => ({
    default: module.MaterialLibraryPage,
  })),
);
const ImportPage = lazy(() =>
  import("./pages/ImportPage").then((module) => ({
    default: module.ImportPage,
  })),
);
const MemoryPage = lazy(() =>
  import("./pages/MemoryPage").then((module) => ({
    default: module.MemoryPage,
  })),
);
const OverviewPage = lazy(() =>
  import("./pages/OverviewPage").then((module) => ({
    default: module.OverviewPage,
  })),
);
const RunsPage = lazy(() =>
  import("./pages/RunsPage").then((module) => ({ default: module.RunsPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((module) => ({
    default: module.SettingsPage,
  })),
);
const StoryPage = lazy(() =>
  import("./pages/StoryPage").then((module) => ({ default: module.StoryPage })),
);
const MarketPage = lazy(() =>
  import("./pages/MarketPage").then((module) => ({
    default: module.MarketPage,
  })),
);
const OpeningPage = lazy(() =>
  import("./pages/OpeningPage").then((module) => ({
    default: module.OpeningPage,
  })),
);
const RulesPage = lazy(() =>
  import("./pages/RulesPage").then((module) => ({
    default: module.RulesPage,
  })),
);
const DecisionQueuePage = lazy(() =>
  import("./pages/DecisionQueuePage").then((module) => ({
    default: module.DecisionQueuePage,
  })),
);
const TodayWorkspacePage = lazy(() =>
  import("./pages/TodayWorkspacePage").then((module) => ({
    default: module.TodayWorkspacePage,
  })),
);
const BestsellerAnalyzePage = lazy(() =>
  import("./pages/BestsellerAnalyzePage").then((module) => ({
    default: module.BestsellerAnalyzePage,
  })),
);
const PatternTemplatePage = lazy(() =>
  import("./pages/PatternTemplatePage").then((module) => ({
    default: module.PatternTemplatePage,
  })),
);

export default function App() {
  return (
    <Suspense fallback={<div className="loading-state">加载工作区...</div>}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="overview" element={<EmptyPage section="项目概览" />} />
          <Route path="story" element={<EmptyPage section="故事设计" />} />
          <Route path="chapters" element={<EmptyPage section="章节工作台" />} />
          <Route path="commercial" element={<EmptyPage section="商业增长" />} />
          <Route path="memory" element={<EmptyPage section="记忆中心" />} />
          <Route path="batch-plan" element={<EmptyPage section="批量规划" />} />
          <Route path="materials" element={<EmptyPage section="素材库" />} />
          <Route path="completion" element={<EmptyPage section="完本规划" />} />
          <Route path="market" element={<EmptyPage section="市场调研" />} />
          <Route path="opening" element={<EmptyPage section="黄金三章" />} />
          <Route path="rules" element={<EmptyPage section="规则设置" />} />
          <Route path="decisions" element={<EmptyPage section="决策队列" />} />
          <Route path="bestseller" element={<EmptyPage section="爆款拆解" />} />
          <Route path="patterns" element={<EmptyPage section="套路模板" />} />
          <Route path="imports" element={<EmptyPage section="作品导入" />} />
          <Route path="runs" element={<EmptyPage section="运行记录" />} />
          <Route path="projects/:projectId">
            {/* 默认进入今日工作台，而不是项目概览 */}
            <Route index element={<Navigate to="today" replace />} />
            <Route path="today" element={<TodayWorkspacePage />} />
            <Route path="overview" element={<OverviewPage />} />
            <Route path="story" element={<StoryPage />} />
            <Route path="chapters" element={<ChapterPage />} />
            <Route path="chapters/:chapterId" element={<ChapterPage />} />
            <Route path="commercial" element={<CommercialPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="batch-plan" element={<BatchPlanningPage />} />
            <Route path="materials" element={<MaterialLibraryPage />} />
            <Route path="completion" element={<CompletionPage />} />
            <Route path="market" element={<MarketPage />} />
            <Route path="opening" element={<OpeningPage />} />
            <Route path="rules" element={<RulesPage />} />
            <Route path="decisions" element={<DecisionQueuePage />} />
            <Route path="bestseller" element={<BestsellerAnalyzePage />} />
            <Route path="patterns" element={<PatternTemplatePage />} />
            <Route path="imports" element={<ImportPage />} />
            <Route path="runs" element={<RunsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
