import os

import uvicorn

from backend.config import get_settings


if __name__ == '__main__':
    settings = get_settings()
    uvicorn.run(
        'backend.main:app',
        host=settings['host'],
        port=settings['port'],
        reload=settings['debug'],
        log_level='info' if not settings['debug'] else 'debug'
    )
