import { Redis } from '@upstash/redis';

const redis = Redis.fromEnv();
const KEY = 'fit42-week';

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'GET') {
    try {
      const data = await redis.get(KEY);
      return res.status(200).json(data || { days: {}, updatedAt: 0 });
    } catch {
      return res.status(503).json({ error: 'redis_unavailable' });
    }
  }

  if (req.method === 'PUT') {
    const { days, updatedAt: clientTs } = req.body || {};
    if (!days || typeof days !== 'object' || Array.isArray(days)) {
      return res.status(400).json({ error: 'invalid_days' });
    }

    try {
      const existing = (await redis.get(KEY)) || { days: {}, updatedAt: 0 };
      const clientUpdatedAt = Number(clientTs) || 0;

      if (clientUpdatedAt < existing.updatedAt) {
        return res.status(409).json(existing);
      }

      const payload = { days, updatedAt: Date.now() };
      await redis.set(KEY, payload);
      return res.status(200).json(payload);
    } catch {
      return res.status(503).json({ error: 'redis_unavailable' });
    }
  }

  res.setHeader('Allow', 'GET, PUT');
  return res.status(405).end();
}
