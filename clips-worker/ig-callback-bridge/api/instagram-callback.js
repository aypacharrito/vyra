// Optional HTTPS OAuth redirect relay for a SINGLE-USER LOCAL VYRA workstation.
// Deploy this small endpoint to your own Vercel domain. No credentials here.
// The authorizing browser and VYRA must run on the same computer.
// This is not a multi-user SaaS authentication service.
export default function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Referrer-Policy', 'no-referrer');
  if (req.method !== 'GET') return res.status(405).end();
  const url = new URL('http://127.0.0.1:8765/api/oauth/instagram/callback');
  for (const name of ['state', 'code', 'error']) {
    const value = req.query?.[name];
    if (typeof value === 'string' && value.length < 3500) url.searchParams.set(name, value);
  }
  if (!url.searchParams.has('state') && !url.searchParams.has('error'))
    return res.status(400).send('Missing Instagram OAuth state');
  return res.redirect(302, url.toString());
}
