import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import Home from './pages/Home'
import Compare from './pages/Compare'
import Settings from './pages/Settings'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/workspace" element={<Home />} />
      <Route path="/compare" element={<Compare />} />
      <Route path="/settings" element={<Settings />} />
    </Routes>
  )
}

export default App
