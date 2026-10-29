import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { ShellProvider } from './components/Shell'
import { ToastProvider } from './components/Toast'
import ChatPage from './pages/ChatPage'
import DocsPage from './pages/DocsPage'
import KnowledgePage from './pages/KnowledgePage'
import MemoryPage from './pages/MemoryPage'
import VerificationPage from './pages/VerificationPage'

export default function App() {
  return (
    <ToastProvider>
      <ShellProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<ChatPage />} />
              {/* /workbench 是同一个对话工作台的固定地址，历史深链与自动化脚本都指向它。 */}
              <Route path="workbench" element={<ChatPage />} />
              <Route path="knowledge" element={<KnowledgePage />} />
              <Route path="memory" element={<MemoryPage />} />
              <Route path="verification" element={<VerificationPage />} />
              {/* 架构与接口页；/docs 由 FastAPI 的 OpenAPI(Swagger) 占用，SPA 深链不能同名。 */}
              <Route path="architecture" element={<DocsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ShellProvider>
    </ToastProvider>
  )
}
