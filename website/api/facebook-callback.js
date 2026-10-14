// Single-user desktop OAuth relay. Credentials never enter this endpoint.
export default function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Referrer-Policy', 'no-referrer');
  if (req.method !== 'GET') return res.status(405).end();
  const url = new URL('http://127.0.0.1:8765/api/oauth/facebook/callback');
  for (const name of ['state', 'code', 'error']) {
    const value = req.query?.[name];
    if (typeof value === 'string' && value.length < 3500) url.searchParams.set(name, value);
  }
  if (!url.searchParams.has('state') && !url.searchParams.has('error')) return res.status(400).send('Missing account connection state');
  return res.redirect(302, url.toString());
}
