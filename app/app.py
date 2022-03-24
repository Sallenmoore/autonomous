
from src import create_app
#from sassutils.wsgi import SassMiddleware

#application factory
app = create_app()
# app.wsgi_app = SassMiddleware(
#     app.wsgi_app,
#     {
#         "app": {
#             "sass_path": "static/style/sass",
#             "css_path": "static/style",
#             "wsgi_path": "style",
#         }
#     },
# )

if __name__ == "__main__":
    app.run(
        host=app.config['HOST'],
        port=app.config['PORT'],
    )