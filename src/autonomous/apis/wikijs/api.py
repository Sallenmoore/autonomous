import json
import os

import requests
from slugify import slugify

from autonomous import log

from .page import WikiJSPage


class WikiJS:
    endpoint = f"{os.environ.get('WIKIJS_BASE_URL')}/{os.environ.get('WIKIJS_API_PATH', 'graphql')}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('WIKIJS_TOKEN')}",
    }

    @classmethod
    def make_request(cls, query, obj_vars=None):
        # log(query)
        # log(**obj_vars)

        variables = json.dumps(obj_vars)

        response = requests.post(
            WikiJS.endpoint,
            headers=cls.headers,
            json={"query": query, "variables": variables},
        )
        if response.status_code != 200:
            raise Exception(response.text)

        # log(response.text)

        return response

    @classmethod
    def get_page(cls, id):
        id = int(id)
        query = """
        query($id:Int!){
            pages{
                single(id:$id){
                    id
                    path
                    title
                    content
                    updatedAt
                    tags {
                        title
                    }
                    description
                }
            }
        }
        """
        res = cls.make_request(query, {"id": id})
        # log(res, res.text)
        return (
            WikiJSPage(**(res.json()["data"]["pages"]["single"]))
            if res.json()["data"]["pages"]["single"]
            else None
        )

    @classmethod
    def pull_tagged(cls, tags=None):
        query = """
            query($tags:[String!]!){
                pages{
                    list (tags: $tags){
                        id
                        path
                        title
                    }
                }
            }
        """
        # log(query)
        response = cls.make_request(query, {"tags": tags})
        # log(response.text)
        results = response.json()["data"]["pages"]["list"]
        # log(results)
        pages = [cls.get_page(p["id"]) for p in results]
        return pages

    @classmethod
    def create_page(cls, title, content, description, tags, path):
        if page := cls.find_by_path(path):
            return cls.update_page(
                page.id,
                title=title,
                content=content,
                description=description,
                tags=tags,
            )

        obj_vars = {
            "title": title,
            "content": content,
            "description": description,
            "tags": tags,
            "path": path,
        }
        query = """
        mutation($description:String!, $title:String!, $content:String!, $path:String!, $tags:[String!]!){
            pages
            {
                create (
                    content: $content,
                    description: $description,
                    title: $title,
                    tags: $tags,
                    path: $path,
                    isPublished: true,
                    isPrivate: false,
                    editor: "markdown",
                    locale: "en"
                    )
                {
                    page{
                        id
                        path
                        title
                    }
                    responseResult{
                        message
                        succeeded
                        errorCode
                    }
                }
            }
        }
        """

        response = cls.make_request(query, obj_vars)
        results = response.json()
        page = results["data"]["pages"]["create"]["page"]
        if not page:
            log(f"results: {response.json()['data']['pages']['create']['responseResult']}")
            return response.json()["data"]["pages"]["create"]["responseResult"]
        result = WikiJSPage(**page)
        return result

    @classmethod
    def update_page(cls, id, **kwargs):
        """
        params:
        - name: the name of the object
        - desc: the description of the object
        - wikijs_id: the id of the object in wikijs (**must provide either id or path**)
        - path: the path to the object in wikijs (**must provide either id or path**)
        - tags: a list of tags to add to the object
        """
        page = cls.get_page(id)
        obj_vars = {
            "id": id,
            "title": kwargs.get("title", page.title),
            "description": kwargs.get("description", page.description),
            "content": kwargs.get("content", page.content),
            "tags": kwargs.get("tags", page.tags),
        }
        query = """
        mutation($id:Int!, $description:String!, $title:String!, $content:String!, $tags:[String!]!){
            pages
            {
                update (
                    id: $id,
                    content: $content,
                    description: $description,
                    title: $title,
                    tags: $tags,
                    )
                {
                    page{
                        id
                        path
                        title
                    }
                    responseResult{
                        message
                        succeeded
                        errorCode
                    }
                }
            }
        }
        """

        res = cls.make_request(query, obj_vars)
        results = res.json()["data"]["pages"]["update"]["page"]
        if not results:
            log(f"results: {res.json()['data']['pages']['create']['responseResult']}")
            return
        result = WikiJSPage(**results)
        return result

    @classmethod
    def find_by_title(cls, title):
        query = """
            query($title:String!){
                pages
                {
                    search (query: $title)
                    {
                        results {
                            id
                            path
                            title
                        }
                    }
                }
            }
            """
        # log(query)
        response = cls.make_request(query, {"title": title})
        # log(response.text)
        results = response.json()["data"]["pages"]["search"]["results"]

        try:
            for p in results:
                # log(title, p)
                if title == p["title"]:
                    return int(p["id"])
        except KeyError as e:
            log(e)
            log(response.text)
        return None

    @classmethod
    def find_by_path(cls, path):
        if path.startswith("/"):
            path = path[1:]
        query = """
            query($path:String!){
                pages
                {
                    singleByPath (path: $path, locale: "en")
                    {
                        id
                        path
                        title
                    }
                }
            }
            """
        response = cls.make_request(query, {"path": path})
        #log(response.json())
        results = response.json()["data"]["pages"]["singleByPath"]
        return WikiJSPage(**results) if results else None

    @classmethod
    def remove_page(cls, id):
        # log(query)

        query = """
        mutation($id:Int!){
            pages{
                delete(id:$id){
                    responseResult{
                        message
                        errorCode
                        succeeded
                    }
                }
            }
        }
        """
        res = cls.make_request(query, {"id": id})
        return res.json()["data"]["pages"]["delete"]["responseResult"]["succeeded"]
