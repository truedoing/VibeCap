import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 3001,
    proxy: {
      '/search': 'http://localhost:8766',
      '/preview_video': 'http://localhost:8766',
      '/assign': 'http://localhost:8766',
      '/status': 'http://localhost:8766',
      '/segments.json': 'http://localhost:8766',
      '/素材clips': 'http://localhost:8766',
      '/clips': 'http://localhost:8766',
      '/copy': 'http://localhost:8766',
      '/tts_segments': 'http://localhost:8766',
      '/storyboard_suggest': 'http://localhost:8766',
      '/chat': 'http://localhost:8766',
      '/dramas': 'http://localhost:8766',
      '/tasks': 'http://localhost:8766',
      '/tasks/create': 'http://localhost:8766',
      '/posters': 'http://localhost:8766',
    }
  }
})
