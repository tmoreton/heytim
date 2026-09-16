import { StrictMode } from 'react';
import { createRoot, hydrateRoot } from 'react-dom/client';
import { Website, pages } from './website';
import './styles/base.css';
import './styles/home.css';
import './styles/library.css';
import './styles/website.css';

const pathname = window.location.pathname;
document.title = pages[pathname.replace(/\/+$/, '') || '/'] ?? 'Page not found — FroggyBot';
const root = document.getElementById('root')!;
const website = <StrictMode><Website pathname={pathname} /></StrictMode>;
if (root.querySelector('header')) hydrateRoot(root, website);
else createRoot(root).render(website);
