import celery
import os


def make_taskrunner(app):
    class AutoTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = celery.Celery(
        "tasks",
        task_cls=AutoTask,
        backend=os.environ.get("CELERY_BACKEND", "rpc://user:bitnami@rabbitmq"),
        broker=os.environ.get("CELERY_BROKER_URL", "pyamqp://user:bitnami@rabbitmq"),
    )

    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app
