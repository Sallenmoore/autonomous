from autonomous import assets


class TestAssets:
    csspath_dir = "src/autonomous/app_template/app/static/style/sass/main.scss"
    cssoutput_dir = "src/autonomous/app_template/app/static/style/main.css"
    js_files = "main"
    jspath_dir = "src/autonomous/app_template/app/static/js"
    jsoutput_dir = "src/autonomous/app_template/app/static/js/main.min.js"

    def test_js_assets(self):
        assets.javascript(path=TestAssets.jspath_dir, files=TestAssets.js_files)

    def test_css_assets(self):
        path_dir = "src/autonomous/app_template/app/static/style/sass/main.scss"
        output_dir = "src/autonomous/app_template/app/static/style/main.css"
        assets.dartsass(path=path_dir, output=output_dir)

    def test_build_assets(self):
        assets.build_assets(
            csspath=TestAssets.csspath_dir,
            cssoutput=TestAssets.cssoutput_dir,
            jspath=TestAssets.jspath_dir,
            jsfiles=TestAssets.js_files,
        )
