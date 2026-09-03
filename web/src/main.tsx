import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { I18nProvider } from './i18n';
import './styles/base.css';

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

/* I18nProvider is outside BrowserRouter because language is not route state:
 * it is chosen before any route resolves, it survives every navigation, and
 * nothing about it belongs in the URL. It also owns <html lang>, which has to
 * be right for the whole document rather than for the matched route. */
createRoot(container).render(
  <StrictMode>
    <I18nProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
);
