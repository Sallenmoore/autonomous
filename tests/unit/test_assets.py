from autonomous import assets


class TestAssets:
    def test_js_assets(self):
        path_dir = "src/autonomous/app_template/app/static/js"
        output_dir = "src/autonomous/app_template/app/static/js/main.min.js"
        assets.javascript(path=path_dir, output=output_dir)

    def test_css_assets(self):
        path_dir = "src/autonomous/app_template/app/static/style/sass/main.scss"
        output_dir = "src/autonomous/app_template/app/static/style/main.css"
        assets.dartsass(path=path_dir, output=output_dir)

    def test_build_assets(self):
        csspath_dir = "src/autonomous/app_template/app/static/style/sass/main.scss"
        cssoutput_dir = "src/autonomous/app_template/app/static/style/main.css"
        jspath_dir = "src/autonomous/app_template/app/static/js"
        jsoutput_dir = "src/autonomous/app_template/app/static/js/main.min.js"
        assets.build_assets(
            csspath=csspath_dir,
            cssoutput=cssoutput_dir,
            jspath=jspath_dir,
            jsoutput=jsoutput_dir,
        )
