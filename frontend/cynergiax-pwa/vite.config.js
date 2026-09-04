import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Cynergiax B2B2C',
        short_name: 'Cynergiax',
        description: 'Gestión y Reserva de Cargadores EV',
        theme_color: '#ffffff',
        background_color: '#ffffff',
        display: 'standalone', // Fuerza a que parezca app nativa (sin barra de URL)
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ]
      }
    })
  ]
})