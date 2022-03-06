import os

class Config:
    TESTING = os.environ.get("TESTING", False)
    DEBUG = os.environ.get("FLASK_DEBUG", False)
    FLASK_ENV = os.environ.get("FLASK_ENV", 'development')
    SECRET_KEY = os.environ.get("SECRET_KEY", "none")

class ProdConfig(Config):
    FLASK_ENV = 'production'
    DEBUG = False
    TESTING = False


class DevConfig(Config):
    FLASK_ENV = 'development'
    DEBUG = True
    TESTING = True
