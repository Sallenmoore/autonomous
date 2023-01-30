import firebase_admin
import os

# Fetch the service account key JSON file contents
cred = firebase_admin.credentials.Certificate(os.getenv("FIREBASE_KEY_FILE"))

# Initialize the app with a service account, granting admin privileges
firebase_admin.initialize_app(
    cred,
    {"databaseURL": os.getenv("FIREBASE_URL")},
)


class AutoModel:
    id = None

    def save(self):
        if self.id:
            self.get_ref(self.id).update(self.__dict__)
        else:
            self.get_ref().push(value=self.__dict__)

    def delete(self):
        pass

    @classmethod
    def get(cls, id):
        data = cls.get_ref(id).get()
        obj = cls(**data)
        obj.id = data["id"]

    @classmethod
    def get_ref(cls, id=None):
        query = f"{cls.__name__}/{id}" if id else cls.__name__
        return firebase_admin.db.reference(query)
