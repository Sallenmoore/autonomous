import os, sys, shutil

def createapp(app_name):
    """
    _summary_

    _extended_summary_

    Args:
        app_name (_type_): _description_
    """
    app_template = os.path.join(os.path.dirname(__file__), "app_template/app")

    shutil.copytree(app_template, f"./app/{app_name}")

    if not os.path.isdir("config"):
        os.mkdir("config")
        
    gunicorn_config_template = os.path.join(os.path.dirname(__file__), "app_template/config/gunicorn.conf.py")
    shutil.copy(gunicorn_config_template, "config/gunicorn.conf.py")
    nginx_config_template = os.path.join(os.path.dirname(__file__), "app_template/config/nginx.conf")
    shutil.copy(nginx_config_template, "config/nginx.conf")

    with open("config/nginx.conf", 'a+') as fptr:
        fptr.seek(0)
        updated_nginx_conf = fptr.read().replace("<template>", app_name)
        fptr.truncate(0)
        fptr.write(updated_nginx_conf)
        
    requirements_config_template = os.path.join(os.path.dirname(__file__), "app_template/config/requirements.txt")
    shutil.copy(requirements_config_template, "config/requirements.txt")
        
    docker_config_template = os.path.join(os.path.dirname(__file__), "app_template/config/test.Dockerfile")
    shutil.copy(docker_config_template, f"config/{app_name}.Dockerfile")

    env_config_template = os.path.join(os.path.dirname(__file__), "app_template/config/test.env")
    shutil.copy(env_config_template,f"config/{app_name}.env")
    
    dockercompose_template = os.path.join(os.path.dirname(__file__), "docker-compose.yml")
    shutil.copy(dockercompose_template, "docker-compose.yml")
    with open("docker-compose.yml", 'a+') as fptr:
        fptr.seek(0)
        updated_compose = fptr.read().replace("<template>", app_name)
        fptr.truncate(0)
        fptr.write(updated_compose)

    print("Make sure you verify the following:")
    print(f"\t 1. {app_name}.env with ports and other settings")
    print(f"\t 2. config/nginx.conf: ports to forward to your app")
    print(f"\t 3. docker-compose.yml: settings for your app")

def main():
    print(sys.argv)
    if len(sys.argv) <= 1:
        print("Please provide a task")
        return
    task = sys.argv[1]
    if task == "app":
        if len(sys.argv) < 3:
            print("Please provide an app name")
            return
        app_name = sys.argv[2]
        createapp(app_name)
    else:
        print("Unrecognized command")
        return

if __name__ == "__main__":
    main()