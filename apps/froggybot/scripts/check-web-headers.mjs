import { readFile } from 'node:fs/promises';

const routes = JSON.parse(await readFile('dist/_expo/.routes.json', 'utf8'));
const headers = routes.headers ?? {};
const required = {
  'Content-Security-Policy': ['frame-ancestors \'none\'', "object-src 'none'"],
  'Permissions-Policy': ['camera=()', 'geolocation=()'],
  'Referrer-Policy': ['strict-origin-when-cross-origin'],
  'X-Content-Type-Options': ['nosniff'],
  'X-Frame-Options': ['DENY'],
};

for (const [name, fragments] of Object.entries(required)) {
  const value = headers[name];
  if (typeof value !== 'string' || fragments.some((fragment) => !value.includes(fragment))) {
    throw new Error(`The exported web app is missing a valid ${name} header.`);
  }
}

console.log('Exported web security headers passed.');
