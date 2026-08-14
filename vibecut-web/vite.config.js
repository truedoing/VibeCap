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
      '/narration': 'http://localhost:8765',
      '/narration.json': 'http://localhost:8765',
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
      '/tasks/description': 'http://localhost:8765',
      '/topics': 'http://localhost:8765',
      '/posters': 'http://localhost:8765',
      '/data': 'http://localhost:8765',
      '/picks': 'http://localhost:8765',
      '/proxies': 'http://localhost:8765',
      '^/asr/(raw|classified)': 'http://localhost:8765',
      '/script': 'http://localhost:8765',
      '/export': 'http://localhost:8765',
      '/export_clips': 'http://localhost:8765',
      '/voiceover': 'http://localhost:8765',
    }
  }
})
