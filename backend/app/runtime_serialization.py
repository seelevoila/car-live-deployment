"""Hold a runtime model lease through the final streaming response body."""
import asyncio


class ModelLeaseMiddleware:
    PATHS = {'/tts', '/set_gpt_weights', '/set_sovits_weights', '/set_refer_audio', '/runtime/prime', '/runtime/adapt'}

    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'] in self.PATHS:
            async with self.lock:
                await self.app(scope, receive, send)
        else:
            await self.app(scope, receive, send)
