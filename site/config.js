// Local-dev defaults: sample data sits right next to index.html, and login
// is left unconfigured (login.html will just show a disabled button).
// scripts/deploy_site.sh generates the real values into build/site/config.js
// and uploads that separately -- it never overwrites this file, so this one
// stays on local-dev placeholders. Never hand-edit this for production.
export const MANIFEST_URL = "./manifest.json";
export const COGNITO_DOMAIN = "";     // e.g. https://your-gallery.auth.us-east-1.amazoncognito.com
export const COGNITO_CLIENT_ID = "";
export const REDIRECT_URI = "";       // e.g. https://gallery.example.com/auth/callback
