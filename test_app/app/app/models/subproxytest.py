from autonomous import Config
from autonomous.model.proxymodel import ProxyModel

class SubModelTest(ProxyModel): 
    API_URL=f"http://test:{Config.API_PORT}sub/modeltest"