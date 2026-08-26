const KEY = 'fit42-week';

function redisConfig() {
  const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
  if (!url || !token) return null;
  return { url, token };
}

async function redisCmd(config, ...args) {
  const r = await fetch(config.url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${config.token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(args),
  });
  if (!r.ok) throw new Error(`redis_http_${r.status}`);
  const data = await r.json();
  if (data.error) throw new Error(String(data.error));
  return data.result;
}

async function redisGet(config) {
  const raw = await redisCmd(config, 'GET', KEY);
  if (raw == null) return null;
  return typeof raw === 'string' ? JSON.parse(raw) : raw;
}

async function redisSet(config, value) {
  await redisCmd(config, 'SET', KEY, JSON.stringify(value));
}

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');

  const config = redisConfig();
  if (!config) {
    return res.status(503).json({ error: 'redis_unconfigured' });
  }

  if (req.method === 'GET') {
    try {
      const data = await redisGet(config);
      return res.status(200).json(data || { days: {}, updatedAt: 0 });
    } catch (err) {
      return res.status(503).json({ error: 'redis_unavailable', detail: String(err.message || err) });
    }
  }

  if (req.method === 'PUT') {
    const { days, updatedAt: clientTs } = req.body || {};
    if (!days || typeof days !== 'object' || Array.isArray(days)) {
      return res.status(400).json({ error: 'invalid_days' });
    }

    try {
      const existing = (await redisGet(config)) || { days: {}, updatedAt: 0 };
      const clientUpdatedAt = Number(clientTs) || 0;

      if (clientUpdatedAt < existing.updatedAt) {
        return res.status(409).json(existing);
      }

      const payload = { days, updatedAt: Date.now() };
      await redisSet(config, payload);
      return res.status(200).json(payload);
    } catch (err) {
      return res.status(503).json({ error: 'redis_unavailable', detail: String(err.message || err) });
    }
  }

  res.setHeader('Allow', 'GET, PUT');
  return res.status(405).end();
};
