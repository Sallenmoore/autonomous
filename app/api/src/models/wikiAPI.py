import requests
from mistletoe import Document, HTMLRenderer
import os
import urllib.parse
import logging
log = logging.getLogger()

class WikiAPI:
    WIKI_APIKEY = os.getenv("$WIKIKEY", "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcGkiOjIsImdycCI6MSwiaWF0IjoxNjYwODQ3NjI3LCJleHAiOjE3NTU1MjA0MjcsImF1ZCI6InVybjp3aWtpLmpzIiwiaXNzIjoidXJuOndpa2kuanMifQ.Pn0kXoX45rjA4xdOsHMNcEXkoaQv8ZOyjwuwK-zNr1DfMC6im6Dh4dacjSw_kCM7rmshiGDvzORbYnO-StJek75clfhmIxpV7VDpL8ZnU6N8trHqoeQfPriEEs5C-CkwtkjR-UKsvnQhnj5ENCqs6U66LLhiuSbbD7tVbEizDS7hMdcOIs-IZDVrXeqo7dogb00hSeabFUdP5GVsh71qXyOz51NoanmJDpHuy0mUznalrybgPJ06c_c2IFiyUvcAeGC1FHIVmpCLga1xclNxQFVuVvBIBjmqiFaQq5zy24AMzdrCl--pfkZ3fdQ94OH-JE6vXlrw68U-fBn51cEiDQ")

    def __init__(self, url = 'http://samoore.duckdns.org:44444/graphql', base_url=None):
        self.api = url
        self.base_url = base_url if base_url else urllib.parse.urlsplit(url)[1]

    def make_query(self, query):
        ## get list of associated pages
        log.debug(query)
            # TODO need ot move this key into environment variable
        headers= {
            "Authorization": f"Bearer {self.WIKI_APIKEY}", 
            "content-type": "application/json",
            "accept": "application/json"
        }
        
        r = requests.post(self.api, json={"query":query}, headers=headers)

        debug_msg = f'''
            status: {r.status_code} 
            raw response: {r.text},
            encoding: {r.encoding},
            headers: {r.headers},
        '''
        log.debug(debug_msg)
        r.raise_for_status()
        res = r.json()
        log.debug(f"res")
        return  res


    def get_page_by_id(self, id):
        query = f"""
        query {{
            pages {{
                single(id:{id}){{
                    description
                    title
                    content
                }}
            }}
        }}
        """
        response = self.make_query(query)
        return response['data']['pages']['single']
        
        
    def get_page_by_title(self, title, tag=None):
        query = """
            query {
                pages {
                    list"""
                    
        query += f'(tags:"{tag}")' if tag else ""
        query += "{"
                
        query += """
                            id
                            title
                            path
                    }
                }
            }
        """
        response = self.make_query(query)
        pages = response['data']['pages']['list']
        the_page = None
        for a_page in pages:
            if a_page['title'].lower() == title.lower():
                the_page = a_page
                break

        return self.get_page_by_id(the_page['id']) if the_page else None

    def get_folder_id(self, path, starting_id = 0):
        """
        recursively searches for the folder along the given path

        Args:
            path (list): _description_
            starting_id (int, optional): folder id. Defaults to 0.

        Returns:
            int: folder id
        """            
        #make this function non-destructive
        path = path[:]
        query = f"""
        query {{
            assets {{
                folders(parentFolderId: {starting_id}){{
                    id
                    slug
                    name
                }}
            }}
        }}
        """
        response = self.make_query(query)
        folders = response['data']['assets']['folders']
        for f in folders:
            if f['name'].lower() == path[0].lower():
                path.pop(0)
                if not path:
                    return f['id']
                else:
                    return self.get_folder_id(path, starting_id=f['id'])
        
    def get_asset_url(self, assets_path, name):
        path = '/'.join(assets_path)
        folder_id = self.get_folder_id(assets_path)
        query = f"""
            query {{
                assets {{
                    list(folderId: {folder_id}, kind:IMAGE){{
                        id
                        filename
                        ext
                    }}
                }}
            }}
        """
        filename = None
        result = self.make_query(query)
        for asset in result["data"]["assets"]["list"]:
            log.info(name.lower())
            log.info(asset['filename'].split('.')[0])
            if name.lower() == asset['filename'].split('.')[0].lower():
                filename = asset['filename']
                break
        url = self.base_url+'/'+path+'/'+filename if filename else None
        log.info(url)
        return url

    def wikipull(self, title=None, id=None, assets_path=None):
        """
        _summary_

        _extended_summary_

        Args:
            name (_type_): _description_

        Returns:
            _type_: _description_
        """

        ### get specific page ###
        page = None
        if title:
            page = self.get_page_by_title(title)
        elif id:
            page = self.get_page_by_id(title)

        if not page:
            return None

        content = page.get('content')
            
        data = {'content': page.get('content')}
        
        log.debug(data)

        if not assets_path:
            return data
            
        data['asset_url'] = f"http://{self.get_asset_url(assets_path, title)}"
        log.debug(data)
        return data
            

        


