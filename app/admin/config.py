import os

class Config:
    TESTING = os.environ.get("TESTING", False)
    DEBUG = os.environ.get("FLASK_DEBUG", os.environ.get("DEBUG", False))
    FLASK_ENV = os.environ.get("FLASK_ENV", 'development')
    SECRET_KEY = os.environ.get("SECRET_KEY", "secretkey")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    HOST=os.environ.get('HOST', '0.0.0.0')
    PORT=os.environ.get('PORT', 80)
    SCSS_ASSET_DIR= os.environ.get("STATIC_DIR", "static")
    SCSS_STATIC_DIR=SCSS_ASSET_DIR

class ProdConfig(Config):
    FLASK_ENV = 'production'
    DEBUG = False
    TESTING = False
    LOG_LEVEL = "ERROR"


class DevConfig(Config):
    FLASK_ENV = 'development'
    DEBUG = True
    TESTING = True
    LOG_LEVEL = "INFO"
    #EXPLAIN_TEMPLATE_LOADING= os.environ.get("DEBUG", False)
