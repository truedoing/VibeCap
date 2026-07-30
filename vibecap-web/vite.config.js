import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 3000,
    proxy: {
      '/search': 'http://localhost:8765',
      '/preview_video': 'http://localhost:8765',
      '/assign': 'http://localhost:8765',
      '/status': 'http://localhost:8765',
      '/segments.json': 'http://localhost:8765',
      '/素材clips': 'http://localhost:8765',
      '/clips': 'http://localhost:8765',
      '/copy': 'http://localhost:8765',
      '/tts_segments': 'http://localhost:8765',
      '/storyboard_suggest': 'http://localhost:8765',
      '/chat': 'http://localhost:8765',
      '/dialogue_match': 'http://localhost:8765',
      '/dramas': 'http://localhost:8765',
      '/tasks': 'http://localhost:8765',
      '/tasks/create': 'http://localhost:8765',
      '/posters': 'http://localhost:8765',
      '/data': 'http://localhost:8765',
      '/picks': 'http://localhost:8765',
    }
  }
})
