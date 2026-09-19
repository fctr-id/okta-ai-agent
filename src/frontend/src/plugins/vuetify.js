import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import { Hint } from '../directives/hint'
import '../styles/tooltips.css'

export default createVuetify({
  directives: { Hint },
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
    VTooltip: {
      contentClass: 'app-tooltip',
      location: 'bottom',
      offset: 8,
      openDelay: 350,
      closeDelay: 100,
      openOnFocus: true,
      interactive: true,
      maxWidth: 320
    },
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
