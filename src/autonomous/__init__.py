from autonomous.logger import Logger
log = Logger()

from autonomous.config import Config
config = Config()

from autonomous.handler import NetworkHandler

def response(handler = NetworkHandler, pickled=True):
  return handler.package(obj, unpicklable=pickled)

