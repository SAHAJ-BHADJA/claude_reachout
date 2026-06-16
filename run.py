"""Entry point: python run.py"""
import uvicorn
from app.config import cfg

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=cfg.APP_HOST, port=cfg.APP_PORT, reload=False)
