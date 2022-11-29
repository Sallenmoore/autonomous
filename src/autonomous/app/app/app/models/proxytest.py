from autonomous.config import Config
from autonomous.model.proxymodel import ProxyModel

class ModelTest(ProxyModel): 
    API_URL=f"http://api:{Config.API_PORT}/modeltest"