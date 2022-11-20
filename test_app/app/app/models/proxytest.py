from autonomous import Config
from autonomous.model.proxymodel import ProxyModel

class ModelTest(ProxyModel): 
    API_URL=f"http://test:{Config.API_PORT}/modeltest"