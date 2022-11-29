import os, logging

class Config:
    APP_NAME = os.environ.get("APP_NAME", "app")
    
    DEBUG = os.environ.get("DEBUG", False)
    TESTING = DEBUG
    FLASK_ENV = 'development' if DEBUG else 'production'
    FLASK_DEBUG = DEBUG
    FLASK_SECRET_KEY = os.environ.get("NATASHA")
    SECRET_KEY = os.environ.get("SECRET_KEY", "secretkey")
    
    HOST=os.environ.get('HOST', '0.0.0.0')
    PORT=os.environ.get('PORT', 80)
    API_PORT=os.environ.get('API_PORT', '')
    
    LOG_LEVEL = os.environ.get("LOG_LEVEL", logging.INFO)