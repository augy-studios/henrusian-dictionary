const TABLE_MAP = {
    dict: 'henrusian15_dict',
    idioms: 'henrusian15_idioms',
    names: 'henrusian15_names',
};

export default async function handler(req, res) {
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    if (req.method !== 'GET') {
        return res.status(405).json({
            error: 'Method not allowed'
        });
    }

    const {
        tab = 'dict'
    } = req.query;

    const table = TABLE_MAP[tab];
    if (!table) {
        return res.status(400).json({
            error: 'Invalid tab. Use: dict, idioms, or names.'
        });
    }

    const supabaseUrl = process.env.SUPABASE_URL;
    const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

    if (!supabaseUrl || !supabaseKey) {
        return res.status(500).json({
            error: 'Supabase credentials not configured.'
        });
    }

    try {
        // Fetch all entries, ordered by word ascending
        const url = `${supabaseUrl}/rest/v1/${table}?select=id,word,definition,created_at&order=word.asc&limit=10000`;

        const response = await fetch(url, {
            headers: {
                apikey: supabaseKey,
                Authorization: `Bearer ${supabaseKey}`,
                'Content-Type': 'application/json',
                Range: '0-9999',
            },
        });

        if (!response.ok) {
            const err = await response.text();
            console.error('Supabase error:', err);
            return res.status(response.status).json({
                error: 'Failed to fetch from database.'
            });
        }

        const entries = await response.json();

        // Cache for 60 seconds on CDN edge
        res.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=120');
        return res.status(200).json({
            entries,
            count: entries.length,
            tab
        });

    } catch (err) {
        console.error('Handler error:', err);
        return res.status(500).json({
            error: 'Internal server error.'
        });
    }
}