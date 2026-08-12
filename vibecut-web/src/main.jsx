import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useParams, Outlet } from 'react-router-dom'
import './index.css'
import { TaskProvider, EmptyProjectProvider } from './context/ProjectContext'
import Home from './pages/Home'
import SeriesPage from './pages/Series'
import VibeEdit from './pages/VibeEdit'
import PlanningDesk from './pages/PlanningDesk'
import DataDesk from './pages/DataDesk'
import VoiceDesk from './pages/VoiceDesk'
import { loadSeriesList, loadTask } from './model/series'

// ── 导航栏 ──
function AppLayout() {
  const { seriesId, taskId } = useParams()
  const isTaskPage = !!(seriesId && taskId)

  return (
    <>
      <header className="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur supports-backdrop-blur:bg-card/60">
        {/* 第一行：品牌 + 面包屑 */}
        <div className="flex items-center gap-2 h-10 px-4">
          <NavLink to="/" className="flex items-center gap-2 shrink-0">
            <svg width="20" height="20" viewBox="0 0 48 48" style={{ marginRight: 4 }}><polygon points="6,6 24,42 24,42" fill="#a78bfa"/><path d="M 14 18 L 24 42 L 34 18" stroke="#a78bfa" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" fill="none"/><line x1="2" y1="2" x2="16" y2="16" stroke="#22c55e" strokeWidth="3" strokeLinecap="round"/><line x1="46" y1="2" x2="32" y2="16" stroke="#22c55e" strokeWidth="3" strokeLinecap="round"/></svg>
            <span className="text-primary font-extrabold text-base tracking-tight">VibeCut</span>
          </NavLink>

          {seriesId && (
            <>
              <span className="text-border text-xs">/</span>
              <span className="text-xs text-muted-foreground truncate max-w-[140px]">
                {seriesId === 'doutinghao' ? '都挺好' : decodeURIComponent(seriesId)}
              </span>
            </>
          )}

          {taskId && (
            <>
              <span className="text-border text-xs">/</span>
              <span className="text-xs text-foreground/80 font-medium truncate max-w-[140px]">{decodeURIComponent(taskId)}</span>
            </>
          )}

          <div className="flex-1" />
          <span className="text-[10px] text-muted-foreground/50 hidden sm:inline">API :8765</span>
        </div>

        {/* 第二行：功能标签 — 始终显示 */}
        <nav className="flex items-center gap-1 px-4 h-8 border-t border-border/50 bg-secondary/30">
          {/* 项目：始终指向根路由 */}
          <NavLink to="/" end
            className={({ isActive }) =>
              `text-xs px-3 py-1 rounded-md transition-colors ${isActive ? 'bg-background text-foreground font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground hover:bg-background/50'}`
            }>项目</NavLink>

          {/* 数据台 / 编剧台 / 分镜台：仅在任务页可点击，否则置灰 */}
          {isTaskPage ? (
            <NavLink to={`/${seriesId}/${taskId}/data`}
              className={({ isActive }) =>
                `text-xs px-3 py-1 rounded-md transition-colors ${isActive ? 'bg-background text-foreground font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground hover:bg-background/50'}`
              }>数据台</NavLink>
          ) : (
            <span className="text-xs px-3 py-1 rounded-md text-muted-foreground/35 select-none">数据台</span>
          )}

          {isTaskPage ? (
            <NavLink to={`/${seriesId}/${taskId}/planning`}
              className={({ isActive }) =>
                `text-xs px-3 py-1 rounded-md transition-colors ${isActive ? 'bg-background text-foreground font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground hover:bg-background/50'}`
              }>编剧台</NavLink>
          ) : (
            <span className="text-xs px-3 py-1 rounded-md text-muted-foreground/35 select-none">编剧台</span>
          )}

          {isTaskPage ? (
            <NavLink to={`/${seriesId}/${taskId}/voice`}
              className={({ isActive }) =>
                `text-xs px-3 py-1 rounded-md transition-colors ${isActive ? 'bg-background text-foreground font-medium shadow-sm ring-1 ring-green/30' : 'text-green/80 hover:text-green hover:bg-background/50'}`
              }>配音台</NavLink>
          ) : (
            <span className="text-xs px-3 py-1 rounded-md text-muted-foreground/35 select-none">配音台</span>
          )}

          {isTaskPage ? (
            <NavLink to={`/${seriesId}/${taskId}/vibe`}
              className={({ isActive }) =>
                `text-xs px-3 py-1 rounded-md transition-colors ${isActive ? 'bg-background text-foreground font-medium shadow-sm ring-1 ring-purple/30' : 'text-purple/80 hover:text-purple hover:bg-background/50'}`
              }>分镜台</NavLink>
          ) : (
            <span className="text-xs px-3 py-1 rounded-md text-muted-foreground/35 select-none">分镜台</span>
          )}
        </nav>
      </header>

      <main className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </main>
    </>
  )
}

// ── TaskLayout：包裹任务级别页面，提供 TaskProvider ──
function TaskLayout() {
  return (
    <TaskProvider>
      <Outlet />
    </TaskProvider>
  )
}

// ── App ──
function App() {
  return (
    <BrowserRouter>
      <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
        <Routes>
          <Route element={<AppLayout />}>
            {/* 非任务页面 */}
            <Route index element={
              <EmptyProjectProvider><Home /></EmptyProjectProvider>
            } />
            <Route path=":seriesId" element={
              <EmptyProjectProvider><SeriesPage /></EmptyProjectProvider>
            } />
            {/* 任务页面 — 有 TaskProvider */}
            <Route path=":seriesId/:taskId" element={<TaskLayout />}>
              <Route index element={<Navigate to="data" replace />} />
              <Route path="data" element={<DataDesk />} />
              <Route path="planning" element={<PlanningDesk />} />
              <Route path="voice" element={<VoiceDesk />} />
              <Route path="timeline" element={<Navigate to="vibe" replace />} />
              <Route path="vibe" element={<VibeEdit />} />
            </Route>
          </Route>
        </Routes>
      </div>
    </BrowserRouter>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)
