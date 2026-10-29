import React from 'react'
import ReactDOM from 'react-dom/client'
// 全局基础样式必须先进打包队列：CSS 同名优先级相同时后出现的胜出，
// 反过来会让 .composer-send / .composer-select 这类页面级覆盖被基础类盖掉。
import './styles/global.css'
import App from './App'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('root element not found')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
