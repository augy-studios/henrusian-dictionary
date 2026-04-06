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
        // Paginate through all rows (Supabase hard-caps at 1000 per request)
        const PAGE = 1000;
        const baseUrl = `${supabaseUrl}/rest/v1/${table}?select=id,word,definition,created_at&order=word.asc&limit=${PAGE}`;
        const headers = {
            apikey: supabaseKey,
            Authorization: `Bearer ${supabaseKey}`,
            'Content-Type': 'application/json',
        };

        let entries = [];
        let offset = 0;

        while (true) {
            const response = await fetch(`${baseUrl}&offset=${offset}`, {
                headers: { ...headers, Range: `${offset}-${offset + PAGE - 1}` },
            });

            if (!response.ok) {
                const err = await response.text();
                console.error('Supabase error:', err);
                return res.status(response.status).json({ error: 'Failed to fetch from database.' });
            }

            const page = await response.json();
            entries = entries.concat(page);
            if (page.length < PAGE) break;
            offset += PAGE;
        }

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