import json

from utils.rest_utils_databucket import DatabucketRestClient

BUCKET_NAME = 'bucket_name'

class Databucket:

    service_url = None
    user_name = None
    rest_client = None

    def __init__(self, headers, service_url: str, user_name: str, enable_logging: bool = False, enable_logging_headers: bool = False):
        self.headers = headers
        self.service_url = service_url
        self.user_name = user_name
        self.rest_client = DatabucketRestClient(enable_logging=enable_logging, headers=self.headers, log_headers=enable_logging_headers)

    def set_service_url(self, service_url: str):
        self.service_url = service_url

    def get_service_url(self) -> str:
        return self.service_url

    def set_user_name(self, user_name: str):
        self.user_name = user_name

    def set_proxy(self, proxy: str):
        self.rest_client.set_proxy(proxy)

    def insert_bundle(self, bucket_name: str, tag_name: str = 'default tag', lock: bool = False, properties: {} = None) -> int:
        resource = f'/buckets/{bucket_name}/bundles?userName=' + self.user_name
        payload = {'locked': lock, 'tag_name': tag_name, 'properties': properties}
        response = self.rest_client.post(url=self.service_url + resource, data=json.dumps(payload).encode('utf-8'))

        return response.json()['bundle_id']

    def get_bundle(self, bucket_name: str, bundle_id: int):
        resource = f'/buckets/{bucket_name}/bundles/{bundle_id}'

        response = self.rest_client.get(url=self.service_url + resource)
        resp_json = response.json()

        if resp_json['bundles'].__len__() == 1:
            bundle = resp_json['bundles'][0]
            bundle[BUCKET_NAME] = bucket_name
            return bundle
        else:
            return None

    def get_bundles_by_ids(self, bucket_name: str, bundles_ids: []):
        resource = f"/buckets/{bucket_name}/bundles/{','.join(map(str, bundles_ids))}"

        response = self.rest_client.get(url=self.service_url + resource)
        resp_json = response.json()

        if resp_json['bundles'].__len__() > 0:
            bundles = resp_json['bundles']
            for bundle in bundles:
                bundle[BUCKET_NAME] = bucket_name
            return bundles
        else:
            return None

    def get_bundles(self, bucket_name: str, conditions: [], limit: int = 1, random: bool = False) -> []:
        resource = f'/buckets/{bucket_name}/bundles/custom?limit={limit}'

        if random:
            resource += '&sort=rand()'
        else:
            resource += '&sort=bundle_id'

        payload = dict(conditions=conditions)
        response = self.rest_client.post(url=self.service_url + resource, data=json.dumps(payload, ensure_ascii=False))
        resp_json = response.json()

        if resp_json['bundles'].__len__() > 0:
            bundles = resp_json['bundles']
            for bundle in bundles:
                bundle[BUCKET_NAME] = bucket_name
            return bundles
        else:
            return None

    def lock_bundle(self, bucket_name: str, conditions: [], random: bool = False) -> {}:
        bundles = self.lock_bundles(bucket_name=bucket_name, conditions=conditions, limit=1, random=random)
        if bundles:
            bundle = bundles[0]
            bundle[BUCKET_NAME] = bucket_name
            return bundle
        else:
            return None

    def lock_bundles(self, bucket_name: str, conditions: [], limit: int = 1, random: bool = False) -> []:
        resource = f'/buckets/{bucket_name}/bundles/custom/lock?userName={self.user_name}&limit={limit}'

        if random:
            resource += '&sort=rand()'

        payload = dict(conditions=conditions)

        response = self.rest_client.post(url=self.service_url + resource, data=json.dumps(payload, ensure_ascii=False))
        resp_json = response.json()

        if 'bundles' in resp_json and resp_json['bundles'].__len__() > 0:
            bundles = resp_json['bundles']
            for bundle in bundles:
                bundle[BUCKET_NAME] = bucket_name
            return bundles
        else:
            return None


    def update_bundle(self, bucket_name: str, bundle_id: int, new_tag_name: str = None, new_lock: bool = None, new_properties: dict = None):
        resource = f'/buckets/{bucket_name}/bundles/{bundle_id}?userName={self.user_name}'

        payload = {}

        if new_tag_name is not None:
            payload['tag_name'] = new_tag_name

        if new_lock is not None:
            payload['locked'] = new_lock

        if new_properties is not None:
            payload['properties'] = new_properties

        self.rest_client.put(url=self.service_url + resource, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'))


    def delete_bundles(self, bucket_name: str):
        resource = f'/buckets/{bucket_name}/bundles'
        self.rest_client.delete(url=self.service_url + resource)
