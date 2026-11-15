from app.main import app
from bot_instance import setup_routes
from config import settings

setup_routes()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
