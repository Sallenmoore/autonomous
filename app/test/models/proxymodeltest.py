from selflib.model.proxymodel import ProxyModel
from config import Config
class ProxyModelTest(ProxyModel): 
    API_URL=f"http://test:{Config.PORT}/modeltest"