import os
import logging

class Config:
    APP_NAME = os.environ.get("APP_NAME", "test")
    TESTING = os.environ.get("TESTING", False)
    DEBUG = os.environ.get("FLASK_DEBUG", False)
    FLASK_ENV = os.environ.get("FLASK_ENV", 'development')
    SECRET_KEY = os.environ.get("SECRET_KEY", "secretkey")
    HOST=os.environ.get('HOST', '0.0.0.0')
    PORT=os.environ.get('PORT', 6000)
    API_PORT=os.environ.get('API_PORT', 6000)
    LOG_LEVEL = logging.INFO
