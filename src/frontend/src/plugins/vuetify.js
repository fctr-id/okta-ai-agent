import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import { createVuetify } from 'vuetify'

export default createVuetify({
  theme: {
    defaultTheme: 'light',
    themes: {
      light: {
        colors: {
          primary: '#4C6EF5',
          'surface-variant': '#f1f5f9',
          background: '#ffffff',
          surface: '#ffffff',
          muted: '#94a3b8'
        }
      }
    }
  },
  defaults: {
    VCard: {
      rounded: 'lg'
    },
    VBtn: {
      variant: 'flat',
      rounded: 'pill'
    },
    VTextField: {
      variant: 'outlined',
      density: 'comfortable'
    }
  }
})