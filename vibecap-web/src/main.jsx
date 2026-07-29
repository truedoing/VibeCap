import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink, useParams, Outlet } from 'react-router-dom'
import './index.css'
import { TaskProvider, EmptyProjectProvider } from './context/ProjectContext'
import Home from './pages/Home'
import SeriesPage from './pages/Series'
import MatchingDesk from './pages/MatchingDesk'
import Timeline from './pages/Timeline'
import { loadSeriesList, loadTask } from './model/series'

const subLink = ({ isActive }) =>
  `text-sm font-medium transition-colors ${isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}`

// ── 导航栏 ──
function AppLayout() {
  const { seriesId, taskId } = useParams()
  // seriesId 现在是电视剧名称（如"都挺好"）
  const isTaskPage = !!(seriesId && taskId)

  return (
    <>
      <header className="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur supports-backdrop-blur:bg-card/60">
        <div className="flex items-center gap-3 h-12 px-4">
          <NavLink to="/" className="flex items-center gap-2 shrink-0">
            <span className="text-primary font-bold text-base tracking-tight">VIBECAP</span>
            <span className="text-[10px] text-muted-foreground hidden sm:inline">分镜策划台</span>
          </NavLink>

          {seriesId && (
            <>
              <span className="text-border text-sm">/</span>
              <NavLink to="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors truncate max-w-[140px]">
                {seriesId === 'doutinghao' ? '都挺好' : decodeURIComponent(seriesId)}
              </NavLink>
            </>
          )}

          {taskId && (
            <>
              <span className="text-border text-sm">/</span>
              <span className="text-sm text-foreground font-medium truncate max-w-[140px]">{decodeURIComponent(taskId)}</span>
            </>
          )}

          {isTaskPage && (
            <nav className="flex items-center gap-3 ml-4">
              <NavLink to={`/${seriesId}/${taskId}/planning`} end className={subLink}>策划台</NavLink>
              <NavLink to={`/${seriesId}/${taskId}/timeline`} className={subLink}>剪辑台</NavLink>
            </nav>
          )}

          <div className="flex-1" />
          <span className="text-xs text-muted-foreground hidden sm:inline">API → :8765</span>
        </div>
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
              <Route path="planning" element={<MatchingDesk />} />
              <Route path="timeline" element={<Timeline />} />
            </Route>
          </Route>
        </Routes>
      </div>
    </BrowserRouter>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)
