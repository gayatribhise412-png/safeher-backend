from fastapi import APIRouter
from .auth import router as auth_router
from .user import router as user_router
from .sos import router as sos_router
from .chatbot import router as chatbot_router
from .emergency import router as emergency_router
from .location import router as location_router
from .fake_call import router as fake_call_router
from .notification import router as notification_router
from .voice_detection import router as voice_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(user_router)
api_router.include_router(sos_router)
api_router.include_router(chatbot_router)
api_router.include_router(emergency_router)
api_router.include_router(location_router)
api_router.include_router(fake_call_router)
api_router.include_router(notification_router)
api_router.include_router(voice_router)

__all__ = ["api_router"]
