import crypto from 'node:crypto';

const GUEST_TTL_MS = 10 * 60 * 1000;

export default async function handler(req, res) {
    if (req.method !== 'GET') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const origin = req.headers.origin;
    if (origin) {
        const allowed = (process.env.ALLOWED_ORIGINS || '').split(',').map(o => o.trim()).filter(Boolean);
        if (!allowed.includes(origin)) {
            return res.status(403).json({ error: 'Origin not allowed' });
        }
    }

    const supabaseUrl = process.env.SUPABASE_URL;
    const supabaseKey = process.env.SUPABASE_SERVICE_KEY;
    if (!supabaseUrl || !supabaseKey) {
        return res.status(500).json({ error: 'Supabase credentials not configured.' });
    }

    const appId = String(req.query.app || 'unknown');
    const sessionToken = crypto.randomUUID();
    const signingKey = crypto.randomBytes(32).toString('hex');
    const now = Date.now();

    const row = {
        session_token: sessionToken,
        signing_key: signingKey,
        is_guest: true,
        app_id: appId,
        created_at: new Date(now).toISOString(),
        expires_at: new Date(now + GUEST_TTL_MS).toISOString(),
    };

    const insertRes = await fetch(`${supabaseUrl}/rest/v1/uwu_signing_keys`, {
        method: 'POST',
        headers: {
            apikey: supabaseKey,
            Authorization: `Bearer ${supabaseKey}`,
            'Content-Type': 'application/json',
            Prefer: 'return=minimal',
        },
        body: JSON.stringify(row),
    });

    if (!insertRes.ok) {
        const err = await insertRes.text();
        console.error('Supabase error:', err);
        return res.status(500).json({ error: 'Failed to issue guest key.' });
    }

    return res.status(200).json({ key_id: sessionToken, signing_key: signingKey });
}
