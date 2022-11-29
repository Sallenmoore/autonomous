from autonomous.config import Config
from autonomous.model.proxymodel import ProxyModel

class SubModelTest(ProxyModel): 
    API_URL=f"http://api:{Config.API_PORT}sub/modeltest"