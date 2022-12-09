from autonomous.model.model import Model

class SubModelTest(Model): 
    def autoattributes(self):
        #log(self)
        return {
            "name": str,
            "number": int,
        }