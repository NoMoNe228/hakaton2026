import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import 'plyr/dist/plyr.css'
import './styles.css'
import Home from './pages/Home.jsx'
import SearchPage from './pages/Search.jsx'
import Lecture from './pages/Lecture.jsx'
import Knowledge from './pages/Knowledge.jsx'
import Help from './pages/Help.jsx'
import SearchBox from './components/SearchBox.jsx'
import Health from './components/Health.jsx'
import StyleSwitch, { applyStyle, savedStyle } from './components/StyleSwitch.jsx'
import '@fontsource/nunito/400.css'
import '@fontsource/nunito/600.css'
import '@fontsource/nunito/700.css'
import '@fontsource/nunito/800.css'

// Стиль ставим до первой отрисовки, чтобы страница не мигала
applyStyle(savedStyle())

function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <Link to="/" className="logo">
          <img src="/favicon.svg" alt="" />
          <span>Суть</span>
        </Link>
        <SearchBox compact />
        <nav className="topnav">
          <NavLink to="/knowledge">Энциклопедия</NavLink>
          <NavLink to="/help">Справка</NavLink>
        </nav>
        <Health />
        <StyleSwitch />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/lecture/:id" element={<Lecture />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/help" element={<Help />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

createRoot(document.getElementById('root')).render(<App />)
