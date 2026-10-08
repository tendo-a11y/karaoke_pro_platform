import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { startTranslation } from './i18n.js'

// Перевод интерфейса на выбранный язык (RU — без изменений).
startTranslation()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
