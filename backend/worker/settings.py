"""
ARQ worker configuration.

Redis connection is configured via:
  REDIS_HOST  (default: localhost)
  REDIS_PORT  (default: 6379)
"""
import os
from arq.connections import RedisSettings


def get_redis_settings() -> RedisSettings:
    return RedisSettings(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
    )
