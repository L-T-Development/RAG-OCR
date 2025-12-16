import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import Home from './pages/Home'
import Compare from './pages/Compare'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/workspace" element={<Home />} />
      <Route path="/compare" element={<Compare />} />
    </Routes>
  )
}

export default App
