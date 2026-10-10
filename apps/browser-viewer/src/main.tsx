import { createRoot } from 'react-dom/client';
import dcv from 'dcv';
import { SessionViewer } from './SessionViewer';

createRoot(document.getElementById('root')!).render(<SessionViewer sdk={dcv} />);
