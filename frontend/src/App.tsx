import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/layout/AppShell";
import { HomePage } from "./pages/HomePage";

const CreativeWorkspacePage = lazy(() =>
  import("./pages/CreativeWorkspacePage").then((module) => ({ default: module.CreativeWorkspacePage })),
);
const CreativePage = lazy(() =>
  import("./pages/CreativePage").then((module) => ({ default: module.CreativePage })),
);
const StoryLibraryPage = lazy(() =>
  import("./pages/StoryLibraryPage").then((module) => ({ default: module.StoryLibraryPage })),
);
const ReviewPage = lazy(() =>
  import("./pages/ReviewPage").then((module) => ({ default: module.ReviewPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })),
);

export default function App() {
  return (
    <Suspense fallback={<div className="loading-state">加载工作区...</div>}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="projects/:projectId">
            <Route index element={<Navigate to="workspace" replace />} />
            <Route path="workspace" element={<CreativeWorkspacePage />} />
            <Route path="create" element={<CreativePage />} />
            <Route path="library" element={<StoryLibraryPage />} />
            <Route path="review" element={<ReviewPage />} />
            <Route path="*" element={<Navigate to="workspace" replace />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
